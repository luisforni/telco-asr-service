

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram

from app.models.transcription import TranscriptionSession, TranscriptionChunk
from app.services.asr_service import ASRService

log = structlog.get_logger()
router = APIRouter(tags=["ASR"])

ws_connections = Counter("asr_websocket_connections_total", "WebSocket connections opened")
transcription_errors = Counter("asr_transcription_errors_total", "Transcription errors")
audio_latency = Histogram(
    "asr_audio_latency_seconds",
    "Audio chunk processing latency",
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
)

asr_service = ASRService()

@router.post("/sessions", status_code=201)
async def create_session(body: dict, request: Request):

    session = TranscriptionSession(
        session_id=str(uuid.uuid4()),
        call_id=body.get("call_id", str(uuid.uuid4())),
        language=body.get("language", "es-MX"),
        sample_rate=body.get("sample_rate", 8000),
        encoding=body.get("encoding", "MULAW"),
        enable_diarization=body.get("enable_diarization", True),
    )
    return session.model_dump()

@router.get("/sessions/{session_id}")
async def get_session(session_id: str):

    raise HTTPException(status_code=404, detail="Session not found")

@router.websocket("/stream/{call_id}")
async def asr_stream(websocket: WebSocket, call_id: str, language: str = "es-MX"):

    await websocket.accept()
    ws_connections.inc()
    session = TranscriptionSession(
        session_id=str(uuid.uuid4()),
        call_id=call_id,
        language=language,
    )
    log.info("asr.stream.start", call_id=call_id, session_id=session.session_id)

    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
    chunk_queue: asyncio.Queue[TranscriptionChunk] = asyncio.Queue(maxsize=500)

    async def receive_audio():

        try:
            while True:
                msg = await websocket.receive()
                if "bytes" in msg:
                    await audio_queue.put(msg["bytes"])
                elif msg.get("text") == "END":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await audio_queue.put(None)

    async def audio_generator():
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                return
            yield chunk

    async def send_chunks():

        while True:
            chunk = await chunk_queue.get()
            if chunk is None:
                break
            try:
                await websocket.send_json(chunk.model_dump(mode="json"))
            except Exception:
                break

    receiver = asyncio.create_task(receive_audio())
    sender = asyncio.create_task(send_chunks())

    try:
        final = await asr_service.stream_transcribe(session, audio_generator(), chunk_queue)
        await chunk_queue.put(None)
        await sender

        kafka = websocket.app.state.kafka
        await kafka.publish_transcription(call_id, {
            "event_type": "TRANSCRIPTION_COMPLETE",
            **final.model_dump(mode="json"),
        })
        log.info("asr.stream.complete", call_id=call_id, words=final.total_words)
    except Exception as e:
        transcription_errors.inc()
        log.error("asr.stream.error", call_id=call_id, error=str(e))
    finally:
        receiver.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
