import os
import sys
import time
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, TimeoutError

# --- Basic Configuration (remains the same) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

SHEET_ID = os.environ.get('SHEET_ID')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
URL = "https://play.pakakumi.com/"
MAX_GAMES = 5000
REQUEST_DELAY = 1.0
# --- End of Basic Configuration ---


def authenticate_google_sheets():
    # This function is perfect, no changes needed.
    # ... (your existing authenticate_google_sheets code)
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json:
            logger.error("GOOGLE_CREDS_JSON environment variable is missing!")
            return None
        parsed_creds = json.loads(creds_json)
        creds = Credentials.from_service_account_info(parsed_creds, scopes=SCOPES)
        gc = gspread.authorize(creds)
        logger.info("Google Sheets authentication successful")
        return gc
    except Exception as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        return None


# === vvv NEW, EFFICIENT PLAYWRIGHT FUNCTIONS vvv ===

def get_latest_game_id(page: Page) -> int | None:
    """Gets latest game ID using an existing Playwright page."""
    logger.info("Navigating to homepage to find the latest game ID...")
    try:
        page.goto(URL, timeout=60000, wait_until='domcontentloaded')
        # Wait for the specific element we need. This confirms the page has loaded properly.
        page.wait_for_selector('a[href^="/games/"]', timeout=30000)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        game_links = soup.select('a[href^="/games/"]')
        
        if game_links:
            latest_id = int(game_links[0]['href'].split('/')[-1])
            logger.info(f"Successfully found latest game ID: {latest_id}")
            return latest_id
    except TimeoutError:
        logger.error("TimeoutError: The page took too long to load or the game links never appeared.")
    except Exception as e:
        logger.error(f"Could not get latest game ID: {e}", exc_info=True)
    
    return None


def scrape_game_with_playwright(page: Page, game_id: int) -> dict | None:
    """Scrapes a single game's data using an existing Playwright page."""
    logger.info(f"Scraping game {game_id}...")
    url = f"https://play.pakakumi.com/games/{game_id}"
    try:
        page.goto(url, timeout=30000, wait_until='domcontentloaded')
        # Wait for the key information to be present
        page.wait_for_selector("div:text('Round Information')", timeout=20000)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        game_data = {'id': game_id, 'multiplier': 0.0, 'date': 'Unknown'}

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
                            game_data['multiplier'] = float(value.replace('x', ''))
                        elif key == 'Date':
                            game_data['date'] = value
        
        game_data['scraped_at'] = datetime.utcnow().isoformat() + "Z"
        return game_data
    except TimeoutError:
         logger.error(f"TimeoutError: Game page for ID {game_id} took too long to load or 'Round Information' never appeared.")
    except Exception as e:
        logger.error(f"Could not scrape game {game_id}: {e}", exc_info=True)

    return None

# === ^^^ END OF NEW PLAYWRIGHT FUNCTIONS ^^^ ===


def update_sheet(gc):
    """Update Google Sheet with new games using a single browser instance."""
    try:
        logger.info("Opening Google Sheet...")
        sh = gc.open_by_key(SHEET_ID)
        games_sheet = sh.worksheet("Games")
    except Exception as e:
        logger.error(f"Could not open Google Sheet: {e}")
        return

    logger.info("Getting existing game IDs...")
    existing_ids = set()
    try:
        id_column = games_sheet.col_values(1)[1:]
        existing_ids = set(int(i) for i in id_column if i and i.isdigit())
        logger.info(f"Found {len(existing_ids)} existing games.")
    except Exception as e:
        logger.error(f"Error reading existing IDs: {e}")

    # === vvv REFACTORED TO USE ONE BROWSER INSTANCE vvv ===
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            latest_id = get_latest_game_id(page)
            if not latest_id:
                logger.error("Could not determine latest game ID. Aborting run.")
                return

            start_id = max(existing_ids) + 1 if existing_ids else max(1, latest_id - 100)
            logger.info(f"Starting scrape from game ID {start_id} to {latest_id}")

            if start_id > latest_id:
                logger.info("Sheet is already up-to-date. No new games to scrape.")
                return

            new_games_data = []
            for game_id in range(start_id, latest_id + 1):
                game_data = scrape_game_with_playwright(page, game_id)
                if game_data and game_data.get('date') != 'Unknown':
                    new_games_data.append([
                        game_data['id'],
                        game_data['multiplier'],
                        game_data['date'],
                        game_data['scraped_at']
                    ])
                time.sleep(REQUEST_DELAY) # Be respectful to the server

            if new_games_data:
                logger.info(f"Adding {len(new_games_data)} new games to sheet...")
                games_sheet.append_rows(new_games_data, value_input_option='USER_ENTERED')
                logger.info("Successfully added new games.")
            else:
                logger.info("No new valid game data was scraped.")

        finally:
            logger.info("Closing browser.")
            browser.close()
    # === ^^^ END OF REFACTORED BROWSER LOGIC ^^^ ===

    # Trimming logic can remain the same
    # ... (your existing trimming logic) ...


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
