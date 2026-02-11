import os
import requests
from colorama import Fore, Style
import json
import config
import database as db
import iso
import shutil
import psutil
import subprocess
import sys
import re
import ctypes # <--- Added for Windows Drive Label support

# Load settings.json as an obj
CONFIG = None
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')

with open(SETTINGS_PATH) as f:
    CONFIG = config.Config(json.load(f))

# Directory Methods
def VerifyDir(path) -> tuple[bool, str]:
    realPath = os.path.realpath(path)
    # Check if the path exists
    if (not os.path.isdir(realPath)):
        return (False, "Directory does not exist.")
    
    # Check if the device is formatted as exFat
    device = get_storage_device(path)
    if device is None:
        return (False, "Storage device not detected.")
    
    # Note: Some Linux distros report exfat as 'fuseblk', so we permit that too.
    fs_type = device.get("file_system", "").lower()
    if 'exfat' not in fs_type and 'fuseblk' not in fs_type:
         # Warning only, as detection can sometimes be flaky
         print(f"[Warning] Filesystem detected as {fs_type}, expected exFat.")
    
    # Verify the path is set up for game storage
    for idx, folder in enumerate(CONFIG.FILE_STRUCTURE):
        if (not os.path.isdir(os.path.join(path, folder))):
            CreateStructure(path)
    
    return (True, "Directory Verified.")

def CreateStructure(path):
    for idx, folder in enumerate(CONFIG.FILE_STRUCTURE):
        dest = os.path.join(path, folder)
        os.makedirs(dest, exist_ok=True)

# Database Methods
def CheckDatabases():
    global db
    
    libExists = Fore.GREEN + 'Exists' + Style.RESET_ALL
    mapExists = Fore.GREEN + 'Exists' + Style.RESET_ALL
    
    # 1. Check Library DB (Dynamic Path)
    current_db_path = db.get_db_path()
    if not current_db_path or not os.path.exists(current_db_path):
        db.initialize_library()
        libExists = Fore.YELLOW + 'Initialized' + Style.RESET_ALL
        
    # 2. Check Map DB (Static Path)
    if not os.path.exists(db.MAP_DB_LOCAL_PATH):
        db.initialize_map()
        mapExists = Fore.YELLOW + 'Initialized' + Style.RESET_ALL
        
    print("-" * 30)
    print("| Database Verification System")
    print(f"|- Library Path: {current_db_path or 'Not Set'}")
    for name, status in [('Library db', libExists), ('Mapping db', mapExists)]:
        print(f"|- {name}: {status}")
    print("-" * 30)

def ProcessUpload(temp_path: str):
    global db
    
    # 1. Validation
    if not os.path.exists(temp_path):
        return {"status": "error", "message": "Upload failed: Temp file not found."}

    serial = iso.get_serial(temp_path)
    if serial is None:
        if os.path.exists(temp_path): os.remove(temp_path)
        return {"status": "error", "message": "Game Lacks Valid Serial Number"}

    # 2. Get Metadata
    game_title = db.query_title_by_serial(serial) or "Unknown Game"
    # Clean invalid chars for Windows/exFAT (including dots to prevent extension issues)
    clean_title = re.sub(r'[<>:"/\\|?*]', '', game_title).strip()
    
    # Standard OPL naming format: SERIAL.Title.iso
    file_name = f'{serial}.{clean_title}.iso'
    
    # 3. Determine Destination
    file_size = os.path.getsize(temp_path)
    # 700MB cutoff for CD vs DVD
    if file_size > 734003200:
        sub_folder = "DVD"
    else:
        sub_folder = "CD"
    
    # Construct full destination path
    dest_dir = os.path.join(CONFIG.LIB_PATH, sub_folder)
    dest_path = os.path.join(dest_dir, file_name)

    print(f"[Task] Transferring {clean_title} to {dest_path}...")

    try:
        # 4. Ensure Destination Directory Exists
        os.makedirs(dest_dir, exist_ok=True)

        # 5. Check for duplicates / collisions
        if os.path.exists(dest_path):
            print(f"[Warning] File already exists at {dest_path}. Overwriting.")

        # 6. MANUAL COPY (Replaces shutil.move to handle cross-device moves safer)
        shutil.copy2(temp_path, dest_path)

        # 7. Verify Integrity
        if os.path.getsize(dest_path) != file_size:
            raise IOError("Copy validation failed: Destination size mismatch.")

        # 8. Delete Source
        os.remove(temp_path)
        print(f"[Task] Transfer complete. Source deleted.")

        # 9. Update Database
        # IMPORTANT: We store the FULL path now. 
        # This makes deletion much easier later.
        cleanSerial = db.clean_serial(serial)
        cover_url = f"{CONFIG.COVERS_URL}/{cleanSerial}.jpg"
        
        db.add_game_to_library(serial, clean_title, dest_path, file_size, cover_url)
        
        # 10. Trigger Cover Download
        download_cover(serial)

        return {
            "status": "completed", 
            "message": f"{clean_title} Added To Library", 
            "title": clean_title, 
            "cover_url": cover_url
        }

    except Exception as e:
        print(f"[Error] Transfer failed: {e}")
        # Clean up the potentially half-copied file
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except: pass
            
        # Clean up temp file if it still exists
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except: pass
            
        return {"status": "error", "message": f"Failed to transfer to USB: {str(e)}"}

