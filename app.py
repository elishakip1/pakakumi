import os
import gspread
from flask import Flask, render_template
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Configuration
SHEET_ID = os.environ['SHEET_ID']
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
MAX_GAMES = 5000

def authenticate_google_sheets():
    """Authenticate with Google Sheets"""
    creds_json = os.environ["GOOGLE_CREDS_JSON"]
    if isinstance(creds_json, str):
        import json
        creds_json = json.loads(creds_json)
    
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    return gspread.authorize(creds)

def get_game_data():
    """Retrieve game data from Google Sheets"""
    try:
        gc = authenticate_google_sheets()
        sh = gc.open_by_key(SHEET_ID)
        games_sheet = sh.worksheet("Games")
        
        # Get all games (skip header)
        all_games = games_sheet.get_all_values()[1:]
        
        # Format data
        games = []
        for row in all_games[:MAX_GAMES]:
            if len(row) >= 4:
                games.append({
                    'id': int(row[0]),
                    'multiplier': float(row[1]) if row[1] else 0.0,
                    'date': row[2],
                    'scraped_at': row[3]
                })
        return games
    except Exception as e:
        print(f"Error retrieving data from sheet: {str(e)}")
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
    """Show game details (placeholder - could be extended)"""
    return render_template('game_details.html', game_id=game_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))