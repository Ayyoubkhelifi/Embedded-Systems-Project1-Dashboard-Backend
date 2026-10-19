# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway_pkg ./gateway_pkg

# Software-only image (simulator mode). For a Raspberry Pi with the SX127x
# module, build on the Pi after installing build deps and add
# requirements-lora.txt (spidev/RPi.GPIO/pySX127x) — see gateway/README.md.

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=2 \
    CMD python -m gateway_pkg.main --check || exit 1

CMD ["python", "-m", "gateway_pkg.main"]
