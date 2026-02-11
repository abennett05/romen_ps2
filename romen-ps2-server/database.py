import sqlite3
import requests
import os 
import system

# database.py

# Constants
# We ONLY keep the Map DB here because it lives in the app, not the USB drive.
MAP_DB_LOCAL_PATH = './data/ps2_titlemap.db'
MAP_FILE_URL = 'https://github.com/niemasd/GameDB-PS2/releases/latest/download/PS2.titles.json'

# --- Helper: Get Dynamic Path ---

def get_db_path():
    """
    Dynamically constructs the database path based on the current system config.
    Returns None if no library path is selected.
    """
    if not system.CONFIG.LIB_PATH:
        return None
    return os.path.join(system.CONFIG.LIB_PATH, 'romen_ps2.db')

# --- Initialization Functions ---

def initialize_library():
    db_path = get_db_path()
    
    # 1. Check if we actually have a valid path (Device connected?)
    if not db_path:
        print("[DB Init Warning] No library path selected. Skipping DB creation.")
        return

    try:
        # Ensure the directory exists before creating the file
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS library (
                serial TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filepath TEXT NOT NULL,
                size INTEGER,
                cover_url TEXT
            )
        ''')
        conn.commit()
        conn.close()
        print(f"[DB] Library initialized at: {db_path}")
    except (sqlite3.OperationalError, OSError) as e:
        print(f"[DB Init Error] Could not initialize library at {db_path}: {e}")

def initialize_map():
    try:
        response = requests.get(MAP_FILE_URL, verify=True)
        response.raise_for_status()
        data = response.json()
        print(f"Loaded {len(data)} entries from mapping database.")
        
        db_dir = os.path.dirname(MAP_DB_LOCAL_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(MAP_DB_LOCAL_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS title_map (
                serial TEXT PRIMARY KEY,
                title TEXT NOT NULL
            )
        ''')
        
        # Use executemany for faster insertion
        game_list = [(k, v) for k, v in data.items()]
        cursor.executemany('INSERT OR REPLACE INTO title_map (serial, title) VALUES (?, ?)', game_list)
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Map Init Error] Failed to initialize map: {e}")

# --- Query Functions ---

def query_title_by_serial(serial):
    cleanSerial = clean_serial(serial)
    if not os.path.exists(MAP_DB_LOCAL_PATH): return None
    try:
        conn = sqlite3.connect(MAP_DB_LOCAL_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT title FROM title_map WHERE serial = ?', (cleanSerial,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except sqlite3.OperationalError:
        return None

def query_library_by_serial(serial):
    db_path = get_db_path()
    
    if not db_path or not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM library WHERE serial = ?', (serial,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except sqlite3.OperationalError:
        return None

def get_all_games():
    db_path = get_db_path()

    if not db_path:
        print("[DB Warning] No library path set.")
        return []
        
    if not os.path.exists(db_path):
        print(f"[DB Warning] Library DB file not found at {db_path}")
        return []

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM library")
        rows = cursor.fetchall()
        
        # Convert rows to list of dicts
        return [dict(row) for row in rows]

    except sqlite3.OperationalError as e:
        print(f"[DB Error] Failed to fetch library: {e}")
        return []
    except Exception as e:
        print(f"[DB Error] Unexpected error: {e}")
        return []
    finally:
        if conn: conn.close()

# --- Add/Remove Funcs ---

def add_game_to_library(serial, title, filepath, size=None, cover_url=None):
    db_path = get_db_path()
    if not db_path:
        print("[DB Error] Cannot add game: No library path selected.")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO library (serial, title, filepath, size, cover_url)
            VALUES (?, ?, ?, ?, ?)
        ''', (serial, title, filepath, size, cover_url))

        conn.commit()
        print(f"[DB] Added {title} ({serial}) to library.")
        return True
    
    except sqlite3.Error as e:
        print(f"[DB] Error adding game: {e}")
        return False
    finally:
        if conn: conn.close()

def remove_game_from_library(serial):
    db_path = get_db_path()
    if not db_path or not os.path.exists(db_path):
        return False

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('DELETE FROM library WHERE serial = ?', (serial,))
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"[DB] Removed game ({serial}) from library.")
        else:
            print(f"[DB] Warning: Game ({serial}) not found in library.")
        return True
    
    except sqlite3.Error as e:
        print(f"[DB] Error removing game: {e}")
        return False
    finally:
        if conn: conn.close()

# --- Helper Functions ---
def clean_serial(serial):
    if not serial: return ""
    return serial.replace('_', '-').replace('.', '').upper()