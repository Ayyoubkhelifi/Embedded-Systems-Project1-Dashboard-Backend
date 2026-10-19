"""Forwarding pipeline — HTTP(S) delivery with retry, backoff, and durable buffer.

Flow:
  radio → validate → dedup → enqueue(buffer) → try forward immediately
                                     ↘ background flush loop drains buffer
Backend responds: 201 stored / 200 duplicate / 4xx rejected.
Only confirmed deliveries (any 2xx) remove the buffered row.
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime
from typing import Any

import httpx

from gateway_pkg.logging_setup import get_logger
from gateway_pkg.protocol import PacketError, decode_packet
from gateway_pkg.store import GatewayStore


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


logger = get_logger("gateway.forwarder")


class Pipeline:
    def __init__(
        self,
        settings,
        store: GatewayStore,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._client = client or httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=settings.backend_timeout_seconds,
            verify=settings.tls_verify,
        )
        self._owned_client = client is None

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    # ---- ingest path ----

    def process_frame(self, frame: bytes, rssi: float, snr: float) -> str:
        """Validate + dedup + enqueue. Returns one of: stored, duplicate, rejected:<why>."""
        try:
            packet = decode_packet(frame, lambda d: self.settings.node_key_map.get(d))
        except PacketError as exc:
            logger.warning("rejected packet: %s", exc)
            return f"rejected:{type(exc).__name__}"

        if not self.store.is_new(packet.device_id, packet.seq):
            logger.info("duplicate dropped device=%s seq=%s", packet.device_id, packet.seq)
            return "duplicate"

        payload = packet.to_ingest_payload(
            rssi=rssi, snr=snr, gateway_id=self.settings.gateway_id, gateway_time=now_iso()
        )
        self.store.enqueue(packet.device_id, packet.seq, payload)
        return "stored"

    async def flush_once(self, batch_limit: int = 200) -> tuple[int, int]:
        """Try to deliver buffered packets oldest-first.

        Returns (delivered, still_buffered). Raises nothing; per-packet
        failures are logged and retried on the next flush with backoff.
        """
        delivered = 0
        rows = self.store.peek(limit=batch_limit)
        for row in rows:
            row_id, payload_text = row[0], row[3]
            payload: dict[str, Any] = json_loads(payload_text)
            posted = await self._post_with_retry(payload, attempt=1)
            if not posted:
                self.store.mark_attempt(row_id)
                break  # stop draining on first failure (preserve order)
            self.store.remove(row_id)
            delivered += 1
        return delivered, self.store.buffered_count()

    async def _post_with_retry(self, payload: dict[str, Any], attempt: int) -> bool:
        backoff = self.settings.retry_backoff_base
        for tries in range(self.settings.retry_max):
            try:
                resp = await self._client.post(
                    "/api/v1/telemetry",
                    json=payload,
                    headers={"X-Gateway-Key": self.settings.gateway_api_key, "Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "backend unreachable (attempt %d/%d): %s",
                    tries + 1,
                    self.settings.retry_max,
                    type(exc).__name__,
                )
                resp = None
            except Exception as exc:  # noqa: BLE001 — never crash the loop
                logger.exception("unexpected forward failure: %s", exc)
                resp = None
            if resp is not None and 200 <= resp.status_code < 300:
                if resp.status_code == 200 and resp.json().get("duplicate"):
                    logger.info("backend flagged duplicate device=%s seq=%s", payload.get("device_id"), payload.get("seq"))
                return True
            if resp is not None and not (500 <= resp.status_code < 600):
                logger.error(
                    "backend rejected packet device=%s seq=%s status=%d body=%s",
                    payload.get("device_id"),
                    payload.get("seq"),
                    resp.status_code,
                    resp.text[:200],
                )
                return True  # definitive client-side rejection: not deliverable; drop
            # Retryable failure (network error or 5xx): exponential backoff + jitter
            if tries < self.settings.retry_max - 1:
                wait_for = min(backoff, self.settings.retry_backoff_max) * (0.5 + random.random())
                await asyncio.sleep(wait_for)
                backoff *= self.settings.retry_backoff_base
        logger.error("exhausted retries; leaving packet buffered")
        return False


def json_loads(text: str) -> dict[str, Any]:
    import json

    return json.loads(text)
