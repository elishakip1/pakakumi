import os
import sys
import time
import logging
import traceback
import gspread
from flask import Flask, render_template, jsonify, request
from google.oauth2.service_account import Credentials

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables
def get_env_vars():
    """Get and log environment variables"""
    env_vars = {
        'SHEET_ID': os.environ.get('SHEET_ID'),
        'PORT': os.environ.get('PORT', '5000'),
        'GOOGLE_CREDS_JSON': 'SET' if 'GOOGLE_CREDS_JSON' in os.environ else 'MISSING'
    }
    
    logger.info("Environment Variables:")
    for key, value in env_vars.items():
        logger.info(f"  {key}: {value[:20] + '...' if value and len(value) > 20 else value}")
    
    return env_vars

# Get env vars early
env = get_env_vars()
SHEET_ID = env['SHEET_ID']
PORT = int(env['PORT'])
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
MAX_GAMES = 100000
DEFAULT_THRESHOLD = 2.0  # Default win threshold

def authenticate_google_sheets():
    """Authenticate with Google Sheets"""
    logger.info("Authenticating with Google Sheets...")
    
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json:
            logger.error("GOOGLE_CREDS_JSON environment variable is missing!")
            return None
            
        # Try to parse JSON to validate
        try:
            import json
            parsed_creds = json.loads(creds_json)
            logger.info("GOOGLE_CREDS_JSON parsed successfully")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in GOOGLE_CREDS_JSON: {str(e)}")
            return None
        
        try:
            creds = Credentials.from_service_account_info(parsed_creds, scopes=SCOPES)
            gc = gspread.authorize(creds)
            logger.info("Google Sheets authentication successful")
            return gc
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            traceback.print_exc()
            return None
    except Exception as e:
        logger.error(f"Unexpected authentication error: {str(e)}")
        traceback.print_exc()
        return None

def get_game_data():
    """Retrieve game data from Google Sheets with duplicate prevention"""
    logger.info("Retrieving game data from Google Sheets...")
    
    if not SHEET_ID:
        logger.error("SHEET_ID not set, skipping data retrieval")
        return []
    
    try:
        start_time = time.time()
        gc = authenticate_google_sheets()
        if not gc:
            logger.error("Google Sheets authentication failed")
            return []
            
        logger.info(f"Opening sheet with ID: {SHEET_ID[:5]}...{SHEET_ID[-5:]}")
        try:
            sh = gc.open_by_key(SHEET_ID)
        except gspread.SpreadsheetNotFound:
            logger.error(f"Spreadsheet with ID {SHEET_ID[:5]}...{SHEET_ID[-5:]} not found!")
            return []
        
        # Access worksheet
        try:
            logger.info("Accessing 'Games' worksheet")
            games_sheet = sh.worksheet("Games")
        except gspread.WorksheetNotFound:
            logger.error("'Games' worksheet not found")
            return []
        except gspread.APIError as e:
            logger.error(f"Google Sheets API error: {str(e)}")
            return []
        
        logger.info("Fetching data from worksheet...")
        try:
            all_games = games_sheet.get_all_values()
        except gspread.APIError as e:
            logger.error(f"Error retrieving sheet data: {str(e)}")
            return []
        
        logger.info(f"Found {len(all_games)} rows in sheet")
        
        if len(all_games) < 2:  # Header + at least one row
            logger.info("Sheet has headers but no game data yet")
            return []
        
        # Format data with duplicate prevention
        seen_ids = set()
        games = []
        for i, row in enumerate(all_games[1:][:MAX_GAMES]):  # Skip header
            if len(row) >= 4:
                try:
                    game_id = int(row[0])
                    
                    # Skip duplicate game IDs
                    if game_id in seen_ids:
                        logger.warning(f"Duplicate game ID skipped: {game_id}")
                        continue
                    seen_ids.add(game_id)
                    
                    games.append({
                        'id': game_id,
                        'multiplier': float(row[1]) if row[1] else 0.0,
                        'date': row[2],
                        'scraped_at': row[3]
                    })
                except ValueError as e:
                    logger.error(f"Error parsing row {i+2}: {row} - {str(e)}")
            else:
                logger.error(f"Row {i+2} has only {len(row)} columns (needs 4)")
        
        logger.info(f"Successfully loaded {len(games)} games in {time.time()-start_time:.2f} seconds")
        return games
    except Exception as e:
        logger.error(f"Unexpected error retrieving data: {str(e)}")
        traceback.print_exc()
        return []

