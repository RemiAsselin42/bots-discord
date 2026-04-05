#!/bin/bash
# duck.sh — Met à jour l'IP DuckDNS.
# À exécuter via cron (ex: */5 * * * *).
#
# Variables requises (depuis l'environnement ou ~/.env) :
#   DUCKDNS_DOMAIN   Sous-domaine DuckDNS (sans .duckdns.org)
#   DUCKDNS_TOKEN    Token DuckDNS
#   LOGFILE          Fichier de log (défaut : ~/duck.log)

set -euo pipefail

if [ -f "$HOME/.env" ]; then
    # shellcheck source=/dev/null
    set -a; source "$HOME/.env"; set +a
fi

LOGFILE="${LOGFILE:-$HOME/duck.log}"

if [ -z "${DUCKDNS_DOMAIN:-}" ] || [ -z "${DUCKDNS_TOKEN:-}" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') : ERREUR — DUCKDNS_DOMAIN ou DUCKDNS_TOKEN non défini" >> "$LOGFILE"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Mise à jour DuckDNS pour ${DUCKDNS_DOMAIN}..." >> "$LOGFILE"
curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" >> "$LOGFILE"
echo "" >> "$LOGFILE"
