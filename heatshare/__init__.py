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
from aqt.utils import tooltip, getText


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
    url = f"{base_url}/u/{username}"

    if base_url:
        tooltip(f"Your heatmap is viewable at:<br><b>{url}</b>", period=5000)
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


def update_username():
    """Prompt user for display name and update on server."""
    # Get current username
    username = get_username()
    
    # Prompt for new display name
    display_name, accepted = getText(
        f"Your hashed username is: {username}\n\nEnter a display name (1-32 chars, letters/numbers/underscore/dash only):",
        mw,
        title="Update Display Name"
    )
    
    if not accepted or not display_name:
        return
    
    display_name = display_name.strip()
    
    # Start update in background thread
    def do_update():
        base_url = get_base_url()
        token = get_stored_token()
        
        if not token:
            mw.taskman.run_on_main(
                lambda: tooltip("❌ Not registered. Please sync first.", period=4000)
            )
            return
        
        api_url = f"{base_url}/api/display-name"
        payload = json.dumps({"display_name": display_name}).encode("utf-8")
        
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="PUT",
        )
        
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                mw.taskman.run_on_main(
                    lambda: tooltip(f"✅ Display name updated to '{display_name}'", period=4000)
                )
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                error_msg = e.read().decode("utf-8")
                data = json.loads(error_msg)
                detail = data.get("detail", f"HTTP {code}")
            except:
                detail = f"HTTP {code}"
            mw.taskman.run_on_main(
                lambda: tooltip(f"❌ Update failed: {detail}", period=5000)
            )
        except (urllib.error.URLError, OSError) as e:
            msg = str(e)
            mw.taskman.run_on_main(
                lambda: tooltip(f"❌ Could not reach server: {msg}", period=5000)
            )
    
    threading.Thread(target=do_update, daemon=True).start()


def add_menu_items():
    menu = mw.form.menuTools.addMenu("heatshare")

    view_action = QAction("View my heatmap", mw)
    view_action.triggered.connect(open_heatmap)
    menu.addAction(view_action)

    update_username_action = QAction("Update my username", mw)
    update_username_action.triggered.connect(update_username)
    menu.addAction(update_username_action)
gui_hooks.main_window_did_init.append(add_menu_items)
gui_hooks.sync_did_finish.append(on_sync_did_finish)
gui_hooks.profile_did_open.append(on_profile_loaded)