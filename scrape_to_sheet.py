import os
import sys
import time
import random
import json
import logging
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Configuration
SHEET_ID = os.environ.get('SHEET_ID')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
URL = "https://play.pakakumi.com/"
MAX_GAMES = 5000
REQUEST_DELAY = 1.0  # Increased delay
RETRY_LIMIT = 3

# Log environment variables
logger.info(f"SHEET_ID: {SHEET_ID[:5]}...{SHEET_ID[-5:] if SHEET_ID else 'None'}")
logger.info(f"GOOGLE_CREDS_JSON: {'SET' if 'GOOGLE_CREDS_JSON' in os.environ else 'MISSING'}")

# Random User-Agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
]

def authenticate_google_sheets():
    """Authenticate with Google Sheets"""
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json:
            logger.error("GOOGLE_CREDS_JSON environment variable is missing!")
            return None
            
        # Try to parse JSON to validate
        try:
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
            return None
    except Exception as e:
        logger.error(f"Unexpected authentication error: {str(e)}")
        return None

def get_latest_game_id():
    """Get latest game ID from homepage"""
    for attempt in range(RETRY_LIMIT):
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = requests.get(URL, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            game_links = soup.select('a[href^="/games/"]')
            if game_links:
                latest_id = int(game_links[0]['href'].split('/')[-1])
                logger.info(f"Latest game ID: {latest_id}")
                return latest_id
            else:
                logger.warning("No game links found on homepage")
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed to get latest game ID: {str(e)}")
            time.sleep(2)
    return None

def scrape_game(game_id):
    """Scrape game data for a specific ID"""
    logger.info(f"Scraping game {game_id}...")
    url = f"https://play.pakakumi.com/games/{game_id}"
    for attempt in range(RETRY_LIMIT):
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = requests.get(url, headers=headers, timeout=20)
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
            logger.error(f"Attempt {attempt+1} failed for game {game_id}: {str(e)}")
            time.sleep(1)
    return None

def update_sheet(gc):
    """Update Google Sheet with new games"""
    try:
        logger.info("Opening Google Sheet...")
        sh = gc.open_by_key(SHEET_ID)
        
        # Get or create worksheets
        try:
            games_sheet = sh.worksheet("Games")
            logger.info("Found existing 'Games' sheet")
        except gspread.WorksheetNotFound:
            logger.info("Creating new 'Games' sheet")
            games_sheet = sh.add_worksheet(title="Games", rows=MAX_GAMES+100, cols=10)
            games_sheet.append_row(["Game ID", "Multiplier", "Date", "Scraped At"])
            logger.info("Created new 'Games' sheet with headers")
        
        # Get existing game IDs
        logger.info("Getting existing game IDs...")
        existing_ids = []
        if games_sheet.row_count > 1:
            try:
                existing_ids = [int(row[0]) for row in games_sheet.get_all_values()[1:] if row and row[0].isdigit()]
                logger.info(f"Found {len(existing_ids)} existing games in sheet")
            except Exception as e:
                logger.error(f"Error reading existing IDs: {str(e)}")
        
        # Get latest game ID
        latest_id = get_latest_game_id()
        if not latest_id:
            logger.error("Failed to get latest game ID")
            return 0
            
        # Determine starting ID
        if existing_ids:
            start_id = max(existing_ids) + 1
            logger.info(f"Starting from game ID: {start_id} (after last existing game)")
        else:
            start_id = max(1, latest_id - 100)  # Start with recent 100 games
            logger.info(f"Starting from game ID: {start_id} (first run)")
        
        logger.info(f"Fetching games from {start_id} to {latest_id}")
        
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
                try:
                    games_sheet.append_rows(new_games)
                    logger.info(f"Added {len(new_games)} games so far...")
                    new_games = []
                except Exception as e:
                    logger.error(f"Error saving batch: {str(e)}")
        
        # Append any remaining games
        if new_games:
            try:
                games_sheet.append_rows(new_games)
                logger.info(f"Added {len(new_games)} new games to sheet")
            except Exception as e:
                logger.error(f"Error saving final batch: {str(e)}")
        
        # Trim sheet to MAX_GAMES
        try:
            all_games = games_sheet.get_all_values()[1:]  # Skip header
            if len(all_games) > MAX_GAMES:
                rows_to_delete = len(all_games) - MAX_GAMES
                logger.info(f"Trimming sheet by deleting {rows_to_delete} old games...")
                games_sheet.delete_rows(2, rows_to_delete + 1)  # +1 for header offset
                logger.info(f"Trimmed sheet to {MAX_GAMES} games")
        except Exception as e:
            logger.error(f"Error trimming sheet: {str(e)}")
        
        return len(new_games)
    except Exception as e:
        logger.error(f"Error updating sheet: {str(e)}")
        traceback.print_exc()
        return 0

def main():
    logger.info("Starting data collection...")
    try:
        gc = authenticate_google_sheets()
        if not gc:
            logger.error("Authentication failed, exiting")
            return
            
        new_entries = update_sheet(gc)
        logger.info(f"Added {new_entries} new game records")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        traceback.print_exc()
    logger.info("Data collection completed")

if __name__ == "__main__":
    main()