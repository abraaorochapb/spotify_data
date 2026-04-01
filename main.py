import os
import csv
import time
import uuid
import json
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Spotify OAuth config
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://127.0.0.1:8000/auth/callback")

SCOPES = "user-read-recently-played user-read-playback-state user-top-read"

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
EVENT_LOG = DATA_DIR / "event_log.csv"

# Initialize CSV if not exists
if not EVENT_LOG.exists():
    with open(EVENT_LOG, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "case_id", "activity", "timestamp",
            "track_name", "artist_name", "genres",
            "duration_ms", "played_at", "context_type"
        ])


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/auth/login")
async def login():
    from urllib.parse import urlencode
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "show_dialog": "true",
    }
    return RedirectResponse(f"{SPOTIFY_AUTH_URL}?{urlencode(params)}")


@app.get("/auth/callback")
async def callback(code: str = None, error: str = None):
    """Handle Spotify OAuth callback, collect data, save to event log."""
    if error or not code:
        return HTMLResponse("<h2>Autorização cancelada. Você pode fechar esta janela.</h2>")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(CLIENT_ID, CLIENT_SECRET),
        )

    if token_resp.status_code != 200:
        return HTMLResponse("<h2>Erro ao autenticar com o Spotify. Tente novamente.</h2>")

    tokens = token_resp.json()
    access_token = tokens["access_token"]

    # Collect recently played tracks
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {access_token}"}

        recent_resp = await client.get(
            f"{SPOTIFY_API_BASE}/me/player/recently-played?limit=50",
            headers=headers,
        )

    if recent_resp.status_code != 200:
        return HTMLResponse("<h2>Erro ao coletar dados. Tente novamente.</h2>")

    recent = recent_resp.json()

    # Generate anonymous case_id for this user session
    case_id = str(uuid.uuid4())[:8]

    rows = []
    for item in recent.get("items", []):
        track = item.get("track", {})
        played_at = item.get("played_at", "")
        context = item.get("context") or {}

        rows.append([
            case_id,
            "track_played",
            played_at,
            track.get("name", ""),
            ", ".join(a["name"] for a in track.get("artists", [])),
            "",  # genres enriched separately via /artists endpoint
            track.get("duration_ms", ""),
            played_at,
            context.get("type", "unknown"),
        ])

    # Append to CSV
    with open(EVENT_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    return HTMLResponse("""
    <html>
    <head>
      <meta charset="UTF-8"/>
      <style>
        body { font-family: sans-serif; display: flex; align-items: center;
               justify-content: center; min-height: 100vh; background: #0a0a0a; color: #f0f0f0; text-align: center; }
        h2 { font-size: 1.5rem; margin-bottom: 0.5rem; }
        p  { color: #888; font-size: 14px; }
        .check { font-size: 3rem; margin-bottom: 1rem; }
      </style>
    </head>
    <body>
      <div>
        <div class="check">✓</div>
        <h2>Obrigado pela sua contribuição!</h2>
        <p>Seus dados foram coletados com sucesso.<br/>Você pode fechar esta janela.</p>
      </div>
    </body>
    </html>
    """)


@app.get("/data/preview")
async def preview_data():
    """Preview collected event log (last 20 rows) — for dev only."""
    if not EVENT_LOG.exists():
        return {"rows": []}
    rows = []
    with open(EVENT_LOG, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return {"total": len(rows), "preview": rows[-20:]}