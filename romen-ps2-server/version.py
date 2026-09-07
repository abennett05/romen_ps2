# Single source of truth for the app version.
# The release workflow rewrites __version__ from the pushed git tag when it
# packages a build, so a downloaded copy always reports the release it came from.
__version__ = "0.3.0"

# GitHub repo that releases are published to. Overridable in settings.json.
GITHUB_REPO = "abennett05/isobe"
