FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    MPLCONFIGDIR=/tmp/.cache/matplotlib

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git ripgrep tesseract-ocr tesseract-ocr-slv tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY agent_api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY migrations /app/migrations
COPY scripts /app/scripts
COPY agent_api /app/agent_api
COPY config /app/config
COPY skills /app/skills
COPY workspace_seed /seed

RUN chmod +x /app/agent_api/entrypoint.sh \
    && chmod -R g=u /app /seed /tmp

EXPOSE 8081

CMD ["/app/agent_api/entrypoint.sh"]
