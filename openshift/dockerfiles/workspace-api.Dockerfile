FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

WORKDIR /app

COPY workspace_api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY workspace_api /app/workspace_api
COPY shared /app/shared
COPY migrations /app/migrations
COPY agent_api /app/agent_api

RUN chmod +x /app/workspace_api/entrypoint.sh \
    && chmod -R g=u /app /tmp

EXPOSE 8090

CMD ["/app/workspace_api/entrypoint.sh"]
