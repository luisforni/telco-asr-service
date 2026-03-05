

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.routes import router
from app.services.kafka_service import KafkaService

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("asr_service.starting")
    kafka = KafkaService(
        brokers=os.getenv("KAFKA_BROKERS", "kafka:9092"),
        topic=os.getenv("KAFKA_TOPIC_TRANSCRIPTIONS", "transcription-events"),
    )
    await kafka.start()
    app.state.kafka = kafka
    yield
    log.info("asr_service.stopping")
    await kafka.stop()

app = FastAPI(
    title="Telco ASR Service",
    description="Real-time speech transcription via WebSocket streaming",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(router, prefix="/api/v1")

@app.get("/healthz")
async def health():
    return {"status": "ok", "service": "asr-service"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        workers=int(os.getenv("WORKERS", "1")),
        log_level="info",
    )
