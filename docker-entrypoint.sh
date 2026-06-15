#!/usr/bin/env sh
set -eu

# Ensure the shared data directory exists and is writable by the runtime user.
# This is important for bind-mounted host volumes like ./data.
mkdir -p /app/data
chown -R app:app /app/data || true

if command -v runuser >/dev/null 2>&1; then
  exec runuser -u app -- "$@"
else
  exec su -s /bin/sh app -c "$*"
fi
