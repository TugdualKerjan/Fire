"""
Anki Heatmap Reporter
Phones home to your configured server on every sync with full review history.
"""

import threading
import urllib.request
import urllib.error
import json

from aqt import gui_hooks, mw
from aqt.utils import tooltip

def get_config() -> dict:
    return mw.addonManager.getConfig(__name__) or {}


def get_stored_token() -> str:
    """Get the stored token from add-on storage."""
    return get_config().get("_stored_token", "").strip()


def store_token(token: str):
    """Store the token in add-on storage."""
    config = get_config()
    config["_stored_token"] = token
    mw.addonManager.writeConfig(__name__, config)


def get_base_url() -> str:
    return get_config().get("base_url", "http://fire.tugdual.fr").strip().rstrip("/")


def get_username() -> str:
    """Get username from Anki profile name."""
    import re
    username = mw.pm.name.strip().lower()
    # Convert to valid username format
    username = re.sub(r'[^a-z0-9_-]', '_', username)
    username = re.sub(r'_{2,}', '_', username)  # collapse multiple underscores
    username = username.strip('_')  # remove leading/trailing underscores
    return username[:32] if len(username) >= 2 else f"user_{username}"


def fetch_all_reviews() -> list[dict]:
    """
    Returns [{date, count}] for every day in the local revlog.
    Runs a single grouped SQL query — fast even for large collections.
    """
    rows = mw.col.db.all(
        """
        SELECT
            date(id / 1000, 'unixepoch', 'localtime') AS day,
            COUNT(*)                                   AS cnt
        FROM revlog
        GROUP BY day
        ORDER BY day
        """
    )
    return [{"date": row[0], "count": row[1]} for row in rows]


def phone_home():
    reviews = fetch_all_reviews()
    if not reviews:
        return

    base_url = get_base_url()
    token = get_stored_token()
    username = get_username()

    # Try with existing token first
    if token and try_upload_with_token(base_url, token, reviews):
        return

    # Auto-register if no token or token failed
    try_auto_register(base_url, username, reviews)


def try_upload_with_token(base_url: str, token: str, reviews: list) -> bool:
    """Try to upload with existing token. Returns True if successful."""
    api_url = f"{base_url}/api/reviews"
    payload = json.dumps({"reviews": reviews}).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except (urllib.error.URLError, OSError):
        return False


def try_auto_register(base_url: str, username: str, reviews: list):
    """Attempt auto-registration and store token if successful."""
    api_url = f"{base_url}/api/auto-register"
    payload = json.dumps({"username": username, "reviews": reviews}).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            store_token(data["token"])
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        pass


def on_sync_did_finish():
    threading.Thread(target=phone_home, daemon=True).start()


def on_profile_loaded():
    base_url = get_base_url()
    username = get_username()

    if base_url:
        tooltip(f"🔥 Heatmap Reporter active as '{username}'", period=3000)
    else:
        tooltip(
            "⚠️ Heatmap Reporter: no base_url configured.<br>"
            "Go to <b>Tools → Add-ons → Heatmap Reporter → Config</b>",
            period=6000
        )


gui_hooks.sync_did_finish.append(on_sync_did_finish)
gui_hooks.profile_did_open.append(on_profile_loaded)