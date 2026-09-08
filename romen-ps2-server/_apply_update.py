"""
Installs a staged ISObe update and restarts the app.

Run by updater.py as a detached process, never directly:

    python _apply_update.py /path/to/plan.json

It is a separate process because ISObe cannot overwrite the files it is
running from. The sequence is:

    wait for the old server to exit
      -> back up everything about to be replaced
      -> copy the new build in
      -> merge settings.json so the user's storage path survives
      -> reinstall dependencies if requirements.txt changed
      -> start the new version

If any step after the backup fails, the backup is restored and the previous
version is started again, so a failed update leaves a working app rather than
a half-replaced one. Either way the outcome is written to last_update.json for
the newly started server to report.
"""

import json
import os
import shutil
import subprocess
import sys
import time

PARENT_EXIT_TIMEOUT = 60


def log(message):
    print(f"[APPLY] {message}", flush=True)


def pid_alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_for_parent(pid):
    log(f"Waiting for ISObe (pid {pid}) to exit...")
    deadline = time.time() + PARENT_EXIT_TIMEOUT
    while time.time() < deadline:
        if not pid_alive(pid):
            log("Old process has exited.")
            # Give the OS a moment to release file handles on Windows.
            time.sleep(1)
            return True
        time.sleep(0.5)
    raise TimeoutError(f"ISObe did not shut down within {PARENT_EXIT_TIMEOUT}s.")


