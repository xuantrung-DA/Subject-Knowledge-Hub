#!/bin/sh
set -eu
case "${MAX_UPLOAD_MB:-100}" in
  ''|*[!0-9]*) echo 'MAX_UPLOAD_MB must be an integer between 1 and 1000' >&2; exit 1 ;;
esac
MAX_UPLOAD_MB=${MAX_UPLOAD_MB:-100}
if [ "$MAX_UPLOAD_MB" -lt 1 ] || [ "$MAX_UPLOAD_MB" -gt 1000 ]; then
  echo 'MAX_UPLOAD_MB must be an integer between 1 and 1000' >&2
  exit 1
fi
# Permit multipart framing; backend independently enforces the exact file limit.
MAX_REQUEST_BODY_BYTES=$((MAX_UPLOAD_MB * 1048576 + 1048576))
export MAX_REQUEST_BODY_BYTES
envsubst '${MAX_REQUEST_BODY_BYTES}' < /etc/nginx/templates/hub.conf.template > /etc/nginx/conf.d/default.conf
nginx -t
exec "$@"
