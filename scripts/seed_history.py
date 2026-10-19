"""Seed ~6 hours of realistic dummy history so charts/alerts are populated
immediately on a fresh demo run.

Invoked by scripts/run_demo.py with the backend venv and DATABASE_URL env set.
Idempotent: devices/readings are only inserted when missing.

    .venv/bin/python scripts/seed_history.py
"""
import math
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import get_sessionmaker  # noqa: E402
from app.models import Alert, Device, SensorReading, User  # noqa: E402

RNG = random.Random(20261019)

HISTORY_HOURS = 6
INTERVAL_SECONDS = 60  # one reading per minute

DEVICES = [
    (101, "ESP32 Node A", "Greenhouse — Bay 1", {"temp": 22.0, "hum": 48.0, "mq2": 190}),
    (102, "ESP32 Node B", "Greenhouse — Bay 2", {"temp": 24.0, "hum": 55.0, "mq2": 240}),
    (103, "ESP32 Node C", "Yard — Sensor Mast", {"temp": 19.0, "hum": 61.0, "mq2": 160}),
]

SEQ_BASE = 100_000_000  # keep clear of the live simulator's seq space


def _diurnal(t: datetime) -> float:
    return math.sin((t.hour + t.minute / 60) / 24 * 2 * math.pi)


async def main() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        admin = (
            await session.execute(select(User).where(User.username == "admin@ess.local"))
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        count = HISTORY_HOURS * 3600 // INTERVAL_SECONDS

        for lora_id, name, location, base in DEVICES:
            device = (
                await session.execute(select(Device).where(Device.device_id == lora_id))
            ).scalar_one_or_none()
            if device is None:
                device = Device(device_id=lora_id, name=name, location=location)
                session.add(device)
                await session.flush()
            else:
                device.name, device.location = name, location

            (n,) = (
                await session.execute(
                    select(func.count()).select_from(SensorReading).where(SensorReading.device_id_ref == device.id)
                )
            ).one()
            if n:  # idempotent re-run: skip devices that already have data
                print(f"  device {lora_id}: history present, skipping")
                continue

            last_seq = SEQ_BASE
            rows: list[SensorReading] = []
            for i in range(count):
                t = now - timedelta(seconds=(count - i) * INTERVAL_SECONDS)
                day = _diurnal(t)

                # Device 102: slow heat-soak over the last 30 min →
                # temp_high alert territory (> 35 °C) at the tail.
                temp = base["temp"] + 5.5 * day + RNG.uniform(-0.4, 0.4)
                if lora_id == 102:
                    temp += max(0.0, (i - (count - 30))) * 0.16

                hum = base["hum"] - 9 * day + RNG.uniform(-1.5, 1.5)
                mq2 = base["mq2"] + RNG.uniform(-25, 25)

                # Device 103: an mq2 episode 2 h ago (20 min above threshold)…
                gas_alarm = False
                if lora_id == 103 and 115 <= i <= 135:
                    mq2 = RNG.uniform(1050, 1420)
                    gas_alarm = True
                # …and a water episode ~90 min ago (15 min wet).
                water_detected = lora_id == 103 and 268 <= i <= 283
                water_raw = RNG.uniform(420, 880) if water_detected else RNG.uniform(5, 60)

                rows.append(
                    SensorReading(
                        device_id_ref=device.id,
                        packet_seq=last_seq,
                        temperature_c=round(temp, 2),
                        humidity_pct=round(hum, 2),
                        mq2_raw=int(mq2),
                        water_raw=int(water_raw),
                        battery_mv=3900 + int(40 * math.sin(i / 90)) + RNG.randint(-15, 15),
                        temp_valid=True,
                        hum_valid=True,
                        mq2_valid=True,
                        water_valid=True,
                        battery_valid=True,
                        gas_alarm=gas_alarm,
                        water_detected=water_detected,
                        simulated=True,
                        rssi=round(RNG.uniform(-92, -68), 1),
                        snr=round(RNG.uniform(-2, 10), 1),
                        gateway_id="gw-demo",
                        gateway_time=t,
                    )
                )
                last_seq += 1

            device.last_seen_at = now
            device.last_seq = last_seq
            device.last_rssi = -74.0
            device.last_snr = 7.5
            device.status = "online"
            session.add_all(rows)

        await session.flush()
        await session.commit()

        # ---- representative alert lifecycle (raw rows; history insert bypasses the rule engine) ----
        alerts = []
        for lora_id, rule_key, severity, description, status, age_min, closed_min in [
            (102, "temp_high", "critical",
             "Temperature 36.2 °C exceeded **35.0 °C** for 2 consecutive readings (preliminary indication — not a certified safety alarm).",
             "open", 12, None),
            (103, "mq2_threshold", "critical",
             "MQ-2 raw counts crossed the **800** threshold for 2 consecutive readings — investigate possible smoke/gas (preliminary indication — not a certified safety alarm).",
             "closed", 118, 96),
            (103, "water_detected", "warning",
             "Water presence detected at the probe.",
             "open", 87, None),
            (101, "humidity_high", "warning",
             "Relative humidity 88.4 % exceeded **85.0 %** for 3 consecutive readings.",
             "acknowledged", 296, 284),
        ]:
            device = (
                await session.execute(select(Device).where(Device.device_id == lora_id))
            ).scalar_one()
            has = (
                await session.execute(
                    select(Alert).where(Alert.device_id_ref == device.id, Alert.rule_key == rule_key)
                )
            ).scalar_one_or_none()
            if has is None:
                created = now - timedelta(minutes=age_min)
                acked = datetime.now(UTC) - timedelta(minutes=age_min - 4) if status != "open" else None
                alerts.append(
                    Alert(
                        device_id_ref=device.id,
                        rule_key=rule_key,
                        severity=severity,
                        description=description,
                        status=status,
                        created_at=created,
                        acknowledged_at=acked,
                        acknowledged_by=admin.id if (acked and admin) else None,
                        closed_at=now - timedelta(minutes=closed_min) if closed_min else None,
                    )
                )
        session.add_all(alerts)
        await session.commit()

    print(f"History seeded: {count} readings/device × {len(DEVICES)} devices, alerts: {len(alerts)} new")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
