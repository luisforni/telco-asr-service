

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class TranscriptionStatus(str, Enum):
    STREAMING = "streaming"
    FINAL = "final"
    ERROR = "error"

class WordDetail(BaseModel):
    word: str
    start_time: float
    end_time: float
    confidence: float = Field(ge=0.0, le=1.0)

class TranscriptionChunk(BaseModel):
    call_id: str
    chunk_id: str
    transcript: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    status: TranscriptionStatus = TranscriptionStatus.STREAMING
    words: list[WordDetail] = []
    language: str = "es-MX"
    speaker_tag: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TranscriptionSession(BaseModel):
    session_id: str
    call_id: str
    language: str = "es-MX"
    sample_rate: int = 8000
    encoding: str = "MULAW"
    enable_diarization: bool = True
    max_speaker_count: int = 2
    model: str = "telephony"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    chunk_count: int = 0
    total_words: int = 0

class FinalTranscription(BaseModel):
    call_id: str
    session_id: str
    full_transcript: str
    chunks: list[TranscriptionChunk] = []
    language: str
    duration_seconds: float
    total_words: int
    avg_confidence: float
    completed_at: datetime = Field(default_factory=datetime.utcnow)
