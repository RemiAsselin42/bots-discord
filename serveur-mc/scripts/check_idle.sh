#!/bin/bash
# check_idle.sh — Surveille l'inactivité du serveur Minecraft via les logs.
# Arrête le serveur si aucun joueur depuis IDLE_LIMIT minutes.
# À exécuter via cron toutes les CHECK_INTERVAL minutes.
#
# Variables requises (depuis l'environnement ou ~/.env) :
#   SERVER_DIR      Répertoire du serveur Minecraft
#   SCREEN_NAME     Nom de la session screen/tmux (défaut : minecraft)
#   IDLE_LIMIT      Minutes d'inactivité avant arrêt (défaut : 5)
#   CHECK_INTERVAL  Intervalle du cron en minutes (défaut : 1)
#   LOCK_FILE       Fichier de comptage idle (défaut : /tmp/minecraft_idle.lock)

set -euo pipefail

if [ -f "$HOME/.env" ]; then
    # shellcheck source=/dev/null
    set -a; source "$HOME/.env"; set +a
fi

SERVER_DIR="${SERVER_DIR:-/home/ec2-user/minecraft-server}"
SCREEN_NAME="${SCREEN_NAME:-minecraft}"
IDLE_LIMIT="${IDLE_LIMIT:-5}"
CHECK_INTERVAL="${CHECK_INTERVAL:-1}"
LOCK_FILE="${LOCK_FILE:-/tmp/minecraft_idle.lock}"

PLAYERS_CONNECTED=$(grep "There are" "$SERVER_DIR/logs/latest.log" 2>/dev/null | tail -1 | grep -oP '(?<=There are )\d+' || echo "0")
PLAYERS_CONNECTED="${PLAYERS_CONNECTED:-0}"

if [ "$PLAYERS_CONNECTED" = "0" ]; then
    if [ -f "$LOCK_FILE" ]; then
        MINUTES_IDLE=$(cat "$LOCK_FILE")
        MINUTES_IDLE=$((MINUTES_IDLE + CHECK_INTERVAL))
    else
        MINUTES_IDLE=$CHECK_INTERVAL
    fi

    echo "$MINUTES_IDLE" > "$LOCK_FILE"

    if (( MINUTES_IDLE >= IDLE_LIMIT )); then
        echo "$(date): Serveur inactif depuis ${MINUTES_IDLE} minutes, arrêt en cours..." \
            >> "$SERVER_DIR/minecraft-stop.log"
        screen -S "$SCREEN_NAME" -p 0 -X stuff "stop$(printf \\r)" || true
        rm -f "$LOCK_FILE"
    fi
else
    rm -f "$LOCK_FILE"
fi
