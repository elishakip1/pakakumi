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
import re

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
REQUEST_DELAY = 1.0
RETRY_LIMIT = 5  # Increased retries

# Log environment variables
logger.info(f"SHEET_ID: {SHEET_ID[:5]}...{SHEET_ID[-5:] if SHEET_ID else 'None'}")
logger.info(f"GOOGLE_CREDS_JSON: {'SET' if 'GOOGLE_CREDS_JSON' in os.environ else 'MISSING'}")

# Enhanced headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1'
}

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
    """Get latest game ID from homepage with improved scraping"""
    for attempt in range(RETRY_LIMIT):
        try:
            logger.info(f"Fetching homepage (attempt {attempt+1})")
            response = requests.get(URL, headers=HEADERS, timeout=15)
            response.raise_for_status()
            
            # Debug: Save HTML for inspection
            # with open(f"homepage_{attempt}.html", "w", encoding="utf-8") as f:
            #     f.write(response.text)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Method 1: Try to find game links by href pattern
            game_links = soup.find_all('a', href=re.compile(r'^/games/\d+'))
            if game_links:
                latest_id = int(game_links[0]['href'].split('/')[-1])
                logger.info(f"Found latest game ID via href pattern: {latest_id}")
                return latest_id
                
            # Method 2: Look for game containers
            game_containers = soup.select('div.css-xy3rl8, div.css-1dbjc4n')
            if game_containers:
                for container in game_containers:
                    links = container.find_all('a')
                    if links:
                        href = links[0].get('href', '')
                        if href.startswith('/games/'):
                            latest_id = int(href.split('/')[-1])
                            logger.info(f"Found latest game ID via container: {latest_id}")
                            return latest_id
            
            # Method 3: Extract from script tags (if site uses JS)
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'games' in script.string:
                    match = re.search(r'/games/(\d+)', script.string)
                    if match:
                        latest_id = int(match.group(1))
                        logger.info(f"Found latest game ID via script tag: {latest_id}")
                        return latest_id
                        
            logger.warning("No game links found using any method")
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response size: {len(response.text)} characters")
            
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed: {str(e)}")
            time.sleep(2)
    
    logger.error("All attempts to get latest game ID failed")
    return None

def scrape_game(game_id):
    """Scrape game data for a specific ID"""
    logger.info(f"Scraping game {game_id}...")
    url = f"https://play.pakakumi.com/games/{game_id}"
    for attempt in range(RETRY_LIMIT):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            game_data = {'id': game_id, 'multiplier': 0.0, 'date': 'Unknown'}
            
            # Extract round information - more robust method
            round_info = soup.find('div', string=lambda t: t and 'Round Information' in t)
            if not round_info:
                # Alternative method using class names
                round_info = soup.select_one('div.css-1dbjc4n.r-13awgt0')
            
            if round_info:
                container = round_info.parent
                if not container:
                    container = round_info.find_parent('div', recursive=False)
                    
                if container:
                    # Find all direct child divs
                    rows = container.find_all('div', recursive=False)
                    if len(rows) > 1:
                        rows = rows[1].find_all('div', recursive=False)
                    
                    for row in rows:
                        key_div = row.find('div', recursive=False)
                        value_div = key_div.find_next_sibling('div') if key_div else None
                        
                        if key_div and value_div:
                            key = key_div.get_text(strip=True)
                            value = value_div.get_text(strip=True)
                            
                            if 'Busted At' in key:
                                try:
                                    game_data['multiplier'] = float(value.replace('x', ''))
                                except ValueError:
                                    pass
                            elif 'Date' in key:
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
            
        # If no existing games, start from a known recent game
        if not existing_ids:
            logger.warning("No existing games found - starting from recent game")
            start_id = max(1, latest_id - 100)
        else:
            start_id = max(existing_ids) + 1
        
        # Safety check
        if start_id > latest_id:
            logger.info("No new games to fetch")
            return 0
            
        logger.info(f"Fetching games from {start_id} to {latest_id} ({latest_id - start_id + 1} games)")
        
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
            
            # Save progress every 5 games
            if len(new_games) % 5 == 0 and new_games:
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
