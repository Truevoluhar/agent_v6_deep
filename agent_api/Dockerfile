FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY agent_api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY agent_api /app/agent_api
COPY config /app/config
COPY skills /app/skills
COPY workspace_seed /seed
COPY agent_api/entrypoint.sh /app/agent_api/entrypoint.sh

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /workspace \
    && chown -R appuser:appuser /app /seed \
    && chmod +x /app/agent_api/entrypoint.sh

EXPOSE 8081

CMD ["/app/agent_api/entrypoint.sh"]
