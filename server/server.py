from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import sqlite3, os, datetime, secrets, json, re
from contextlib import contextmanager
from typing import Annotated

app = FastAPI(title="Anki Heatmap Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DB_PATH = "heatmap.db"
ANKIFIRE_BASE_URL = os.environ.get("ANKIFIRE_BASE_URL", "https://fire.tugdual.fr")

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username   TEXT PRIMARY KEY,
                token      TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                username  TEXT NOT NULL,
                date      TEXT NOT NULL,
                count     INTEGER NOT NULL,
                PRIMARY KEY (username, date),
                FOREIGN KEY (username) REFERENCES users(username)
            )
        """)

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

init_db()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

USERNAME_RE = re.compile(r'^[a-z0-9_-]{2,32}$')

def require_token(authorization: Annotated[str | None, Header()] = None) -> str:
    """Resolve Bearer token -> username, raise 401/403 otherwise."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")
    token = authorization.removeprefix("Bearer ").strip()
    with get_db() as db:
        row = db.execute(
            "SELECT username FROM users WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid token")
    return row["username"]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RegisterPayload(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 2-32 chars, lowercase letters/digits/- only")
        return v

class ReviewEntry(BaseModel):
    date: str   # YYYY-MM-DD
    count: int

class BulkReviewPayload(BaseModel):
    reviews: list[ReviewEntry]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/register", status_code=201)
def register(payload: RegisterPayload):
    """
    Self-registration. Returns a token to paste into the add-on config.
    Username must be unique. Tokens are random 32-byte hex strings.
    """
    with get_db() as db:
        existing = db.execute(
            "SELECT 1 FROM users WHERE username = ?", (payload.username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already taken")
        token = secrets.token_hex(32)
        db.execute(
            "INSERT INTO users (username, token, created_at) VALUES (?, ?, ?)",
            (payload.username, token, datetime.date.today().isoformat())
        )
    return {
        "username": payload.username,
        "token": token,
        "heatmap_url": f"{ANKIFIRE_BASE_URL}/u/{payload.username}",
        "note": "Save this token — it won't be shown again."
    }


class AutoRegisterPayload(BaseModel):
    username: str
    reviews: list[ReviewEntry]

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 2-32 chars, lowercase letters/digits/- only")
        return v


@app.post("/api/reviews")
def post_reviews(
    payload: BulkReviewPayload,
    username: str = Depends(require_token),
):
    """
    Called by the Anki add-on on every sync.
    Upserts all {date, count} pairs for the authenticated user.
    Username comes from the token — not from the payload.
    """
    with get_db() as db:
        db.executemany(
            """
            INSERT INTO reviews (username, date, count)
            VALUES (?, ?, ?)
            ON CONFLICT(username, date) DO UPDATE SET count = excluded.count
            """,
            [(username, r.date, r.count) for r in payload.reviews]
        )
    return {"ok": True, "upserted": len(payload.reviews)}


@app.post("/api/auto-register")
def auto_register(payload: AutoRegisterPayload):
    """
    Auto-registration from Anki add-on. Creates user if doesn't exist,
    uploads reviews, and returns token for future requests.
    """
    with get_db() as db:
        existing = db.execute(
            "SELECT token FROM users WHERE username = ?", (payload.username,)
        ).fetchone()

        if existing:
            token = existing["token"]
        else:
            token = secrets.token_hex(32)
            db.execute(
                "INSERT INTO users (username, token, created_at) VALUES (?, ?, ?)",
                (payload.username, token, datetime.date.today().isoformat())
            )

        if payload.reviews:
            db.executemany(
                """
                INSERT INTO reviews (username, date, count)
                VALUES (?, ?, ?)
                ON CONFLICT(username, date) DO UPDATE SET count = excluded.count
                """,
                [(payload.username, r.date, r.count) for r in payload.reviews]
            )

    return {
        "username": payload.username,
        "token": token,
        "heatmap_url": f"{ANKIFIRE_BASE_URL}/u/{payload.username}",
        "upserted": len(payload.reviews)
    }


@app.get("/u/{username}.json")
def get_reviews_json(username: str):
    """Raw review data — useful for custom embedding."""
    with get_db() as db:
        rows = db.execute(
            "SELECT date, count FROM reviews WHERE username = ? ORDER BY date",
            (username,)
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": username, "reviews": [dict(r) for r in rows]}


@app.get("/u/{username}", response_class=HTMLResponse)
def get_heatmap(username: str):
    """Interactive embeddable heatmap page."""
    with get_db() as db:
        user = db.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        rows = db.execute(
            "SELECT date, count FROM reviews WHERE username = ? ORDER BY date",
            (username,)
        ).fetchall()

    data          = {r["date"]: r["count"] for r in rows}
    total_reviews = sum(data.values())
    total_days    = len(data)
    max_count     = max(data.values()) if data else 1

    today = datetime.date.today()
    streak, d = 0, today
    while d.isoformat() in data and data[d.isoformat()] > 0:
        streak += 1
        d -= datetime.timedelta(days=1)

    return HTMLResponse(content=render_heatmap(
        username, json.dumps(data), total_reviews, total_days, max_count, streak
    ))


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def render_heatmap(username, data_json, total_reviews, total_days, max_count, streak):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{username} · Anki Heatmap</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:      #0e0f11; --surface: #16181c; --border: #2a2d35;
    --text:    #e8eaf0; --muted:   #6b7280;
    --accent:  #7c6af7; --accent2: #a78bfa;
    --c0: #1e2028; --c1: #2d2060; --c2: #4a35a0;
    --c3: #6b50d4; --c4: #7c6af7; --c5: #a78bfa;
    --cell: 13px; --gap: 3px; --radius: 3px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'DM Sans', sans-serif;
    font-size: 14px; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 2rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 2rem 2.5rem; max-width: 900px; width: 100%; box-shadow: 0 4px 40px rgba(0,0,0,0.4); }}
  .header {{ display: flex; align-items: baseline; gap: .75rem; margin-bottom: 1.75rem; }}
  .username {{ font-family: 'DM Mono', monospace; font-size: 1.1rem; color: var(--accent2); font-weight: 500; }}
  .label {{ color: var(--muted); font-size: .8rem; letter-spacing: .08em; text-transform: uppercase; }}
  .stats {{ display: flex; gap: 2.5rem; margin-bottom: 1.75rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border); flex-wrap: wrap; }}
  .stat {{ display: flex; flex-direction: column; gap: .2rem; }}
  .stat-value {{ font-family: 'DM Mono', monospace; font-size: 1.5rem; font-weight: 500; color: var(--text); line-height: 1; }}
  .stat-label {{ font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }}
  .year-nav {{ display: flex; align-items: center; gap: .75rem; margin-bottom: 1rem; }}
  .year-btn {{ background: none; border: 1px solid var(--border); color: var(--muted); border-radius: 4px;
    padding: 2px 8px; cursor: pointer; font-family: 'DM Mono', monospace; font-size: 11px;
    transition: border-color .15s, color .15s; }}
  .year-btn:hover {{ border-color: var(--accent); color: var(--accent2); }}
  .year-display {{ font-family: 'DM Mono', monospace; font-size: 12px; color: var(--text); min-width: 40px; text-align: center; }}
  .heatmap-wrap {{ overflow-x: auto; padding-bottom: .5rem; }}
  .heatmap {{ display: inline-flex; flex-direction: column; }}
  .month-labels {{ display: flex; margin-left: calc(var(--cell) + var(--gap) + 6px); margin-bottom: 4px; height: 14px; position: relative; }}
  .month-label {{ font-family: 'DM Mono', monospace; font-size: 10px; color: var(--muted); position: absolute; }}
  .grid-row {{ display: flex; align-items: center; gap: var(--gap); }}
  .day-labels {{ display: flex; flex-direction: column; gap: var(--gap); }}
  .day-label {{ font-family: 'DM Mono', monospace; font-size: 9px; color: var(--muted);
    width: calc(var(--cell) + 6px); height: var(--cell); text-align: right; padding-right: 4px;
    display: flex; align-items: center; justify-content: flex-end; flex-shrink: 0; }}
  .weeks {{ display: flex; gap: var(--gap); }}
  .week {{ display: flex; flex-direction: column; gap: var(--gap); }}
  .cell {{ width: var(--cell); height: var(--cell); border-radius: var(--radius); background: var(--c0);
    cursor: pointer; transition: transform .1s, outline .1s; flex-shrink: 0; }}
  .cell:hover {{ transform: scale(1.3); outline: 1px solid var(--accent); outline-offset: 1px; }}
  .cell.l1 {{ background: var(--c1); }} .cell.l2 {{ background: var(--c2); }}
  .cell.l3 {{ background: var(--c3); }} .cell.l4 {{ background: var(--c4); }}
  .cell.l5 {{ background: var(--c5); }}
  .cell.empty {{ background: transparent; cursor: default; }}
  .cell.empty:hover {{ transform: none; outline: none; }}
  .legend {{ display: flex; align-items: center; gap: 4px; margin-top: 1rem; justify-content: flex-end; }}
  .legend-label {{ font-family: 'DM Mono', monospace; font-size: 9px; color: var(--muted); }}
  .legend .cell {{ cursor: default; }} .legend .cell:hover {{ transform: none; outline: none; }}
  .tooltip {{ position: fixed; background: #1e2028; border: 1px solid var(--border); border-radius: 6px;
    padding: 6px 10px; font-family: 'DM Mono', monospace; font-size: 11px; color: var(--text);
    pointer-events: none; opacity: 0; transition: opacity .15s; z-index: 100; white-space: nowrap; }}
  .embed-hint {{ margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid var(--border);
    font-family: 'DM Mono', monospace; font-size: 10px; color: var(--muted); }}
  .embed-hint code {{ color: var(--accent2); user-select: all; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <span class="username">{username}</span>
    <span class="label">· anki review history</span>
  </div>
  <div class="stats">
    <div class="stat"><span class="stat-value">{total_reviews:,}</span><span class="stat-label">Total Reviews</span></div>
    <div class="stat"><span class="stat-value">{total_days}</span><span class="stat-label">Days Active</span></div>
    <div class="stat"><span class="stat-value">{streak}</span><span class="stat-label">Current Streak</span></div>
    <div class="stat"><span class="stat-value" id="s-year">—</span><span class="stat-label">This Year</span></div>
  </div>
  <div class="year-nav">
    <button class="year-btn" id="btn-prev">←</button>
    <span class="year-display" id="year-display"></span>
    <button class="year-btn" id="btn-next">→</button>
  </div>
  <div class="heatmap-wrap"><div class="heatmap">
    <div class="month-labels" id="month-labels"></div>
    <div class="grid-row">
      <div class="day-labels">
        <div class="day-label"></div><div class="day-label">Mon</div>
        <div class="day-label"></div><div class="day-label">Wed</div>
        <div class="day-label"></div><div class="day-label">Fri</div>
        <div class="day-label"></div>
      </div>
      <div class="weeks" id="weeks"></div>
    </div>
  </div></div>
  <div class="legend">
    <span class="legend-label">less&nbsp;</span>
    <div class="cell"></div><div class="cell l1"></div><div class="cell l2"></div>
    <div class="cell l3"></div><div class="cell l4"></div><div class="cell l5"></div>
    <span class="legend-label">&nbsp;more</span>
  </div>
  <div class="embed-hint">
    embed: <code>&lt;iframe src="{ANKIFIRE_BASE_URL}/u/{username}" width="860" height="280" frameborder="0"&gt;&lt;/iframe&gt;</code>
  </div>
</div>
<div class="tooltip" id="tooltip"></div>
<script>
const DATA = {data_json};
const MAX  = {max_count} || 1;
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const today = new Date(); today.setHours(0,0,0,0);
let currentYear = today.getFullYear();

function level(n) {{
  if (!n) return 0;
  const p = n / MAX;
  return p < .1 ? 1 : p < .3 ? 2 : p < .55 ? 3 : p < .8 ? 4 : 5;
}}
function iso(d) {{
  return d.getFullYear() + '-' +
    String(d.getMonth()+1).padStart(2,'0') + '-' +
    String(d.getDate()).padStart(2,'0');
}}
function render(year) {{
  document.getElementById('year-display').textContent = year;
  let yt = 0;
  for (const [k,v] of Object.entries(DATA)) if (k.startsWith(String(year))) yt += v;
  document.getElementById('s-year').textContent = yt.toLocaleString();

  const start = new Date(year, 0, 1);
  const cur   = new Date(start); cur.setDate(cur.getDate() - cur.getDay());
  const end   = new Date(year, 11, 31);
  const weeksEl  = document.getElementById('weeks');
  const monthsEl = document.getElementById('month-labels');
  weeksEl.innerHTML = monthsEl.innerHTML = '';
  let wi = 0, lastM = -1;

  while (cur <= end || cur.getDay() !== 0) {{
    const wk = document.createElement('div'); wk.className = 'week';
    for (let d = 0; d < 7; d++) {{
      const dt = new Date(cur), s = iso(dt);
      const cell = document.createElement('div'); cell.className = 'cell';
      const inYear = dt.getFullYear() === year;
      if (!inYear || dt > today) {{
        cell.classList.add('empty');
      }} else {{
        const cnt = DATA[s] || 0, lv = level(cnt);
        if (lv) cell.classList.add('l'+lv);
        cell.onmouseenter = e => tip(e, s, cnt);
        cell.onmouseleave = () => {{ tt.style.opacity = 0; }};
        cell.onmousemove  = e => moveTip(e);
      }}
      if (d === 0 && inYear && dt.getMonth() !== lastM) {{
        const lbl = document.createElement('span'); lbl.className='month-label';
        lbl.textContent = MONTHS[dt.getMonth()];
        lbl.style.left  = (wi * 16) + 'px';
        monthsEl.appendChild(lbl); lastM = dt.getMonth();
      }}
      wk.appendChild(cell); cur.setDate(cur.getDate()+1);
    }}
    weeksEl.appendChild(wk); wi++;
  }}
}}
const tt = document.getElementById('tooltip');
function tip(e, s, n) {{
  tt.textContent = s + ' · ' + (n ? n + ' review' + (n>1?'s':'') : 'No reviews');
  tt.style.opacity = 1; moveTip(e);
}}
function moveTip(e) {{
  tt.style.left = (e.clientX+14)+'px'; tt.style.top=(e.clientY-28)+'px';
}}
document.getElementById('btn-prev').onclick = () => render(--currentYear);
document.getElementById('btn-next').onclick = () => {{ if (currentYear < today.getFullYear()) render(++currentYear); }};
render(currentYear);
</script>
</body>
</html>"""