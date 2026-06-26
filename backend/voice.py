"""
Voice pipeline — Groq Whisper STT.

Audio blob (webm/wav) from browser → Groq Whisper → transcribed text.
TTS is handled client-side by the browser's Web Speech API (no server cost).

The WebSocket endpoint proxies voice sessions:
  browser sends audio chunks → server transcribes → returns text to agent loop
"""

import os
import logging
import tempfile
from pathlib import Path

from groq import Groq

logger = logging.getLogger(__name__)


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    Transcribe audio bytes using Groq Whisper.
    Returns the transcribed text string.
    """
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    # Write to a temp file because Groq SDK expects a file-like object
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(filename, f.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en",
            )
        # Groq returns a string when response_format="text"
        result = str(transcription).strip()
        logger.info(f"Transcribed {len(audio_bytes)} bytes → '{result[:80]}'")
        return result
    except Exception as e:
        logger.error(f"Groq transcription error: {e}")
        raise
    finally:
        Path(tmp_path).unlink(missing_ok=True)
