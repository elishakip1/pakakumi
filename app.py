import os
import sys
import time
import logging
import traceback
import gspread
from flask import Flask, render_template, jsonify
from google.oauth2.service_account import Credentials

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables - with detailed debugging
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
MAX_GAMES = 5000

def authenticate_google_sheets():
    """Authenticate with Google Sheets with detailed debugging"""
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
    """Retrieve game data from Google Sheets with detailed logging"""
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
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            logger.info("Accessing 'Games' worksheet")
            games_sheet = sh.worksheet("Games")
        except gspread.WorksheetNotFound:
            logger.error("'Games' worksheet not found in sheet")
            return []
        except gspread.APIError as e:
            logger.error(f"Google Sheets API error: {str(e)}")
            return []
        
        # Get all games (skip header)
        logger.info("Fetching data from worksheet...")
        try:
            all_games = games_sheet.get_all_values()
        except gspread.APIError as e:
            logger.error(f"Error retrieving sheet data: {str(e)}")
            return []
        
        logger.info(f"Found {len(all_games)} rows in sheet")
        
        if len(all_games) < 2:  # Header + at least one row
            logger.error(f"Only {len(all_games)} rows found. Need at least 2 rows (header + data)")
            return []
        
        # Format data
        games = []
        for i, row in enumerate(all_games[1:][:MAX_GAMES]):  # Skip header
            if len(row) >= 4:
                try:
                    games.append({
                        'id': int(row[0]),
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

@app.route('/')
def index():
    """Show game history"""
    games = get_game_data()
    game_count = len(games)
    return render_template('index.html', 
                           games=games,
                           game_count=game_count,
                           MAX_GAMES=MAX_GAMES,
                           SHEET_ID=SHEET_ID)

@app.route('/game/<int:game_id>')
def game_details(game_id):
    """Show game details placeholder"""
    return render_template('game_details.html', 
                           game_id=game_id,
                           SHEET_ID=SHEET_ID)

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