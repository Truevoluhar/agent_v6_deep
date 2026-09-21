#!/bin/sh
set -eu

mkdir -p /data /data/agent_workspace /data/session /data/memory /data/resources /data/runs
chown -R appuser:appuser /data 2>/dev/null || true

exec uvicorn workspace_api.main:app --host 0.0.0.0 --port 8090
