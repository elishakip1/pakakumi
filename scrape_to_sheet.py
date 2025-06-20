import os
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime

# Configuration
SHEET_ID = os.environ['SHEET_ID']
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
URL = "https://play.pakakumi.com/"
MAX_GAMES = 5000
REQUEST_DELAY = 0.2  # Delay between requests

def authenticate_google_sheets():
    """Authenticate with Google Sheets"""
    creds_json = os.environ["GOOGLE_CREDS_JSON"]
    if isinstance(creds_json, str):
        import json
        creds_json = json.loads(creds_json)
    
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    return gspread.authorize(creds)

def get_latest_game_id():
    """Get latest game ID from homepage"""
    try:
        response = requests.get(URL, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        game_links = soup.select('a[href^="/games/"]')
        if game_links:
            return int(game_links[0]['href'].split('/')[-1])
    except Exception as e:
        print(f"Error getting latest game ID: {str(e)}")
    return None

def scrape_game(game_id):
    """Scrape game data for a specific ID"""
    url = f"https://play.pakakumi.com/games/{game_id}"
    try:
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }, timeout=15)
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
        print(f"Error scraping game {game_id}: {str(e)}")
    return None

def update_sheet(gc):
    """Update Google Sheet with new games"""
    try:
        # Open the spreadsheet
        sh = gc.open_by_key(SHEET_ID)
        
        # Get or create worksheets
        try:
            games_sheet = sh.worksheet("Games")
        except gspread.WorksheetNotFound:
            games_sheet = sh.add_worksheet(title="Games", rows=MAX_GAMES+100, cols=10)
            games_sheet.append_row(["Game ID", "Multiplier", "Date", "Scraped At"])
        
        # Get existing game IDs
        existing_ids = []
        if games_sheet.row_count > 1:
            existing_ids = [int(row[0]) for row in games_sheet.get_all_values()[1:] if row]
        
        # Get latest game ID
        latest_id = get_latest_game_id()
        if not latest_id:
            print("Failed to get latest game ID")
            return 0
            
        # Determine starting ID (last in sheet or 5000 games back)
        start_id = max(1, latest_id - MAX_GAMES + 1) if not existing_ids else max(existing_ids) + 1
        
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
        
        # Append new games to sheet
        if new_games:
            games_sheet.append_rows(new_games)
            print(f"Added {len(new_games)} new games to sheet")
        
        # Trim sheet to MAX_GAMES
        all_games = games_sheet.get_all_values()[1:]  # Skip header
        if len(all_games) > MAX_GAMES:
            rows_to_delete = len(all_games) - MAX_GAMES
            games_sheet.delete_rows(2, rows_to_delete + 1)  # +1 for header offset
            print(f"Trimmed sheet to {MAX_GAMES} games")
        
        return len(new_games)
    except Exception as e:
        print(f"Error updating sheet: {str(e)}")
        return 0

def main():
    print("Starting data collection...")
    gc = authenticate_google_sheets()
    new_entries = update_sheet(gc)
    print(f"Added {new_entries} new game records")
    print("Data collection completed")

if __name__ == "__main__":
    main()