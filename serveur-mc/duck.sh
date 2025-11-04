#!/bin/bash

# Configuration
DOMAIN="mc-rgl"      # ← Remplace par ton sous-domaine (sans .duckdns.org)
TOKEN="7737f45d-7ed3-4b44-9af8-5d7acbee2bb4"     # ← Remplace par ton token DuckDNS
LOGFILE="duck.log"

# Mise à jour DuckDNS
echo "[$(date)] Mise à jour DuckDNS..." >> "$LOGFILE"
curl -s "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=" >> "$LOGFILE"
echo "" >> "$LOGFILE"
