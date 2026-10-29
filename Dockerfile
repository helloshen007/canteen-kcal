# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    CANTEEN_STATE_DIR=/app/var CANTEEN_MODEL_DIR=/app/models \
    YOLO_CONFIG_DIR=/app/var/ultralytics MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/cache OMP_NUM_THREADS=2 TORCH_NUM_THREADS=2 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then \
      cp /run/secrets/build_ca /usr/local/share/ca-certificates/build-ca.crt && update-ca-certificates; \
    fi \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    git libgl1 libglib2.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home app \
    && mkdir -p /app/var /app/models && chown app:app /app/var /app/models
COPY web/requirements.txt /app/web/requirements.txt
COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN python -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install -r deploy/requirements.txt
COPY --chown=app:app . /app
USER app
EXPOSE 8000
CMD ["uvicorn", "web.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
