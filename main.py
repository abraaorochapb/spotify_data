import os
import uuid
from urllib.parse import urlencode

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, BigInteger, text

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class EventLog(Base):
    __tablename__ = "event_log"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    case_id      = Column(String)
    activity     = Column(String)
    timestamp    = Column(String)
    track_name   = Column(String)
    artist_name  = Column(String)
    genres       = Column(String)
    duration_ms  = Column(BigInteger)
    played_at    = Column(String)
    context_type = Column(String)

CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("REDIRECT_URI", "http://127.0.0.1:8000/auth/callback")
SCOPES        = "user-read-recently-played user-read-playback-state user-top-read"

SPOTIFY_AUTH_URL  = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE  = "https://api.spotify.com/v1"

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/auth/login")
async def login():
    params = {
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "show_dialog":   "true",
    }
    return RedirectResponse(f"{SPOTIFY_AUTH_URL}?{urlencode(params)}")


@app.get("/auth/callback")
async def callback(code: str = None, error: str = None):
    if error or not code:
        return HTMLResponse("<h2>Autorização cancelada. Você pode fechar esta janela.</h2>")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(CLIENT_ID, CLIENT_SECRET),
        )

    if token_resp.status_code != 200:
        return HTMLResponse("<h2>Erro ao autenticar com o Spotify. Tente novamente.</h2>")

    access_token = token_resp.json()["access_token"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SPOTIFY_API_BASE}/me/player/recently-played?limit=50",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        return HTMLResponse("<h2>Erro ao coletar dados. Tente novamente.</h2>")

    case_id = str(uuid.uuid4())[:8]
    items   = resp.json().get("items", [])

    rows = []
    for item in items:
        track   = item.get("track", {})
        context = item.get("context") or {}
        rows.append(EventLog(
            case_id      = case_id,
            activity     = "track_played",
            timestamp    = item.get("played_at", ""),
            track_name   = track.get("name", ""),
            artist_name  = ", ".join(a["name"] for a in track.get("artists", [])),
            genres       = "",
            duration_ms  = track.get("duration_ms", 0),
            played_at    = item.get("played_at", ""),
            context_type = context.get("type", "unknown"),
        ))

    async with AsyncSessionLocal() as session:
        session.add_all(rows)
        await session.commit()

    return HTMLResponse("""
    <html>
    <head>
      <meta charset="UTF-8"/>
      <style>
        body { font-family: sans-serif; display: flex; align-items: center;
               justify-content: center; min-height: 100vh;
               background: #0a0a0a; color: #f0f0f0; text-align: center; }
        h2  { font-size: 1.5rem; margin-bottom: 0.5rem; }
        p   { color: #888; font-size: 14px; }
        .check { font-size: 3rem; margin-bottom: 1rem; }
      </style>
    </head>
    <body>
      <div>
        <div class="check">&#10003;</div>
        <h2>Obrigado pela sua contribuição!</h2>
        <p>Seus dados foram coletados com sucesso.<br/>Você pode fechar esta janela.</p>
      </div>
    </body>
    </html>
    """)


@app.get("/data/preview")
async def preview_data():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM event_log ORDER BY id DESC LIMIT 20")
        )
        rows = [dict(r._mapping) for r in result]
    return {"total": len(rows), "preview": rows}