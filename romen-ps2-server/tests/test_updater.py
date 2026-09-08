"""
Tests for the self-updater.

Run from the romen-ps2-server directory:

    python tests/test_updater.py

The updater replaces ISObe's own files, so the cases that matter are the ones
where it must refuse: a tampered download, an archive that tries to write
outside the install folder, a build that isn't ISObe, or a downgrade. Every
one of these has to be caught before anything on disk is touched.
"""

import importlib.util
import json
import os
import sys
import shutil
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater
import version

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, expected {want!r}")
        FAILURES.append(label)


def refuses(label, fn):
    """Assert fn() raises, and report the reason it gave."""
    try:
        fn()
    except Exception as e:
        print(f"  ok   {label} -> {type(e).__name__}: {str(e)[:70]}")
        return
    print(f"  FAIL {label}: it was accepted")
    FAILURES.append(label)


def load_apply_module():
    """_apply_update.py is a script, but its helpers are worth testing directly."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        '_apply_update.py')
    spec = importlib.util.spec_from_file_location("_apply_update", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_build(root, version_string="9.9.9", omit=(), extra_members=None):
    """Lay out a package the way release.yml does."""
    pkg = os.path.join(root, "isobe-ps2-v" + version_string)
    os.makedirs(os.path.join(pkg, "dist"), exist_ok=True)
    files = {
        "server.py": "# server\n",
        "requirements.txt": "fastapi\n",
        "version.py": f'__version__ = "{version_string}"\nGITHUB_REPO = "abennett05/isobe"\n',
        "dist/index.html": "<html></html>",
    }
    for name, content in files.items():
        if name in omit:
            continue
        target = os.path.join(pkg, *name.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w') as f:
            f.write(content)

    archive = os.path.join(root, "build.zip")
    with zipfile.ZipFile(archive, 'w') as zf:
        for dirpath, _, filenames in os.walk(pkg):
            for name in filenames:
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.relpath(full, root))
        for arcname, content in (extra_members or {}).items():
            zf.writestr(arcname, content)
    return archive


def test_accepts_a_good_build(tmp):
    print("\na well formed newer build is accepted")
    root = os.path.join(tmp, "good")
    os.makedirs(root)
    archive = make_build(root)
    updater._verify(archive, {})
    staged = updater._stage(archive, root, {})
    check("staged root found", os.path.basename(staged), "isobe-ps2-v9.9.9")
    check("server.py staged", os.path.exists(os.path.join(staged, "server.py")), True)


def test_rejects_bad_builds(tmp):
    print("\nbuilds that are not safe to install are refused")

    root = os.path.join(tmp, "nodist")
    os.makedirs(root)
    archive = make_build(root, omit=("dist/index.html",))
    refuses("missing frontend", lambda: updater._stage(archive, root, {}))

    root = os.path.join(tmp, "noserver")
    os.makedirs(root)
    archive = make_build(root, omit=("server.py",))
    refuses("missing server.py", lambda: updater._stage(archive, root, {}))

    # A build that is older than, or the same as, what is running.
    root = os.path.join(tmp, "old")
    os.makedirs(root)
    archive = make_build(root, version_string="0.0.1")
    refuses("downgrade", lambda: updater._stage(archive, root, {}))

    root = os.path.join(tmp, "same")
    os.makedirs(root)
    archive = make_build(root, version_string=version.__version__)
    refuses("same version", lambda: updater._stage(archive, root, {}))


def test_rejects_zip_slip(tmp):
    print("\nan archive cannot write outside the staging folder")
    root = os.path.join(tmp, "slip")
    os.makedirs(root)
    archive = make_build(root, extra_members={"../../evil.txt": "pwned"})
    refuses("path traversal member", lambda: updater._stage(archive, root, {}))
    check("nothing escaped", os.path.exists(os.path.join(tmp, "evil.txt")), False)


def test_rejects_corrupt_and_tampered(tmp):
    print("\na damaged or tampered download is refused")

    root = os.path.join(tmp, "corrupt")
    os.makedirs(root)
    not_a_zip = os.path.join(root, "build.zip")
    with open(not_a_zip, 'wb') as f:
        f.write(b"this is not a zip file")
    refuses("not a zip", lambda: updater._verify(not_a_zip, {}))

    # Truncating a valid zip has to be caught by the CRC pass.
    root = os.path.join(tmp, "truncated")
    os.makedirs(root)
    archive = make_build(root)
    with open(archive, 'r+b') as f:
        f.truncate(os.path.getsize(archive) // 2)
    refuses("truncated zip", lambda: updater._verify(archive, {}))


def test_preserved_paths():
    print("\nuser owned files are never overwritten")
    apply_module = load_apply_module()
    preserve = updater.PRESERVE

    for path in ("settings.json", "uploads/game.iso", "venv/bin/python",
                 "settings.local.json", "last_update.json"):
        check(f"preserved: {path}", apply_module.is_preserved(path, preserve), True)
    for path in ("server.py", "vmc.py", "dist/index.html", "data/ps2_titlemap.db"):
        check(f"replaced:  {path}", apply_module.is_preserved(path, preserve), False)

    # Windows-style separators have to be handled too.
    check("preserved: uploads\\game.iso",
          apply_module.is_preserved("uploads\\game.iso", preserve), True)


def test_settings_merge(tmp):
    print("\nsettings survive the update, new keys are picked up")
    apply_module = load_apply_module()

    install = os.path.join(tmp, "merge_install")
    staging = os.path.join(tmp, "merge_staging")
    os.makedirs(install)
    os.makedirs(staging)

    current = {
        "paths": {"storage": "/Volumes/PS2", "uploads": "./uploads"},
        "vmc": {"auto_provision": True, "default_size_mb": 32},
    }
    shipped = {
        "paths": {"storage": "", "uploads": "./uploads", "covers_url": "https://new"},
        "vmc": {"auto_provision": False, "default_size_mb": 8},
        "added_later": {"enabled": True},
    }
    with open(os.path.join(install, "settings.json"), 'w') as f:
        json.dump(current, f)
    with open(os.path.join(staging, "settings.json"), 'w') as f:
        json.dump(shipped, f)

    apply_module.merge_settings(install, staging)
    with open(os.path.join(install, "settings.json")) as f:
        merged = json.load(f)

    check("storage path kept", merged["paths"]["storage"], "/Volumes/PS2")
    check("user's VMC size kept", merged["vmc"]["default_size_mb"], 32)
    check("user's auto-provision kept", merged["vmc"]["auto_provision"], True)
    check("new nested key added", merged["paths"]["covers_url"], "https://new")
    check("new top level key added", merged["added_later"], {"enabled": True})


def test_refuses_while_a_transfer_is_running(tmp):
    print("\nupdating is refused while a game is still copying to the drive")
    import server

    server.JOB_RESULT.clear()
    check("no jobs -> nothing in flight", server._uploads_in_flight(), [])

    server.JOB_RESULT["job-1"] = {"status": "processing"}
    server.JOB_RESULT["job-2"] = {"status": "completed", "message": "done"}
    check("only the running job counts", server._uploads_in_flight(), ["job-1"])

    result = server.install_update()
    check("install refused", result["status"], "error")
    check("reason mentions the transfer", "transferring" in result["message"], True)

    server.JOB_RESULT.clear()


def test_install_requires_an_update(tmp):
    print("\ninstalling is refused when there is nothing to install")
    # No network in tests: check_for_updates fails soft and start_install must
    # report that rather than proceeding.
    result = updater.start_install()
    check("refused without a confirmed newer release", result["status"], "error")


def main():
    tmp = tempfile.mkdtemp(prefix="isobe-updater-test-")
    print(f"Using temporary workspace at {tmp}")
    try:
        test_accepts_a_good_build(tmp)
        test_rejects_bad_builds(tmp)
        test_rejects_zip_slip(tmp)
        test_rejects_corrupt_and_tampered(tmp)
        test_preserved_paths()
        test_settings_merge(tmp)
        test_refuses_while_a_transfer_is_running(tmp)
        test_install_requires_an_update(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("All updater checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
