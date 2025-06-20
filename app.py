import os
import requests
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from bs4 import BeautifulSoup

app = Flask(__name__)

# Configuration
MAX_GAMES = 5000  # Make this a constant
GAMES_PER_REQUEST = 100
UPDATE_INTERVAL = 300  # 5 minutes in seconds
REQUEST_DELAY = 0.1  # Delay between requests to avoid rate limiting

# Global cache for game data
game_cache = []
cache_lock = threading.Lock()
last_updated = None
is_updating = False

def parse_game_page(html_content, game_id):
    """Parse game page HTML to extract game data"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    game_data = {
        'id': game_id,
        'multiplier': 0.0,
        'date': 'Unknown',
        'players': []
    }
    
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
    
    # Extract player data
    user_header = soup.find('div', string='User')
    if user_header:
        player_table = user_header.find_parent('div', recursive=False)
        if player_table:
            player_rows = player_table.find_all('div', recursive=False)[1:]
            
            for row in player_rows:
                cols = row.find_all('div', recursive=False)
                if len(cols) >= 3:
                    username = cols[0].get_text(strip=True)
                    multiplier = cols[1].get_text(strip=True)
                    amount = cols[2].get_text(strip=True)
                    profit = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                    
                    try:
                        # Handle negative profits
                        if profit.startswith('-'):
                            profit_value = -float(profit[1:].replace(',', ''))
                        else:
                            profit_value = float(profit.replace(',', ''))
                    except (ValueError, TypeError):
                        profit_value = 0
                    
                    game_data['players'].append({
                        'username': username,
                        'multiplier': multiplier,
                        'amount': amount,
                        'profit': profit_value
                    })
    
    return game_data

def fetch_game_data(game_id):
    """Fetch game data for a specific game ID"""
    url = f"https://play.pakakumi.com/games/{game_id}"
    try:
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        if response.status_code == 200:
            return parse_game_page(response.text, game_id)
        else:
            print(f"Failed to fetch game {game_id}: Status {response.status_code}")
    except Exception as e:
        print(f"Error fetching game {game_id}: {str(e)}")
    return None

def get_latest_game_id():
    """Get the latest game ID from the homepage"""
    try:
        response = requests.get("https://play.pakakumi.com/", headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            game_links = soup.select('a[href^="/games/"]')
            if game_links:
                latest_game = game_links[0]['href'].split('/')[-1]
                return int(latest_game)
        else:
            print(f"Failed to get homepage: Status {response.status_code}")
    except Exception as e:
        print(f"Error getting latest game ID: {str(e)}")
    return None

def update_game_cache():
    """Update the game cache by fetching new games"""
    global game_cache, last_updated, is_updating
    
    with cache_lock:
        if is_updating:
            return
        is_updating = True
    
    try:
        start_time = time.time()
        print("Starting cache update...")
        
        # Get the latest game ID
        latest_id = get_latest_game_id()
        if not latest_id:
            print("Failed to get latest game ID")
            return
        
        # Determine starting ID for this update
        start_id = latest_id - GAMES_PER_REQUEST + 1
        if not game_cache:
            # If cache is empty, fetch the most recent games
            start_id = latest_id - MAX_GAMES + 1
            if start_id < 1:
                start_id = 1
        
        # Fetch new games
        new_games = []
        for game_id in range(start_id, latest_id + 1):
            # Skip if we already have this game in cache
            if any(game['id'] == game_id for game in game_cache):
                continue
                
            game_data = fetch_game_data(game_id)
            if game_data:
                new_games.append(game_data)
                
            # Add small delay to avoid rate limiting
            time.sleep(REQUEST_DELAY)
        
        # Add new games to cache
        with cache_lock:
            # Prepend new games (so newest are first)
            game_cache = new_games + game_cache
            
            # Trim cache to MAX_GAMES
            if len(game_cache) > MAX_GAMES:
                game_cache = game_cache[:MAX_GAMES]
                
            last_updated = datetime.now()
        
        print(f"Cache updated with {len(new_games)} new games in {time.time()-start_time:.2f} seconds")
        
    except Exception as e:
        print(f"Error during cache update: {str(e)}")
    finally:
        with cache_lock:
            is_updating = False

def background_updater():
    """Background thread to periodically update the cache"""
    while True:
        update_game_cache()
        time.sleep(UPDATE_INTERVAL)

# Start background updater thread
updater_thread = threading.Thread(target=background_updater, daemon=True)
updater_thread.start()

@app.route('/')
def index():
    """Render the main page"""
    with cache_lock:
        games = game_cache
        updated = last_updated.strftime("%Y-%m-%d %H:%M:%S") if last_updated else "Never"
        updating = is_updating
    
    # Pass MAX_GAMES to template to fix UndefinedError
    return render_template('index.html', 
                           games=games, 
                           last_updated=updated, 
                           is_updating=updating,
                           MAX_GAMES=MAX_GAMES)

@app.route('/game/<int:game_id>')
def game_details(game_id):
    """Get details for a specific game"""
    with cache_lock:
        # Try to find game in cache
        game = next((g for g in game_cache if g['id'] == game_id), None)
    
    if not game:
        # If not in cache, fetch it
        game = fetch_game_data(game_id)
    
    if not game:
        return jsonify({'error': 'Game not found'}), 404
    
    return render_template('game_details.html', game=game)

@app.route('/refresh')
def refresh():
    """Trigger a manual refresh"""
    if not is_updating:
        threading.Thread(target=update_game_cache).start()
        return jsonify({'status': 'refresh_started'})
    return jsonify({'status': 'already_updating'})

@app.route('/status')
def status():
    """Get current cache status"""
    with cache_lock:
        return jsonify({
            'game_count': len(game_cache),
            'last_updated': last_updated.isoformat() if last_updated else None,
            'is_updating': is_updating
        })

if __name__ == '__main__':
    # Do an initial cache update
    print("Starting initial cache update...")
    update_game_cache()
    print("Initial cache update completed")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))