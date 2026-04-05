#!/bin/bash

# Configuration (variables d'environnement requises)
DOMAIN="${DUCKDNS_DOMAIN:?Variable DUCKDNS_DOMAIN non définie}"
TOKEN="${DUCKDNS_TOKEN:?Variable DUCKDNS_TOKEN non définie}"
LOGFILE="duck.log"

# Mise à jour DuckDNS
echo "[$(date)] Mise à jour DuckDNS..." >> "$LOGFILE"
curl -s "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=" >> "$LOGFILE"
echo "" >> "$LOGFILE"
