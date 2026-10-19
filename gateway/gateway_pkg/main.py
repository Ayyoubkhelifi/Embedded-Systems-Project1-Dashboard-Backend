"""ESS Gateway entrypoint.

Modes:
* default      — SX127x SPI receiver → backend forwarding.
* `--simulate` — in-process faux node fleet (dev/CI); no hardware required.
* `--check`    — config/connection self-test and exit.

Runs an async, cooperative loop; Ctrl+C / SIGTERM triggers graceful shutdown.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from datetime import UTC, datetime

import httpx

from gateway_pkg.config import GatewaySettings, get_settings
from gateway_pkg.forwarder import Pipeline, now_iso
from gateway_pkg.logging_setup import get_logger, setup_logging
from gateway_pkg.radio import build_radio
from gateway_pkg.store import GatewayStore

logger = get_logger("gateway.main")


async def run(settings: GatewaySettings, stop: asyncio.Event, snapshot_cb=None) -> int:
    store = GatewayStore(settings.buffer_db_path)
    pipeline = Pipeline(settings, store)
    radio = build_radio(settings)
    logger.info("gateway starting: %s → %s", radio.description(), settings.backend_url)

    received = stored = rejected = duplicates = 0
    last_flush = monotonic_now()
    flush_interval = max(0.5, settings.flush_interval_seconds)

    try:
        while not stop.is_set():
            # ---- receive ----
            try:
                result = await asyncio.to_thread(radio.recv, settings.poll_interval_seconds)
            except Exception:  # noqa: BLE001 — radio interruptions must not end the loop
                logger.exception("radio failure; retrying in 2s")
                await asyncio.sleep(2.0)
                continue

            if result is not None:
                frame, rssi, snr = result
                received += 1
                verdict = pipeline.process_frame(frame, rssi, snr)
                if verdict == "stored":
                    stored += 1
                elif verdict == "duplicate":
                    duplicates += 1
                elif verdict.startswith("rejected"):
                    rejected += 1

            # ---- flush buffer (periodic) ----
            if monotonic_now() - last_flush >= flush_interval:
                last_flush = monotonic_now()
                try:
                    delivered, still_buffered = await pipeline.flush_once()
                    if delivered or still_buffered:
                        logger.debug("flush delivered=%d buffered=%d", delivered, still_buffered)
                except Exception:  # noqa: BLE001 — retry next tick
                    logger.exception("flush failure")
    finally:
        if snapshot_cb is not None:
            try:
                snapshot_cb(store.diagnostic_snapshot())
            except Exception:  # noqa: BLE001
                pass
        try:
            radio.close()
        finally:
            await pipeline.aclose()
            store.close()

    logger.info(
        "gateway stopped received=%d stored=%d duplicates=%d rejected=%d",
        received,
        stored,
        duplicates,
        rejected,
    )
    return 0


def monotonic_now() -> float:
    import time

    return time.monotonic()


async def check(settings: GatewaySettings) -> int:
    """Config self-test: keys parse, backend reachable, buffer writable."""
    problems: list[str] = []
    if not settings.node_key_map:
        problems.append("NODE_KEYS empty — at least one per-device key required")
    if settings.simulate:
        for dev_id in [int(x) for x in settings.simulate_device_ids.split(",") if x.strip()]:
            if settings.node_key_map.get(dev_id) is None:
                problems.append(f"no key configured for simulated device {dev_id}")
    store = GatewayStore(settings.buffer_db_path)
    snap = store.diagnostic_snapshot()
    store.close()
    try:
        async with httpx.AsyncClient(
            base_url=settings.backend_url, timeout=5.0, verify=settings.tls_verify
        ) as client:
            resp = await client.get("/api/v1/health")
            if resp.status_code == 200 and resp.json().get("status") == "ok":
                logger.info("backend health: OK %s", resp.json())
            else:
                problems.append(f"backend health returned {resp.status_code}: {resp.text[:120]}")
    except httpx.HTTPError as exc:
        problems.append(f"backend unreachable: {type(exc).__name__}: {exc}")

    if problems:
        for p in problems:
            logger.error("CHECK FAIL: %s", p)
        return 1
    logger.info("check ok: buffer=%s", snap)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ess-gateway")
    parser.add_argument("--simulate", action="store_true", help="run without hardware")
    parser.add_argument("--check", action="store_true", help="config self-test")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--json-logs", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.log_level, json_output=args.json_logs)
    if args.simulate:
        import os

        os.environ["SIMULATE"] = "true"
    get_settings.cache_clear()
    settings = get_settings()

    if args.check:
        return asyncio.run(check(settings))

    stop = asyncio.Event()
    loop = asyncio.new_event_loop()

    def _sig(signame: str) -> None:
        logger.info("received %s — shutting down", signame)
        stop.set()

    handled = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig, sig.name)
            handled = True
        except NotImplementedError:
            pass  # Windows: KeyboardInterrupt drives shutdown
    if not handled:
        logger.debug("OS signal handlers unavailable; relying on KeyboardInterrupt")

    try:
        return loop.run_until_complete(run(settings, stop))
    except KeyboardInterrupt:
        return 0
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