def calculate_streaks(games, win_threshold=DEFAULT_THRESHOLD):
    """Calculate winning and losing streaks from game data with custom threshold"""
    stats = {
        'longest_win_streak': 0,
        'longest_loss_streak': 0,
        'highest_multiplier': 0,
        'win_streaks': [],
        'loss_streaks': [],
        'gaps': [],
        'win_threshold': win_threshold,
        'total_games': 0,
        'total_wins': 0,
        'total_losses': 0,
        'total_streak_games': 0,
        'total_missing_games': 0
    }
    
    if not games:
        return stats
    
    # Sort games by ID (chronological order)
    sorted_games = sorted(games, key=lambda x: x['id'])
    stats['total_games'] = len(sorted_games)
    
    # Calculate wins and losses
    stats['total_wins'] = sum(1 for game in sorted_games if game['multiplier'] >= win_threshold)
    stats['total_losses'] = stats['total_games'] - stats['total_wins']
    
    # Find highest multiplier
    stats['highest_multiplier'] = max(game['multiplier'] for game in sorted_games)
    
    # Calculate streaks
    current_streak = 0
    current_type = None
    streak_start = sorted_games[0]['id']
    
    # Identify gaps in game IDs
    prev_id = sorted_games[0]['id']
    for game in sorted_games[1:]:
        if game['id'] != prev_id + 1:
            gap_length = game['id'] - prev_id - 1
            stats['gaps'].append({
                'start': prev_id + 1,
                'end': game['id'] - 1,
                'length': gap_length
            })
            stats['total_missing_games'] += gap_length
        prev_id = game['id']
    
    # Calculate streaks
    for game in sorted_games:
        is_win = game['multiplier'] >= win_threshold
        
        if current_type is None:
            current_type = is_win
            current_streak = 1
        elif current_type == is_win:
            current_streak += 1
        else:
            # Record completed streak
            streak = {
                'start': streak_start,
                'end': game['id'] - 1,
                'length': current_streak,
                'type': 'win' if current_type else 'loss'
            }
            
            if current_type:  # Win streak
                stats['win_streaks'].append(streak)
                if current_streak > stats['longest_win_streak']:
                    stats['longest_win_streak'] = current_streak
            else:  # Loss streak
                stats['loss_streaks'].append(streak)
                if current_streak > stats['longest_loss_streak']:
                    stats['longest_loss_streak'] = current_streak
            
            # Start new streak
            current_streak = 1
            current_type = is_win
            streak_start = game['id']
    
    # Handle the last streak
    streak = {
        'start': streak_start,
        'end': sorted_games[-1]['id'],
        'length': current_streak,
        'type': 'win' if current_type else 'loss'
    }
    if current_type:
        stats['win_streaks'].append(streak)
        if current_streak > stats['longest_win_streak']:
            stats['longest_win_streak'] = current_streak
    else:
        stats['loss_streaks'].append(streak)
        if current_streak > stats['longest_loss_streak']:
            stats['longest_loss_streak'] = current_streak
    
    # Sort streaks by length
    stats['win_streaks'] = sorted(stats['win_streaks'], key=lambda x: x['length'], reverse=True)
    stats['loss_streaks'] = sorted(stats['loss_streaks'], key=lambda x: x['length'], reverse=True)
    
    # Calculate total games in streaks
    stats['total_streak_games'] = stats['total_games']
    
    return stats

@app.route('/')
def index():
    """Show game history with pagination"""
    games = get_game_data()
    game_count = len(games)
    
    # Pagination - 500 games per page
    page = request.args.get('page', 1, type=int)
    per_page = 500
    
    # Calculate pagination indices
    total_pages = (game_count + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_games = games[start_idx:end_idx]
    
    return render_template('index.html', 
                           games=paginated_games,
                           game_count=game_count,
                           MAX_GAMES=MAX_GAMES,
                           SHEET_ID=SHEET_ID,
                           win_threshold=DEFAULT_THRESHOLD,
                           current_page=page,
                           total_pages=total_pages)

@app.route('/game/<int:game_id>')
def game_details(game_id):
    """Show game details placeholder"""
    return render_template('game_details.html', 
                           game_id=game_id,
                           SHEET_ID=SHEET_ID)

@app.route('/visualize')
def visualize():
    """Data visualization dashboard"""
    # Get threshold from query parameter or use default
    win_threshold = request.args.get('threshold', default=DEFAULT_THRESHOLD, type=float)
    games = get_game_data()
    stats = calculate_streaks(games, win_threshold)
    return render_template('visualize.html', 
                          stats=stats,
                          game_count=len(games),
                          MAX_GAMES=MAX_GAMES,
                          SHEET_ID=SHEET_ID,
                          win_threshold=win_threshold)

@app.route('/debug')
def debug_info():
    """Debug information endpoint"""
    debug_data = {
        'env': {
            'SHEET_ID': SHEET_ID,
            'PORT': PORT,
            'GOOGLE_CREDS_JSON_set': 'GOOGLE_CREDS_JSON' in os.environ
        },
        'status': 'running',
        'timestamp': time.time()
    }
    return jsonify(debug_data)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return "OK", 200

if __name__ == '__main__':
    logger.info("Starting Pakakumi Game History Tracker")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Running on port: {PORT}")
    
    # Run the app
    app.run(host='0.0.0.0', port=PORT)