def relative_files(root):
    """Every file under root, as paths relative to root."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.append(os.path.relpath(full, root))
    return found


def is_preserved(relpath, preserve):
    """True if this path belongs to the user rather than to the build."""
    first = relpath.replace('\\', '/').split('/')[0]
    return first in preserve


def back_up(install_dir, backup_dir, files, preserve):
    """Copy the current version of everything we are about to overwrite."""
    os.makedirs(backup_dir, exist_ok=True)
    saved = []
    for relpath in files:
        if is_preserved(relpath, preserve):
            continue
        source = os.path.join(install_dir, relpath)
        if not os.path.exists(source):
            continue
        target = os.path.join(backup_dir, relpath)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        saved.append(relpath)
    log(f"Backed up {len(saved)} file(s).")
    return saved


def restore(install_dir, backup_dir, saved):
    log(f"Rolling back {len(saved)} file(s)...")
    for relpath in saved:
        source = os.path.join(backup_dir, relpath)
        if not os.path.exists(source):
            continue
        target = os.path.join(install_dir, relpath)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    log("Rollback complete.")


def apply_files(install_dir, staging_dir, files, preserve):
    copied = 0
    for relpath in files:
        if is_preserved(relpath, preserve):
            continue
        source = os.path.join(staging_dir, relpath)
        target = os.path.join(install_dir, relpath)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    log(f"Copied {copied} file(s) into place.")
    return copied


def merge_settings(install_dir, staging_dir):
    """
    Keep the user's settings, but pick up any keys the new version added.
    Existing values always win: the storage path in particular must survive.
    """
    current_path = os.path.join(install_dir, 'settings.json')
    shipped_path = os.path.join(staging_dir, 'settings.json')

    if not os.path.exists(shipped_path):
        return
    if not os.path.exists(current_path):
        shutil.copy2(shipped_path, current_path)
        log("No existing settings.json; installed the shipped defaults.")
        return

    try:
        with open(current_path) as f:
            current = json.load(f)
        with open(shipped_path) as f:
            shipped = json.load(f)
    except (ValueError, OSError) as e:
        log(f"Could not merge settings.json ({e}); leaving the existing file untouched.")
        return

    def merge(user, defaults):
        result = dict(defaults)
        for key, value in user.items():
            if key in defaults and isinstance(value, dict) and isinstance(defaults[key], dict):
                result[key] = merge(value, defaults[key])
            else:
                result[key] = value
        return result

    merged = merge(current, shipped)
    with open(current_path, 'w') as f:
        json.dump(merged, f, indent=4)
    log("Merged settings.json, keeping existing values.")


def refresh_dependencies(python, install_dir, backup_dir):
    """
    The launch scripts only install dependencies when the venv is first
    created, so an update that adds one would otherwise start and immediately
    fail on an import. Reinstall only when the file actually changed.
    """
    new_path = os.path.join(install_dir, 'requirements.txt')
    old_path = os.path.join(backup_dir, 'requirements.txt')
    if not os.path.exists(new_path) or not os.path.exists(old_path):
        return True

    with open(new_path, 'rb') as f:
        new = f.read()
    with open(old_path, 'rb') as f:
        old = f.read()
    if new == old:
        log("Dependencies unchanged.")
        return True

    log("requirements.txt changed; installing dependencies...")
    try:
        subprocess.run([python, '-m', 'pip', 'install', '-r', new_path],
                       cwd=install_dir, check=True, timeout=600)
        log("Dependencies installed.")
        return True
    except Exception as e:
        log(f"Dependency install failed: {e}")
        return False


def relaunch(python, install_dir):
    """
    Start the new version detached from whatever launched the old one.

    The restarted server outlives the terminal or tmux pane run.sh was started
    in, so its output goes to isobe.log next to the app rather than to a
    console nobody is watching any more. `tail -f isobe.log` picks it back up.
    """
    log_path = os.path.join(install_dir, 'isobe.log')
    try:
        output = open(log_path, 'ab')
    except OSError as e:
        log(f"Could not open {log_path} ({e}); falling back to this log.")
        output = None

    kwargs = {"cwd": install_dir, "stdin": subprocess.DEVNULL}
    if output is not None:
        kwargs["stdout"] = output
        kwargs["stderr"] = output
    if os.name == 'nt':
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    child = subprocess.Popen([python, 'server.py'], **kwargs)
    log(f"Started ISObe as pid {child.pid}; output goes to {log_path}")
    return child.pid


def write_result(path, **fields):
    fields["finished_at"] = time.time()
    try:
        with open(path, 'w') as f:
            json.dump(fields, f, indent=2)
    except OSError as e:
        log(f"Could not write result file: {e}")


def main():
    if len(sys.argv) < 2:
        print("usage: _apply_update.py <plan.json>")
        return 2

    with open(sys.argv[1]) as f:
        plan = json.load(f)

    install_dir = plan["install_dir"]
    staging_dir = plan["staging_dir"]
    backup_dir = plan["backup_dir"]
    preserve = set(plan["preserve"])
    python = plan["python"]
    result_path = plan["result_path"]

    saved = []
    try:
        wait_for_parent(plan["parent_pid"])

        files = relative_files(staging_dir)
        saved = back_up(install_dir, backup_dir, files, preserve)
        apply_files(install_dir, staging_dir, files, preserve)
        merge_settings(install_dir, staging_dir)

        if not refresh_dependencies(python, install_dir, backup_dir):
            raise RuntimeError("Could not install the new version's dependencies.")

        log(f"Updated {plan.get('from_version')} -> {plan.get('to_version')}.")

    except Exception as e:
        log(f"Update failed: {e}")
        try:
            if saved:
                restore(install_dir, backup_dir, saved)
        except Exception as rollback_error:
            log(f"Rollback also failed: {rollback_error}")
            write_result(result_path, status="error", rolled_back=False,
                         from_version=plan.get("from_version"),
                         to_version=plan.get("to_version"),
                         message=f"Update failed and could not be rolled back: {rollback_error}. "
                                 f"A copy of the previous version is in {backup_dir}.")
            relaunch(python, install_dir)
            return 1

        write_result(result_path, status="error", rolled_back=True,
                     from_version=plan.get("from_version"),
                     to_version=plan.get("to_version"),
                     message=f"Update failed: {e}. The previous version was restored.")
        relaunch(python, install_dir)
        return 1

    # Only the bulky staged copy is removed; the backup stays behind so a bad
    # release can still be recovered by hand.
    shutil.rmtree(os.path.join(plan["work_dir"], "extract"), ignore_errors=True)
    for entry in os.listdir(plan["work_dir"]):
        if entry.endswith('.zip'):
            try:
                os.remove(os.path.join(plan["work_dir"], entry))
            except OSError:
                pass

    new_pid = relaunch(python, install_dir)
    write_result(result_path, status="success",
                 from_version=plan.get("from_version"),
                 to_version=plan.get("to_version"),
                 pid=new_pid,
                 message=f"Updated to {plan.get('to_version')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
