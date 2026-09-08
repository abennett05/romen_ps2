"""
In-place updating for ISObe.

Nothing here ever runs on its own. An install happens only when the user
presses the button in Settings, which posts to /updates/install. The update
check is separate and read-only (see updates.py); finding a new release never
starts an install.

The work is split in two because a process cannot reliably replace the files
it is running from, especially on Windows:

  1. This module downloads the release zip, verifies it, and unpacks it to a
     staging directory. Nothing in the installation is touched, so a failure
     at any point up to here leaves the running app exactly as it was.
  2. It then launches _apply_update.py as a detached process and exits. That
     helper waits for this process to die, swaps the files in, and starts the
     new version. It keeps a backup and rolls back if the swap fails.

The result of step 2 is written to last_update.json, which the freshly started
server reports through /updates/install/status so the outcome survives the
restart.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

import requests

import updates
import version

INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_PATH = os.path.join(INSTALL_DIR, 'last_update.json')
APPLY_SCRIPT = os.path.join(INSTALL_DIR, '_apply_update.py')

# Files the update must never clobber. settings.json is merged rather than
# replaced (the user's storage path lives there); the rest are left alone.
PRESERVE = {'settings.json', 'settings.local.json', 'uploads', 'venv', '.venv',
            'last_update.json'}

# The zip has to look like an ISObe build before it is allowed near the
# installation.
REQUIRED_MEMBERS = ('server.py', 'version.py', 'requirements.txt', 'dist/index.html')

DOWNLOAD_TIMEOUT_SECONDS = 30
CHUNK_SIZE = 1024 * 256

_lock = threading.Lock()
_state = {
    "status": "idle",       # idle | downloading | verifying | staging | restarting | error
    "progress": 0,
    "message": "",
    "target_version": None,
    "started_at": None,
}


# - - - STATE - - -

def _set(**kwargs):
    with _lock:
        _state.update(kwargs)


def get_state() -> dict:
    """Current install state, plus the outcome of any completed install."""
    with _lock:
        state = dict(_state)

    # An install finishes in a different process, so the result is read back
    # from disk rather than held in memory.
    state["last_result"] = read_last_result()
    state["current_version"] = version.__version__
    return state


def read_last_result():
    try:
        with open(RESULT_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def clear_last_result():
    try:
        os.remove(RESULT_PATH)
    except OSError:
        pass


def is_running() -> bool:
    with _lock:
        return _state["status"] in ("downloading", "verifying", "staging", "restarting")


# - - - ENTRY POINT - - -

def start_install(force: bool = False) -> dict:
    """
    Begin an install. Returns immediately; progress is polled from get_state().
    Callers are responsible for confirming the user asked for this.
    """
    if is_running():
        return {"status": "error", "message": "An update is already in progress."}

    try:
        check = updates.check_for_updates(force=force)
    except Exception as e:
        return {"status": "error", "message": f"Could not check for updates: {e}"}

    if check.get("status") != "success":
        return {"status": "error", "message": check.get("message", "Update check failed.")}
    if not check.get("update_available"):
        return {"status": "error", "message": "Already running the latest release."}

    release = check.get("latest") or {}
    if not release.get("download_url"):
        return {"status": "error", "message": "That release has no downloadable build attached."}

    if not os.access(INSTALL_DIR, os.W_OK):
        return {"status": "error", "message": "ISObe's folder is not writable, so it cannot update itself."}

    clear_last_result()
    _set(status="downloading", progress=0, message="Starting download...",
         target_version=release.get("version"), started_at=time.time())

    thread = threading.Thread(target=_run_install, args=(release,), daemon=True)
    thread.start()
    return {"status": "success", "message": "Update started.", "target_version": release.get("version")}


def _run_install(release: dict):
    work_dir = None
    try:
        work_dir = tempfile.mkdtemp(prefix="isobe-update-")

        archive = _download(release, work_dir)
        _verify(archive, release)
        staged = _stage(archive, work_dir, release)
        _hand_off(staged, work_dir, release)

    except Exception as e:
        print(f"[UPDATE] Failed: {e}")
        _set(status="error", progress=0, message=str(e))
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


# - - - STEP 1: DOWNLOAD - - -

def _download(release: dict, work_dir: str) -> str:
    url = release["download_url"]
    name = release.get("download_name") or "isobe-update.zip"
    expected = release.get("download_size") or 0
    dest = os.path.join(work_dir, name)

    _set(status="downloading", progress=0, message=f"Downloading {release.get('version', '')}...")

    response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS,
                            headers={"User-Agent": updates.USER_AGENT})
    response.raise_for_status()

    total = int(response.headers.get("Content-Length") or expected or 0)
    written = 0
    with open(dest, 'wb') as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            f.write(chunk)
            written += len(chunk)
            if total:
                # The download is the slow part, so it owns most of the bar.
                _set(progress=int(written * 80 / total),
                     message=f"Downloading... {written // (1024 * 1024)} MB")

    if expected and written != expected:
        raise IOError(f"Download incomplete: got {written} bytes, expected {expected}.")

    return dest


# - - - STEP 2: VERIFY - - -

def _verify(archive: str, release: dict):
    _set(status="verifying", progress=82, message="Verifying download...")

    # A published checksum is preferred, but older releases don't have one, so
    # its absence is not fatal. The zip's own CRCs are always checked.
    checksum_url = release.get("checksum_url")
    if checksum_url:
        try:
            expected = _fetch_expected_sha256(checksum_url)
        except Exception as e:
            print(f"[UPDATE] Could not read published checksum: {e}")
            expected = None

        if expected:
            actual = _sha256(archive)
            if actual.lower() != expected.lower():
                raise IOError("Checksum mismatch: the download does not match the published release.")
            print("[UPDATE] Checksum verified.")

    if not zipfile.is_zipfile(archive):
        raise IOError("The downloaded file is not a valid zip archive.")

    with zipfile.ZipFile(archive) as zf:
        broken = zf.testzip()
        if broken is not None:
            raise IOError(f"The download is corrupt (bad entry: {broken}).")


def _fetch_expected_sha256(url: str):
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS,
                            headers={"User-Agent": updates.USER_AGENT})
    response.raise_for_status()
    # Format is "<hash>  <filename>", as produced by sha256sum.
    first = response.text.strip().split()
    return first[0] if first else None


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


# - - - STEP 3: STAGE - - -

def _stage(archive: str, work_dir: str, release: dict) -> str:
    _set(status="staging", progress=88, message="Unpacking...")

    extract_dir = os.path.join(work_dir, "extract")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            _safe_extract(zf, member, extract_dir)

    root = _find_package_root(extract_dir)

    for required in REQUIRED_MEMBERS:
        if not os.path.exists(os.path.join(root, *required.split('/'))):
            raise IOError(f"The downloaded build is missing {required}; refusing to install it.")

    staged_version = _read_staged_version(root)
    if staged_version and not updates.is_newer(staged_version, version.__version__):
        raise IOError(f"The downloaded build reports version {staged_version}, "
                      f"which is not newer than {version.__version__}.")

    return root


def _safe_extract(zf: zipfile.ZipFile, member: zipfile.ZipInfo, dest: str):
    """Extract one member, refusing anything that escapes the destination."""
    name = member.filename

    # Archives zipped on macOS carry a parallel __MACOSX tree of resource forks.
    if name.startswith('__MACOSX/') or os.path.basename(name).startswith('._'):
        return

    target = os.path.realpath(os.path.join(dest, name))
    if not target.startswith(os.path.realpath(dest) + os.sep):
        raise IOError(f"Refusing to extract {name}: it points outside the staging folder.")

    if member.is_dir():
        os.makedirs(target, exist_ok=True)
        return

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with zf.open(member) as src, open(target, 'wb') as out:
        shutil.copyfileobj(src, out)


def _find_package_root(extract_dir: str) -> str:
    """Releases wrap everything in a single isobe-ps2-<tag> folder."""
    entries = [e for e in os.listdir(extract_dir) if not e.startswith('.')]
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return extract_dir


def _read_staged_version(root: str):
    try:
        import re
        with open(os.path.join(root, 'version.py')) as f:
            match = re.search(r'^__version__\s*=\s*"([^"]+)"', f.read(), re.M)
        return match.group(1) if match else None
    except Exception:
        return None


# - - - STEP 4: HAND OFF - - -

def _hand_off(staged: str, work_dir: str, release: dict):
    _set(status="restarting", progress=95, message="Installing and restarting...")

    # The helper has to live outside the installation, since the installation
    # is what it is about to overwrite.
    helper = os.path.join(work_dir, '_apply_update.py')
    shutil.copy2(APPLY_SCRIPT, helper)

    plan = {
        "parent_pid": os.getpid(),
        "install_dir": INSTALL_DIR,
        "staging_dir": staged,
        "work_dir": work_dir,
        "backup_dir": os.path.join(work_dir, "backup"),
        "python": sys.executable,
        "preserve": sorted(PRESERVE),
        "result_path": RESULT_PATH,
        "log_path": os.path.join(work_dir, "update.log"),
        "from_version": version.__version__,
        "to_version": release.get("version"),
    }
    plan_path = os.path.join(work_dir, "plan.json")
    with open(plan_path, 'w') as f:
        json.dump(plan, f, indent=2)

    log = open(plan["log_path"], 'ab')
    kwargs = {"cwd": work_dir, "stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen([sys.executable, helper, plan_path], **kwargs)
    print(f"[UPDATE] Handing off to installer for {plan['to_version']}; shutting down.")

    # Give the frontend a moment to see the "restarting" state, then get out of
    # the helper's way. The upload guard in server.py has already established
    # that no transfer is in flight.
    def _exit():
        time.sleep(1.5)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
