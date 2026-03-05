

import json
from datetime import datetime

import structlog
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

log = structlog.get_logger()

class KafkaService:
    def __init__(self, brokers: str, topic: str):
        self.brokers = brokers
        self.topic = topic
        self._producer: AIOKafkaProducer | None = None

    async def start(self):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.brokers,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            acks="all",
            enable_idempotence=True,
            compression_type="gzip",
            linger_ms=5,
        )
        await self._producer.start()
        log.info("kafka.producer.started", brokers=self.brokers)

    async def stop(self):
        if self._producer:
            await self._producer.stop()
            log.info("kafka.producer.stopped")

    async def publish_transcription(self, call_id: str, payload: dict):
        if not self._producer:
            log.error("kafka.producer.not_started")
            return
        try:
            await self._producer.send(self.topic, key=call_id, value=payload)
        except KafkaError as e:
            log.error("kafka.publish.error", error=str(e), call_id=call_id)
