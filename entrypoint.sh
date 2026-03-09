#!/bin/sh
# Fix ownership on mounted volume (may be root-owned on first run)
chown -R empulse:empulse /app/data 2>/dev/null || true
exec su-exec empulse "$@"
