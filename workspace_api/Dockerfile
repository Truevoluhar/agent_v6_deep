FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY workspace_api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY workspace_api /app/workspace_api
COPY agent_api /app/agent_api
COPY workspace_api/entrypoint.sh /app/workspace_api/entrypoint.sh

RUN useradd --create-home --uid 10002 appuser \
    && mkdir -p /workspace \
    && chown -R appuser:appuser /app \
    && chmod +x /app/workspace_api/entrypoint.sh

EXPOSE 8090

CMD ["/app/workspace_api/entrypoint.sh"]
