

import asyncio
import os
import uuid
from typing import AsyncIterator

import structlog
from google.cloud import speech_v1 as speech

from app.models.transcription import (
    FinalTranscription,
    TranscriptionChunk,
    TranscriptionSession,
    TranscriptionStatus,
    WordDetail,
)

log = structlog.get_logger()

def _build_streaming_config(session: TranscriptionSession) -> speech.StreamingRecognitionConfig:

    encoding_map = {
        "MULAW": speech.RecognitionConfig.AudioEncoding.MULAW,
        "LINEAR16": speech.RecognitionConfig.AudioEncoding.LINEAR16,
        "FLAC": speech.RecognitionConfig.AudioEncoding.FLAC,
        "OPUS": speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
    }
    encoding = encoding_map.get(session.encoding, speech.RecognitionConfig.AudioEncoding.MULAW)

    diarization_config = None
    if session.enable_diarization:
        diarization_config = speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=1,
            max_speaker_count=session.max_speaker_count,
        )

    recognition_config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=session.sample_rate,
        language_code=session.language,
        model=session.model,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=True,
        enable_word_confidence=True,
        use_enhanced=True,
        diarization_config=diarization_config,
    )
    return speech.StreamingRecognitionConfig(
        config=recognition_config,
        interim_results=True,
    )

class ASRService:

    def __init__(self):
        try:
            self.client = speech.SpeechAsyncClient()
            self._available = True
        except Exception as exc:
            log.warning("asr_service.gcp_unavailable", reason=str(exc))
            self.client = None
            self._available = False

    async def stream_transcribe(
        self,
        session: TranscriptionSession,
        audio_chunks: AsyncIterator[bytes],
        on_chunk: asyncio.Queue,
    ) -> FinalTranscription:

        if not self._available:
            raise RuntimeError(
                "Google Cloud Speech client is not available. "
                "Set GOOGLE_APPLICATION_CREDENTIALS to enable ASR."
            )
        config = _build_streaming_config(session)
        all_chunks: list[TranscriptionChunk] = []
        start_time = asyncio.get_event_loop().time()

        async def request_gen():
            yield speech.StreamingRecognizeRequest(streaming_config=config)
            async for audio_data in audio_chunks:
                yield speech.StreamingRecognizeRequest(audio_content=audio_data)

        responses = await self.client.streaming_recognize(request_gen())

        async for response in responses:
            for result in response.results:
                alt = result.alternatives[0]
                words = [
                    WordDetail(
                        word=w.word,
                        start_time=w.start_time.total_seconds(),
                        end_time=w.end_time.total_seconds(),
                        confidence=w.confidence,
                    )
                    for w in alt.words
                ]
                chunk = TranscriptionChunk(
                    call_id=session.call_id,
                    chunk_id=str(uuid.uuid4()),
                    transcript=alt.transcript,
                    confidence=alt.confidence,
                    status=TranscriptionStatus.FINAL if result.is_final else TranscriptionStatus.STREAMING,
                    words=words,
                    language=session.language,
                )
                await on_chunk.put(chunk)
                if result.is_final:
                    all_chunks.append(chunk)
                    session.chunk_count += 1
                    session.total_words += len(words)

        duration = asyncio.get_event_loop().time() - start_time
        avg_conf = (
            sum(c.confidence for c in all_chunks) / len(all_chunks)
            if all_chunks else 0.0
        )
        full_transcript = " ".join(c.transcript for c in all_chunks)

        return FinalTranscription(
            call_id=session.call_id,
            session_id=session.session_id,
            full_transcript=full_transcript,
            chunks=all_chunks,
            language=session.language,
            duration_seconds=duration,
            total_words=session.total_words,
            avg_confidence=avg_conf,
        )
