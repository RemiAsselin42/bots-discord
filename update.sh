#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Pull des mises à jour Git..."
cd "$REPO_DIR"
git pull

echo ""
echo "==> Mise à jour de bot-gepetesque..."
cd "$REPO_DIR/bot-gepetesque"
docker-compose down
docker-compose up -d --build --remove-orphans

echo ""
echo "==> Mise à jour de bot-serveur-mc..."
cd "$REPO_DIR/bot-serveur-mc"
docker-compose down
docker-compose up -d --build --remove-orphans

echo ""
echo "==> Tous les bots sont à jour."
docker ps --filter "name=bot"
