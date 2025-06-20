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
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
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
            # === vvv UPDATED CODE vvv ===
            # More realistic headers to mimic a real browser
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Host': 'play.pakakumi.com',
                'Upgrade-Insecure-Requests': '1'
            }
            # === ^^^ END OF UPDATE ^^^ ===

            response = requests.get(URL, headers=headers, timeout=15)
            response.raise_for_status()
            
            # UNCOMMENT THE LINE BELOW FOR DEEP DEBUGGING
            # logger.info(f"Homepage HTML (first 500 chars): {response.text[:500]}")

            soup = BeautifulSoup(response.text, 'html.parser')
            game_links = soup.select('a[href^="/games/"]')
            if game_links:
                latest_id = int(game_links[0]['href'].split('/')[-1])
                logger.info(f"Latest game ID found: {latest_id}")
                return latest_id
            else:
                logger.warning("No game links found on homepage on attempt %d", attempt + 1)
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed to get latest game ID: {str(e)}")
        
        time.sleep(2) # Wait before retrying
    return None

def scrape_game(game_id):
    """Scrape game data for a specific ID"""
    logger.info(f"Scraping game {game_id}...")
    url = f"https://play.pakakumi.com/games/{game_id}"
    for attempt in range(RETRY_LIMIT):
        try:
            # === vvv UPDATED CODE vvv ===
            # Using the same realistic headers for individual game pages
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Host': 'play.pakakumi.com',
                'Upgrade-Insecure-Requests': '1',
                'Referer': URL # Add Referer to look more legitimate
            }
            # === ^^^ END OF UPDATE ^^^ ===

            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()

            # UNCOMMENT THE LINE BELOW FOR DEEP DEBUGGING
            # logger.info(f"Game page HTML (first 500 chars): {response.text[:500]}")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            game_data = {'id': game_id, 'multiplier': 0.0, 'date': 'Unknown'}
            
            # Extract round information
            round_info = soup.find('div', string='Round Information')
            if round_info:
                container = round_info.find_parent('div', recursive=False)
                if container:
                    # This parsing logic is fragile. If it breaks, check the website's HTML structure.
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
        
        try:
            games_sheet = sh.worksheet("Games")
            logger.info("Found existing 'Games' sheet")
        except gspread.WorksheetNotFound:
            logger.info("Creating new 'Games' sheet")
            games_sheet = sh.add_worksheet(title="Games", rows=MAX_GAMES+100, cols=10)
            games_sheet.append_row(["Game ID", "Multiplier", "Date", "Scraped At"])
            logger.info("Created new 'Games' sheet with headers")
        
        logger.info("Getting existing game IDs...")
        existing_ids = set() # Use a set for faster lookups
        if games_sheet.row_count > 1:
            try:
                # Fetch only the first column to be more efficient
                id_column = games_sheet.col_values(1)[1:] 
                existing_ids = set(int(i) for i in id_column if i and i.isdigit())
                logger.info(f"Found {len(existing_ids)} existing games in sheet")
            except Exception as e:
                logger.error(f"Error reading existing IDs: {str(e)}")
        
        latest_id = get_latest_game_id()
        if not latest_id:
            logger.error("Failed to get latest game ID after all retries. Stopping.")
            return 0
            
        start_id = 1
        if existing_ids:
            start_id = max(existing_ids) + 1
            logger.info(f"Starting from game ID: {start_id} (after last existing game: {max(existing_ids)})")
        else:
            start_id = max(1, latest_id - 100)
            logger.info(f"Sheet is empty. Starting from game ID: {start_id} (fetching last 100 games)")
        
        if start_id > latest_id:
            logger.info(f"Sheet is already up to date. No new games to scrape (Last game in sheet: {start_id-1}, Latest game on site: {latest_id}).")
            return 0

        logger.info(f"Fetching games from {start_id} to {latest_id}")
        
        new_games_data = []
        for game_id in range(start_id, latest_id + 1):
            game_data = scrape_game(game_id)
            if game_data and game_data.get('date') != 'Unknown':
                new_games_data.append([
                    game_data['id'],
                    game_data['multiplier'],
                    game_data['date'],
                    game_data['scraped_at']
                ])
            time.sleep(REQUEST_DELAY)
            
            # Save progress every 20 games
            if len(new_games_data) >= 20:
                try:
                    games_sheet.append_rows(new_games_data, value_input_option='USER_ENTERED')
                    logger.info(f"Added a batch of {len(new_games_data)} games to sheet...")
                    new_games_data = []
                except Exception as e:
                    logger.error(f"Error saving batch: {str(e)}")
        
        # Append any remaining games
        if new_games_data:
            try:
                games_sheet.append_rows(new_games_data, value_input_option='USER_ENTERED')
                logger.info(f"Added final batch of {len(new_games_data)} new games to sheet")
            except Exception as e:
                logger.error(f"Error saving final batch: {str(e)}")
        
        # Trim sheet to MAX_GAMES
        try:
            # Re-fetch row count after adding new rows
            current_row_count = len(games_sheet.get_all_values())
            if current_row_count -1 > MAX_GAMES: # -1 for header
                rows_to_delete = (current_row_count -1) - MAX_GAMES
                logger.info(f"Trimming sheet by deleting {rows_to_delete} old games...")
                games_sheet.delete_rows(2, rows_to_delete + 1)
                logger.info(f"Trimmed sheet to {MAX_GAMES} games")
        except Exception as e:
            logger.error(f"Error trimming sheet: {str(e)}")
            
        return len(new_games_data)
    except Exception as e:
        logger.error(f"An unexpected error occurred in update_sheet: {e}", exc_info=True)
        return 0

def main():
    logger.info("Starting data collection script...")
    gc = authenticate_google_sheets()
    if not gc:
        logger.error("Authentication failed, exiting.")
        return
        
    update_sheet(gc)
    logger.info("Data collection script finished.")

if __name__ == "__main__":
    main()
