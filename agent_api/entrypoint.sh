#!/bin/sh
set -eu
umask 000

mkdir -p /data /data/users
chmod -R a+rwX /data/users 2>/dev/null || true

exec uvicorn --no-access-log agent_api.main:app --host 0.0.0.0 --port "${AGENT_API_PORT:-8081}"
