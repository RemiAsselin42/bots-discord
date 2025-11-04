#!/bin/bash

RCON_PASS="mdpcron"
RCON_HOST="127.0.0.1"
RCON_PORT=25575
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
INSTANCE_ID=i-XXXXXXXXXXXXXXXXX

LOGFILE="/var/log/mc-check.log"

echo "$(date): Envoi de la commande 'stop' au serveur Minecraft via RCON..." >> "$LOGFILE"
/usr/bin/mcrcon -H "$RCON_HOST" -P "$RCON_PORT" -p "$RCON_PASS" stop

# Attendre un peu que le serveur se coupe
sleep 30

# Éteindre la machine proprement
echo "$(date): Arrêt de la machine EC2..." >> "$LOGFILE" 
aws ec2 stop-instances --instance-ids "i-XXXXXXXXXXXXXXXXX" --region eu-north-1
 