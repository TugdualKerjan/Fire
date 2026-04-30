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


def get_token() -> str:
    return get_config().get("token", "").strip()


def get_base_url() -> str:
    return get_config().get("base_url", "http://fire.tugdual.fr").strip().rstrip("/")


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
    token = get_token()
    if not token:
        return

    reviews = fetch_all_reviews()
    if not reviews:
        return

    base_url = get_base_url()
    api_url = f"{base_url}/api/reviews"

    payload = json.dumps({"reviews": reviews}).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except (urllib.error.URLError, OSError):
        pass


def on_sync_did_finish():
    threading.Thread(target=phone_home, daemon=True).start()


def on_profile_loaded():
    token = get_token()
    if token:
        tooltip("🔥 Heatmap Reporter active", period=3000)
    else:
        tooltip(
            "⚠️ Heatmap Reporter: no token configured.<br>"
            "Go to <b>Tools → Add-ons → Heatmap Reporter → Config</b>",
            period=6000
        )


gui_hooks.sync_did_finish.append(on_sync_did_finish)
gui_hooks.profile_did_open.append(on_profile_loaded)