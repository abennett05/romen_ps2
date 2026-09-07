"""GitHub Releases integration for ISObe.

Talks to the GitHub Releases API so the running app can tell the user whether a
newer build is available, and where to get it. Everything here is read-only and
fails soft: no network, a rate limit, or a malformed response never takes the
server down, it just reports that the check could not be made.
"""

import os
import re
import time

import requests

import version

# GitHub caps unauthenticated API calls at 60/hour per IP, so results are cached.
CACHE_TTL_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 8
USER_AGENT = f"ISObe-PS2/{version.__version__}"

_cache = {}


# - - - VERSION PARSING - - -

def parse_version(tag: str) -> tuple[tuple[int, ...], str]:
    """Split a tag like 'v0.3.1-beta' into ((0, 3, 1), 'beta').

    Returns ((), '') for anything unparseable so callers can bail out safely.
    """
    if not tag:
        return ((), "")

    cleaned = str(tag).strip().lstrip("vV")

    # Separate the numeric core from any pre-release suffix ('-beta', '-rc1').
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[-+](.*))?$", cleaned)
    if not match:
        return ((), "")

    numbers = tuple(int(part) for part in match.group(1).split("."))
    prerelease = (match.group(2) or "").strip().lower()
    return (numbers, prerelease)


def compare_versions(a: str, b: str) -> int:
    """Return 1 if a > b, -1 if a < b, 0 if equal or not comparable."""
    a_nums, a_pre = parse_version(a)
    b_nums, b_pre = parse_version(b)

    if not a_nums or not b_nums:
        return 0

    # Pad to the same length so 0.3 and 0.3.0 compare equal.
    length = max(len(a_nums), len(b_nums))
    a_padded = a_nums + (0,) * (length - len(a_nums))
    b_padded = b_nums + (0,) * (length - len(b_nums))

    if a_padded != b_padded:
        return 1 if a_padded > b_padded else -1

    # Same numbers: a build with no pre-release suffix is the newer one.
    if a_pre == b_pre:
        return 0
    if not a_pre:
        return 1
    if not b_pre:
        return -1
    return 1 if a_pre > b_pre else -1


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


# - - - GITHUB API - - -

def get_repo() -> str:
    """Repo to check, from settings.json if present, else the built-in default."""
    try:
        import system
        repo = getattr(system.CONFIG, "GITHUB_REPO", "")
        if repo:
            return repo
    except Exception:
        pass
    return version.GITHUB_REPO


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    # Optional: lifts the rate limit for anyone who sets a token.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ISOBE_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str, cache_key: str, force: bool = False):
    """GET JSON with a TTL cache. Raises on failure so callers can report it."""
    cached = _cache.get(cache_key)
    if cached and not force and (time.time() - cached["fetched_at"]) < CACHE_TTL_SECONDS:
        return cached["data"]

    response = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 404:
        raise LookupError("No releases published yet.")
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise ConnectionError("GitHub API rate limit reached, try again later.")
    response.raise_for_status()

    data = response.json()
    _cache[cache_key] = {"data": data, "fetched_at": time.time()}
    return data


def _pick_asset(release: dict) -> dict:
    """Pick the downloadable zip from a release, falling back to the first asset."""
    assets = release.get("assets") or []
    for asset in assets:
        if str(asset.get("name", "")).lower().endswith(".zip"):
            return asset
    return assets[0] if assets else {}


def format_release(release: dict) -> dict:
    """Trim a GitHub release payload down to what the frontend actually renders."""
    asset = _pick_asset(release)
    tag = release.get("tag_name", "")

    return {
        "version": tag,
        "name": release.get("name") or tag,
        "notes": release.get("body") or "",
        "published_at": release.get("published_at"),
        "url": release.get("html_url"),
        "prerelease": bool(release.get("prerelease")),
        "download_url": asset.get("browser_download_url"),
        "download_name": asset.get("name"),
        "download_size": asset.get("size"),
        "download_count": asset.get("download_count"),
    }


def get_latest_release(force: bool = False) -> dict:
    """The most recent release, including pre-releases.

    /releases/latest skips pre-releases, and every ISObe release so far is one,
    so the list endpoint is used and the first non-draft entry is taken.
    """
    repo = get_repo()
    releases = _get_json(
        f"https://api.github.com/repos/{repo}/releases?per_page=10",
        cache_key=f"releases:{repo}",
        force=force,
    )

    if not isinstance(releases, list):
        raise LookupError("Unexpected response from GitHub.")

    for release in releases:
        if not release.get("draft"):
            return format_release(release)

    raise LookupError("No releases published yet.")


def get_releases(limit: int = 10, force: bool = False) -> list:
    """Recent releases, newest first."""
    repo = get_repo()
    releases = _get_json(
        f"https://api.github.com/repos/{repo}/releases?per_page=30",
        cache_key=f"releases:{repo}",
        force=force,
    )

    if not isinstance(releases, list):
        return []

    published = [r for r in releases if not r.get("draft")]
    return [format_release(r) for r in published[:limit]]


def check_for_updates(force: bool = False) -> dict:
    """Compare the running version against the newest published release."""
    current = version.__version__

    try:
        latest = get_latest_release(force=force)
    except Exception as e:
        print(f"[UPDATES] Check failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "current_version": current,
            "update_available": False,
        }

    return {
        "status": "success",
        "current_version": current,
        "update_available": is_newer(latest["version"], current),
        "repo": get_repo(),
        "latest": latest,
    }
