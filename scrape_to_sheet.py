import os
import sys
import time
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException

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
REQUEST_DELAY = 2.0  # Increased delay

# Log environment variables
logger.info(f"SHEET_ID: {SHEET_ID[:5]}...{SHEET_ID[-5:] if SHEET_ID else 'None'}")
logger.info(f"GOOGLE_CREDS_JSON: {'SET' if 'GOOGLE_CREDS_JSON' in os.environ else 'MISSING'}")

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

def setup_selenium():
    """Set up Selenium with headless Chrome"""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
        
        # Disable images for faster loading
        prefs = {"profile.managed_default_content_settings.images": 2}
        chrome_options.add_experimental_option("prefs", prefs)
        
        # Install ChromeDriver automatically
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logger.info("Selenium ChromeDriver initialized successfully")
        return driver
    except Exception as e:
        logger.error(f"Failed to initialize Selenium: {str(e)}")
        return None

def get_latest_game_id(driver):
    """Get latest game ID from homepage using Selenium"""
    try:
        logger.info("Loading homepage with Selenium")
        driver.get(URL)
        
        # Wait for game links to load
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href^="/games/"]'))
            logger.info("Homepage loaded successfully")
        except TimeoutException:
            logger.warning("Game links not found after 15 seconds")
            # Try to save screenshot for debugging
            try:
                driver.save_screenshot("homepage_timeout.png")
                logger.info("Saved screenshot: homepage_timeout.png")
            except Exception as e:
                logger.error(f"Could not save screenshot: {str(e)}")
            return None
        
        # Find all game links
        game_links = driver.find_elements(By.CSS_SELECTOR, 'a[href^="/games/"]')
        if game_links:
            href = game_links[0].get_attribute('href')
            game_id = href.split('/')[-1]
            logger.info(f"Found latest game ID: {game_id}")
            return int(game_id)
        else:
            logger.warning("No game links found on homepage")
            return None
    except Exception as e:
        logger.error(f"Error getting latest game ID with Selenium: {str(e)}")
        return None
    finally:
        # Don't quit driver here - we'll reuse it
        pass

def scrape_game(driver, game_id):
    """Scrape game data for a specific ID using Selenium"""
    logger.info(f"Scraping game {game_id} with Selenium")
    url = f"https://play.pakakumi.com/games/{game_id}"
    try:
        driver.get(url)
        
        # Wait for game information to load
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, '//div[contains(text(), "Round Information")]')))
        except TimeoutException:
            logger.warning("Game information not found after 15 seconds")
            return None
        
        # Get page source and parse with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, 'html.parser')
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
        logger.error(f"Error scraping game {game_id}: {str(e)}")
        return None

def update_sheet(gc):
    """Update Google Sheet with new games"""
    driver = setup_selenium()
    if not driver:
        logger.error("Selenium setup failed, aborting")
        return 0
        
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
        latest_id = get_latest_game_id(driver)
        if not latest_id:
            logger.error("Failed to get latest game ID")
            return 0
            
        # If no existing games, start from a known recent game
        if not existing_ids:
            logger.warning("No existing games found - starting from recent games")
            start_id = max(1, latest_id - 50)  # Only get 50 most recent games initially
        else:
            start_id = max(existing_ids) + 1
        
        # Safety check
        if start_id > latest_id:
            logger.info("No new games to fetch")
            return 0
            
        total_games = latest_id - start_id + 1
        logger.info(f"Fetching {total_games} games from {start_id} to {latest_id}")
        
        # Scrape new games
        new_games = []
        for i, game_id in enumerate(range(start_id, latest_id + 1)):
            if i > 0 and i % 10 == 0:
                logger.info(f"Processed {i} of {total_games} games")
                
            game_data = scrape_game(driver, game_id)
            if game_data:
                new_games.append([
                    game_data['id'],
                    game_data['multiplier'],
                    game_data['date'],
                    game_data['scraped_at']
                ])
            time.sleep(REQUEST_DELAY)
            
            # Save progress every 5 games
            if len(new_games) >= 5:
                try:
                    games_sheet.append_rows(new_games)
                    logger.info(f"Added {len(new_games)} games to sheet")
                    new_games = []
                except Exception as e:
                    logger.error(f"Error saving batch: {str(e)}")
        
        # Append any remaining games
        if new_games:
            try:
                games_sheet.append_rows(new_games)
                logger.info(f"Added {len(new_games)} final games to sheet")
            except Exception as e:
                logger.error(f"Error saving final batch: {str(e)}")
        
        return len(new_games)
    except Exception as e:
        logger.error(f"Error updating sheet: {str(e)}")
        traceback.print_exc()
        return 0
    finally:
        driver.quit()
        logger.info("Selenium driver closed")

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
