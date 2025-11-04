#!/bin/bash

RCON_PASS="mdpcron"
RCON_HOST="127.0.0.1"
RCON_PORT=25575
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
INSTANCE_ID=i-XXXXXXXXXXXXXXXXX

LOGFILE="/var/log/mc-check.log"

output=$(/usr/local/bin/mcrcon -H "$RCON_HOST" -P "$RCON_PORT" -p "$RCON_PASS" list)
echo "$(date '+%Y-%m-%d %H:%M:%S') : sortie brute mcrcon : $output" >> "$LOGFILE"

if echo "$output" | grep -q "There are 0 of"; then
    echo "$(date): Aucun joueur connecté, arrêt du serveur." >> "$LOGFILE"
    /usr/local/bin/mcrcon -H "$RCON_HOST" -P "$RCON_PORT" -p "$RCON_PASS" stop

    # Attendre un peu que le serveur se coupe
    sleep 30

    # Éteindre la machine proprement
    echo "$(date): Arrêt de la machine EC2..." >> "$LOGFILE" 
    aws ec2 stop-instances --instance-ids "i-XXXXXXXXXXXXXXXXX" --region eu-north-1
else
    echo "$(date): Joueurs connectés, serveur actif." >> "$LOGFILE"
fi