def download_cover(serial):
    try:
        clean_serial = db.clean_serial(serial)
        filename = f"{clean_serial}_COV.jpg"
        
        # Ensure ART folder exists
        art_dir = os.path.join(CONFIG.LIB_PATH, 'ART')
        os.makedirs(art_dir, exist_ok=True)
        
        save_path = os.path.join(art_dir, filename)

        print(f"[Cover] Downloading for {serial}...")
        response = requests.get(f"{CONFIG.COVERS_URL}/{clean_serial}.jpg", stream=True)
        response.raise_for_status()
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[Cover] Saved to {save_path}")
        return save_path
    except Exception as e:
        print(f"[Cover] Failed to download cover: {e}")
        return None

def get_library():
    global db
    return db.get_all_games()

def remove_from_library(serial):
    global db
    
    # 1. Fetch game details
    game_data = db.query_library_by_serial(serial)
    
    if not game_data:
        print(f"[System] Cannot remove {serial}: Game not found in database.")
        return False

    try:
        # --- DELETE ISO FILE ---
        # Since we stored the full path in ProcessUpload, we can just use it directly.
        iso_path = game_data.get('filepath')
        
        if iso_path and os.path.exists(iso_path):
            try:
                os.remove(iso_path)
                print(f"[System] Deleted ISO: {iso_path}")
            except OSError as e:
                print(f"[System] Error deleting ISO file: {e}")
        else:
            print(f"[System] ISO file not found at {iso_path}, skipping file deletion.")

        # --- DELETE COVER ART ---
        clean_serial = db.clean_serial(serial)
        cover_path = os.path.join(CONFIG.LIB_PATH, "ART", f"{clean_serial}_COV.jpg")
        
        if os.path.exists(cover_path):
            try:
                os.remove(cover_path)
                print(f"[System] Deleted Cover: {cover_path}")
            except OSError as e:
                print(f"[System] Error deleting cover art: {e}")

        # --- REMOVE FROM DB ---
        db.remove_game_from_library(serial)
        return True

    except Exception as e:
        print(f"[System] Critical error during removal process: {e}")
        return False

def get_storage_device(path):
    realPath = os.path.realpath(path)
    if not os.path.exists(realPath):
        return None

    partitions = psutil.disk_partitions(all=True)

    best_match = ""
    selected_part = None

    for part in partitions:
        try:
            # Handle Windows vs Unix path matching
            if os.name == 'nt':
                match = realPath.lower().startswith(part.mountpoint.lower())
            else:
                match = realPath.startswith(part.mountpoint)

            if match:
                # Find the longest matching path (most specific partition)
                if len(part.mountpoint) > len(best_match):
                    best_match = part.mountpoint
                    selected_part = part
        except Exception:
            continue

    if selected_part:
        try:
            usage = psutil.disk_usage(selected_part.mountpoint)
            label = get_drive_label(selected_part.device, selected_part.mountpoint)
            
            return {
                "label": label, 
                "file_system": selected_part.fstype, 
                "space_free": usage.free,
                "total_space": usage.total,
                "path": path
            }
        except Exception as e:
            print(f"Error reading disk usage: {e}")
            return None
            
    return None

def get_drive_label(device_path, mount_point):
    """
    Cross-platform helper to get the volume label.
    """
    try:
        # --- Windows ---
        if os.name == 'nt':
            kernel32 = ctypes.windll.kernel32
            volume_name_buf = ctypes.create_unicode_buffer(1024)
            # Windows requires a trailing backslash for the root path
            root_path = mount_point if mount_point.endswith('\\') else mount_point + '\\'
            
            kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root_path),
                volume_name_buf,
                ctypes.sizeof(volume_name_buf),
                None, None, None, None, 0
            )
            return volume_name_buf.value
        
        # --- macOS ---
        elif sys.platform == 'darwin':
            cmd = ["diskutil", "info", mount_point]
            output = subprocess.check_output(cmd).decode()
            match = re.search(r"Volume Name:\s+(.*)", output)
            if match:
                label = match.group(1).strip()
                return label if label != "Not applicable" else "Untitled"
            return "Unknown"

        # --- Linux ---
        else:
            cmd = ["lsblk", "-no", "LABEL", device_path]
            label = subprocess.check_output(cmd).decode().strip()
            return label if label else "Unnamed Drive"
            
    except Exception as e:
        print(f"Error getting label: {e}")
        return "Unknown"
    
def set_library_path(new_path):
    global CONFIG
    
    # 1. Resolve and Verify the path first
    real_path = os.path.realpath(new_path)
    is_valid, msg = VerifyDir(real_path)
    
    if not is_valid:
        print(f"[Settings] Invalid path provided: {msg}")
        return {"status": "error", "message": msg}

    try:
        # 2. Read existing settings
        with open(SETTINGS_PATH, 'r') as f:
            data = json.load(f)

        # 3. Update the specific key
        data['paths']['storage'] = real_path

        # 4. Write back to file
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(data, f, indent=4)

        # 5. Update the LIVE config object
        CONFIG.LIB_PATH = real_path 
        
        # 6. CRITICAL: Re-initialize the database on the new drive
        # If the drive is empty, this creates the .db file immediately.
        db.initialize_library()
        
        print(f"[Settings] Storage path updated to: {real_path}")
        return {"status": "success", "message": "Storage path updated successfully", "path": real_path}

    except Exception as e:
        print(f"[Settings] Failed to save: {e}")
        return {"status": "error", "message": str(e)}