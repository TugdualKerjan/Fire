"""
Anki Heatmap Reporter
Phones home to your configured server on every sync with full review history.
"""

import threading
import urllib.request
import urllib.error
import json
import webbrowser
import hashlib

from aqt.qt import QAction
from aqt import gui_hooks, mw
from aqt.utils import tooltip


def get_username() -> str:
    raw = mw.pm.name.strip()
    return "u_" + hashlib.sha256(raw.encode()).hexdigest()[:12]

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
    return get_config().get("base_url", "https://heatshare.tugdual.fr").strip().rstrip("/")


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

def open_heatmap():
    base_url = get_base_url()
    username = get_username()
    url = f"{base_url}/u/{username}"
    webbrowser.open(url)

def test_connection():
    base_url = get_base_url()
    api_url = f"{base_url}/api/health"
    try:
        with urllib.request.urlopen(api_url, timeout=5) as r:
            tooltip(f"✅ Connected to {base_url}", period=3000)
    except Exception as e:
        tooltip(f"❌ Could not reach {base_url}: {e}", period=5000)
def try_register():
    base_url = get_base_url()
    username = get_username()
    reviews = fetch_all_reviews()
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
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            store_token(data["token"])
            mw.taskman.run_on_main(
                lambda: tooltip(f"✅ Registered as '{username}', token stored.", period=4000)
            )
    except urllib.error.HTTPError as e:
        code = e.code
        mw.taskman.run_on_main(
            lambda: tooltip(f"❌ Registration failed: HTTP {code}", period=5000)
        )
    except (urllib.error.URLError, OSError) as e:
        msg = str(e)
        mw.taskman.run_on_main(
            lambda: tooltip(f"❌ Could not reach server: {msg}", period=5000)
        )
    except (json.JSONDecodeError, KeyError) as e:
        mw.taskman.run_on_main(
            lambda: tooltip("❌ Unexpected response from server", period=5000)
        )
def add_menu_items():
    menu = mw.form.menuTools.addMenu("🔥")

    view_action = QAction("View my heatmap", mw)
    view_action.triggered.connect(open_heatmap)
    menu.addAction(view_action)

    # test_action = QAction("Test connection", mw)
    # test_action.triggered.connect(test_connection)
    # menu.addAction(test_action)

    # register_action = QAction("Register / re-register", mw)
    # register_action.triggered.connect(
    #     lambda: threading.Thread(target=try_register, daemon=True).start()
    # )
    # menu.addAction(register_action)

gui_hooks.main_window_did_init.append(add_menu_items)
gui_hooks.sync_did_finish.append(on_sync_did_finish)
gui_hooks.profile_did_open.append(on_profile_loaded)