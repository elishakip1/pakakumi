import os
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime
import sys

# Configuration
SHEET_ID = os.environ['SHEET_ID']
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
URL = "https://play.pakakumi.com/"
MAX_GAMES = 5000
REQUEST_DELAY = 0.5  # Increased delay
RETRY_LIMIT = 3

print("Starting Pakakumi Scraper...")
print(f"Using Sheet ID: {SHEET_ID[:5]}...{SHEET_ID[-5:]}")

def authenticate_google_sheets():
    """Authenticate with Google Sheets"""
    print("Authenticating with Google Sheets...")
    try:
        creds_json = os.environ["GOOGLE_CREDS_JSON"]
        if isinstance(creds_json, str):
            import json
            creds_json = json.loads(creds_json)
        
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        gc = gspread.authorize(creds)
        print("Google Sheets authentication successful!")
        return gc
    except Exception as e:
        print(f"Authentication failed: {str(e)}")
        sys.exit(1)

def get_latest_game_id():
    """Get latest game ID from homepage"""
    print("Fetching latest game ID...")
    for _ in range(RETRY_LIMIT):
        try:
            response = requests.get(URL, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            game_links = soup.select('a[href^="/games/"]')
            if game_links:
                latest_id = int(game_links[0]['href'].split('/')[-1])
                print(f"Latest game ID: {latest_id}")
                return latest_id
            else:
                print("No game links found on homepage")
        except Exception as e:
            print(f"Error getting latest game ID: {str(e)}")
            time.sleep(2)
    return None

def scrape_game(game_id):
    """Scrape game data for a specific ID"""
    print(f"Scraping game {game_id}...")
    url = f"https://play.pakakumi.com/games/{game_id}"
    for attempt in range(RETRY_LIMIT):
        try:
            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            game_data = {'id': game_id, 'multiplier': 0.0, 'date': 'Unknown'}
            
            # Extract round information
            round_info = soup.find('div', string='Round Information')
            if round_info:
                container = round_info.find_parent('div', recursive=False)
                if container:
                    rows = container.find_all('div', recursive=False)[1].find_all('div', recursive=False)
                    
                    for row in rows:
                        key_div = row.find('div', recursive=False)
                        value_div = key_div.find_next_sibling('div') if key_div else None
                        
                        if key_div and value_div:
                            key = key_div.get_text(strip=True)
                            value = value_div.get_text(strip=True)
                            
                            if key == 'Busted At':
                                try:
                                    game_data['multiplier'] = float(value.replace('x', ''))
                                except ValueError:
                                    pass
                            elif key == 'Date':
                                game_data['date'] = value
            
            # Add scrape timestamp
            game_data['scraped_at'] = datetime.utcnow().isoformat() + "Z"
            return game_data
        except Exception as e:
            print(f"Attempt {attempt+1} failed for game {game_id}: {str(e)}")
            time.sleep(1)
    return None

def update_sheet(gc):
    """Update Google Sheet with new games"""
    try:
        print("Opening Google Sheet...")
        sh = gc.open_by_key(SHEET_ID)
        
        # Get or create worksheets
        try:
            games_sheet = sh.worksheet("Games")
            print("Found existing 'Games' sheet")
        except gspread.WorksheetNotFound:
            print("Creating new 'Games' sheet")
            games_sheet = sh.add_worksheet(title="Games", rows=MAX_GAMES+100, cols=10)
            games_sheet.append_row(["Game ID", "Multiplier", "Date", "Scraped At"])
        
        # Get existing game IDs
        print("Getting existing game IDs...")
        existing_ids = []
        if games_sheet.row_count > 1:
            existing_ids = [int(row[0]) for row in games_sheet.get_all_values()[1:] if row and row[0].isdigit()]
            print(f"Found {len(existing_ids)} existing games in sheet")
        
        # Get latest game ID
        latest_id = get_latest_game_id()
        if not latest_id:
            print("Failed to get latest game ID")
            return 0
            
        # Determine starting ID
        if existing_ids:
            start_id = max(existing_ids) + 1
        else:
            start_id = max(1, latest_id - 100)  # Start with recent 100 games
        
        print(f"Fetching games from {start_id} to {latest_id}")
        
        # Scrape new games
        new_games = []
        for game_id in range(start_id, latest_id + 1):
            game_data = scrape_game(game_id)
            if game_data:
                new_games.append([
                    game_data['id'],
                    game_data['multiplier'],
                    game_data['date'],
                    game_data['scraped_at']
                ])
            time.sleep(REQUEST_DELAY)
            
            # Save progress every 10 games
            if len(new_games) % 10 == 0 and new_games:
                games_sheet.append_rows(new_games)
                print(f"Added {len(new_games)} games so far...")
                new_games = []
        
        # Append any remaining games
        if new_games:
            games_sheet.append_rows(new_games)
            print(f"Added {len(new_games)} new games to sheet")
        
        # Trim sheet to MAX_GAMES
        all_games = games_sheet.get_all_values()[1:]  # Skip header
        if len(all_games) > MAX_GAMES:
            rows_to_delete = len(all_games) - MAX_GAMES
            print(f"Trimming sheet by deleting {rows_to_delete} old games...")
            games_sheet.delete_rows(2, rows_to_delete + 1)  # +1 for header offset
            print(f"Trimmed sheet to {MAX_GAMES} games")
        
        return len(new_games)
    except Exception as e:
        print(f"Error updating sheet: {str(e)}")
        return 0

def main():
    print("Starting data collection...")
    try:
        gc = authenticate_google_sheets()
        new_entries = update_sheet(gc)
        print(f"Added {new_entries} new game records")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
    print("Data collection completed")

if __name__ == "__main__":
    main()