"""
FastAPI application — HTTP endpoints and WebSocket for the AI Customer Support Agent.

Endpoints:
  POST /api/chat                 — Send a message to the agent, get SSE stream back
  GET  /api/events/{session_id}  — SSE stream of reasoning events for admin panel
  POST /api/voice                — Upload audio blob, get transcription + run agent
  GET  /api/sessions             — List all active sessions
  DELETE /api/sessions/{id}      — Clear a session
  GET  /api/customers            — List all CRM customers (admin view)
  GET  /api/policy               — Return policy document text
  GET  /                         — Serve customer chat UI
  GET  /admin                    — Serve admin dashboard
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# Validate required env vars at startup
_REQUIRED = ["COHERE_API_KEY"]
_OPTIONAL_VOICE = "GROQ_API_KEY"
_MISSING = [k for k in _REQUIRED if not os.environ.get(k)]
if _MISSING:
    raise RuntimeError(
        f"Missing required environment variables: {', '.join(_MISSING)}\n"
        "Copy .env.example to .env and fill in your COHERE_API_KEY."
    )
_VOICE_ENABLED = bool(os.environ.get(_OPTIONAL_VOICE))

from backend.agent import get_or_create_session, get_all_sessions, clear_session, ReasoningEvent
from backend.crm_data import CUSTOMERS
from backend.policy import POLICY_TEXT
from backend.voice import transcribe_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AI Customer Support Agent starting...")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="AI Customer Support Agent",
    description="Refund processing agent powered by Cohere Command R+",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str


# ── Chat endpoint — runs agent loop, streams events to queue ──────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    session = get_or_create_session(session_id)

    async def stream_response():
        # Kick off the agent loop in a background task
        agent_task = asyncio.create_task(session.run(req.message))

        # Stream events from the queue as SSE
        final_response = ""
        while True:
            try:
                event: ReasoningEvent = await asyncio.wait_for(
                    session.event_queue.get(), timeout=30.0
                )
                data = json.dumps(event.to_dict())
                yield f"data: {data}\n\n"

                if event.type == "final":
                    final_response = event.payload.get("response", "")
                    break
                if event.type == "error" and not agent_task.done():
                    break

            except asyncio.TimeoutError:
                # Send a keepalive ping
                yield "data: {\"type\": \"ping\"}\n\n"

        # Ensure agent task completes
        try:
            full_response = await asyncio.wait_for(agent_task, timeout=5.0)
        except asyncio.TimeoutError:
            full_response = final_response

        # Send the final complete response
        yield f"data: {json.dumps({'type': 'complete', 'session_id': session_id, 'response': full_response})}\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── SSE events endpoint — admin panel listens here ───────────────────────────

@app.get("/api/events/{session_id}")
async def events(session_id: str, request: Request):
    """
    SSE endpoint for the admin panel to receive real-time reasoning events.
    The admin panel polls for new events from the session's queue.
    """
    if session_id not in _get_session_ids():
        raise HTTPException(status_code=404, detail="Session not found")

    session = get_or_create_session(session_id)

    async def event_generator():
        yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(session.event_queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event.to_dict())}\n\n"
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"heartbeat\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ── Voice endpoint — receives audio blob, transcribes, runs agent ─────────────

@app.post("/api/voice")
async def voice(
    audio: UploadFile = File(...),
    session_id: str | None = None,
):
    if not _VOICE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Voice transcription is disabled. Set GROQ_API_KEY in .env to enable it.",
        )

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file")

    if len(raw) > 25 * 1024 * 1024:  # 25 MB Groq limit
        raise HTTPException(status_code=413, detail="Audio file exceeds 25 MB limit")

    try:
        transcript = transcribe_audio(raw, filename=audio.filename or "audio.webm")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    if not transcript:
        raise HTTPException(status_code=422, detail="Could not transcribe audio — please speak clearly")

    # Run the agent loop on the transcript
    sid = session_id or str(uuid.uuid4())
    session = get_or_create_session(sid)

    async def stream_voice_response():
        agent_task = asyncio.create_task(session.run(transcript))

        # First: send the transcript so UI can display it
        yield f"data: {json.dumps({'type': 'transcript', 'text': transcript, 'session_id': sid})}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(session.event_queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event.to_dict())}\n\n"
                if event.type in ("final", "error"):
                    break
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"ping\"}\n\n"

        try:
            full_response = await asyncio.wait_for(agent_task, timeout=5.0)
        except asyncio.TimeoutError:
            full_response = ""

        yield f"data: {json.dumps({'type': 'complete', 'session_id': sid, 'response': full_response})}\n\n"

    return StreamingResponse(
        stream_voice_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Session management ────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": get_all_sessions()}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    cleared = clear_session(session_id)
    if not cleared:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": f"Session {session_id} cleared"}


@app.post("/api/sessions/new")
async def new_session():
    sid = str(uuid.uuid4())
    get_or_create_session(sid)
    return {"session_id": sid}


# ── Admin data endpoints ──────────────────────────────────────────────────────

@app.get("/api/customers")
async def list_customers():
    """Return CRM customer list for admin dashboard."""
    return {
        "customers": [
            {
                "customer_id": c["customer_id"],
                "name": c["name"],
                "email": c["email"],
                "tier": c["tier"],
                "order_count": len(c["orders"]),
                "refund_count": len(c["refund_history"]),
                "account_flags": c["account_flags"],
            }
            for c in CUSTOMERS.values()
        ]
    }


@app.get("/api/policy")
async def get_policy():
    return {"policy": POLICY_TEXT}


# ── Static file serving ───────────────────────────────────────────────────────

@app.get("/")
async def serve_chat():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin")
async def serve_admin():
    return FileResponse(FRONTEND_DIR / "admin.html")


# Mount static files last so API routes take priority
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session_ids() -> list[str]:
    from backend.agent import _sessions
    return list(_sessions.keys())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8000)),
        reload=True,
    )
