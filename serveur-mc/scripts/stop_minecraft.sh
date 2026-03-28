#!/bin/bash
# stop_minecraft.sh — Envoie la commande stop via RCON puis éteint l'instance EC2.
#
# Variables requises (depuis l'environnement ou ~/.env) :
#   RCON_PASS      Mot de passe RCON
#   RCON_HOST      Hôte RCON (défaut : 127.0.0.1)
#   RCON_PORT      Port RCON (défaut : 25575)
#   INSTANCE_ID    ID de l'instance EC2
#   AWS_REGION     Région AWS (défaut : eu-north-1)
#   LOGFILE        Chemin du fichier de log (défaut : /var/log/mc-check.log)

set -euo pipefail

if [ -f "$HOME/.env" ]; then
    # shellcheck source=/dev/null
    set -a; source "$HOME/.env"; set +a
fi

RCON_HOST="${RCON_HOST:-127.0.0.1}"
RCON_PORT="${RCON_PORT:-25575}"
AWS_REGION="${AWS_REGION:-eu-north-1}"
LOGFILE="${LOGFILE:-/var/log/mc-check.log}"

if [ -z "${RCON_PASS:-}" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') : ERREUR — RCON_PASS non défini" >> "$LOGFILE"
    exit 1
fi
if [ -z "${INSTANCE_ID:-}" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') : ERREUR — INSTANCE_ID non défini" >> "$LOGFILE"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') : Envoi de 'stop' via RCON..." >> "$LOGFILE"
/usr/bin/mcrcon -H "$RCON_HOST" -P "$RCON_PORT" -p "$RCON_PASS" stop || true

sleep 30

echo "$(date '+%Y-%m-%d %H:%M:%S') : Arrêt de l'instance EC2 ${INSTANCE_ID}..." >> "$LOGFILE"
aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"
