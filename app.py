import os
import gspread
from flask import Flask, render_template
from google.oauth2.service_account import Credentials
import traceback
import sys

app = Flask(__name__)

# Configuration
try:
    SHEET_ID = os.environ['SHEET_ID']
    print(f"Using Sheet ID: {SHEET_ID[:5]}...{SHEET_ID[-5:]}")
except KeyError:
    print("ERROR: SHEET_ID environment variable not set!")
    SHEET_ID = None

try:
    PORT = os.environ['PORT']
except KeyError:
    PORT = 5000

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
MAX_GAMES = 5000

def authenticate_google_sheets():
    """Authenticate with Google Sheets"""
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json:
            print("ERROR: GOOGLE_CREDS_JSON environment variable not set!")
            return None
            
        if isinstance(creds_json, str):
            import json
            try:
                creds_json = json.loads(creds_json)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON in GOOGLE_CREDS_JSON: {str(e)}")
                return None
        
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"Authentication error: {str(e)}")
        traceback.print_exc()
        return None

def get_game_data():
    """Retrieve game data from Google Sheets"""
    if not SHEET_ID:
        print("SHEET_ID not set, skipping data retrieval")
        return []
    
    try:
        gc = authenticate_google_sheets()
        if not gc:
            print("Google Sheets authentication failed")
            return []
            
        print("Opening Google Sheet...")
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            games_sheet = sh.worksheet("Games")
            print("Found Games worksheet")
        except gspread.WorksheetNotFound:
            print("Games worksheet not found")
            return []
        except gspread.APIError as e:
            print(f"Google Sheets API error: {str(e)}")
            return []
        
        # Get all games (skip header)
        print("Retrieving game data...")
        try:
            all_games = games_sheet.get_all_values()
        except gspread.APIError as e:
            print(f"Error retrieving sheet data: {str(e)}")
            return []
        
        if len(all_games) < 2:  # Header + at least one row
            print("No game data in sheet (less than 2 rows)")
            return []
        
        # Format data
        games = []
        for i, row in enumerate(all_games[1:][:MAX_GAMES]):  # Skip header
            if len(row) >= 4:
                try:
                    game_id = int(row[0]) if row[0] else 0
                    multiplier = float(row[1]) if row[1] else 0.0
                    
                    games.append({
                        'id': game_id,
                        'multiplier': multiplier,
                        'date': row[2],
                        'scraped_at': row[3]
                    })
                except ValueError as e:
                    print(f"Error parsing row {i+2}: {row} - {str(e)}")
            else:
                print(f"Row {i+2} has insufficient columns: {row}")
        
        print(f"Successfully loaded {len(games)} games from sheet")
        return games
    except Exception as e:
        print(f"Unexpected error retrieving data: {str(e)}")
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
                           MAX_GAMES=MAX_GAMES)

@app.route('/game/<int:game_id>')
def game_details(game_id):
    """Show game details placeholder"""
    return render_template('game_details.html', game_id=game_id)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return "OK", 200

if __name__ == '__main__':
    # Initial debug output
    print("Starting Pakakumi Game History Tracker")
    print(f"Python version: {sys.version}")
    print(f"Environment variables: SHEET_ID={'set' if SHEET_ID else 'not set'}, GOOGLE_CREDS_JSON={'set' if 'GOOGLE_CREDS_JSON' in os.environ else 'not set'}")
    
    # Run the app
    app.run(host='0.0.0.0', port=int(PORT))