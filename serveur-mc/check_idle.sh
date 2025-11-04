#!/bin/bash

# Paramètres
SCREEN_NAME="minecraft"        # Nom de ta session screen ou tmux qui lance Minecraft
SERVER_DIR="/home/ec2-user/minecraft-server"
LOCK_FILE="/tmp/minecraft_idle.lock"
IDLE_LIMIT=5                  # minutes avant arrêt
CHECK_INTERVAL=1              # intervalle de cron (en minutes)

# Extraire le nombre de joueurs connectés à partir du log
PLAYERS_CONNECTED=$(grep "There are" $SERVER_DIR/logs/latest.log | tail -1 | grep -oP '(?<=There are )\d+')

if [[ -z "$PLAYERS_CONNECTED" ]]; then
  PLAYERS_CONNECTED=0
fi

if [[ "$PLAYERS_CONNECTED" == "0" ]]; then
  # Aucun joueur connecté : incrémenter compteur d'inactivité
  if [[ -f $LOCK_FILE ]]; then
    MINUTES_IDLE=$(cat $LOCK_FILE)
    MINUTES_IDLE=$((MINUTES_IDLE + CHECK_INTERVAL))
  else
    MINUTES_IDLE=$CHECK_INTERVAL
  fi

  echo $MINUTES_IDLE > $LOCK_FILE

  if (( MINUTES_IDLE >= IDLE_LIMIT )); then
    echo "$(date): Serveur inactif depuis $MINUTES_IDLE minutes, arrêt en cours..." >> $SERVER_DIR/minecraft-stop.log
    screen -S $SCREEN_NAME -p 0 -X stuff "stop$(printf \\r)"
    rm $LOCK_FILE
  fi

else
  # Joueurs connectés, reset compteur
  if [[ -f $LOCK_FILE ]]; then
    rm $LOCK_FILE
  fi
fi
