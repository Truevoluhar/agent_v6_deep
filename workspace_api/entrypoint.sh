#!/bin/sh
set -eu
umask 000

mkdir -p /data /data/users
chmod -R a+rwX /data/users 2>/dev/null || true

exec uvicorn --no-access-log workspace_api.main:app --host 0.0.0.0 --port 8090
