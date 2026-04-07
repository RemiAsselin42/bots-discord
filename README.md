# bots-discord

Monodépôt contenant deux bots Discord autonomes, déployés ensemble sur un même hôte via Docker et mis à jour par un script unique.

## Bots

| Bot | Description | Stack | Documentation |
| --- | ----------- | ----- | ------------- |
| [bot-gepetesque](./bot-gepetesque/) | Bot conversationnel IA (DeepSeek) avec mémoire persistante | Node.js 22, discord.js, SQLite | [README](./bot-gepetesque/README.md) |
| [bot-serveur-mc](./bot-serveur-mc/) | Gestionnaire de serveurs Minecraft EC2 multi-guild | Python 3.10, discord.py, boto3 | [README](./bot-serveur-mc/README.md) |

## Structure du dépôt

```
bots-discord/
├── bot-gepetesque/      # Bot conversationnel DeepSeek
├── bot-serveur-mc/      # Bot gestionnaire de serveurs Minecraft
├── keys/                # Clés SSH (non commitées, montées en volume Docker)
├── update.sh            # Script de mise à jour des deux bots
└── .gitignore
```

## Déploiement

Chaque bot dispose de son propre `docker-compose.yml` et `Dockerfile`. Ils sont déployés indépendamment mais gérés ensemble par `update.sh`.

### Premier démarrage

```bash
# 1. Cloner le dépôt
git clone https://github.com/RemiAsselin42/bots-discord.git
cd bots-discord

# 2. Configurer chaque bot
cp bot-gepetesque/.env.example bot-gepetesque/.env
cp bot-serveur-mc/.env.example bot-serveur-mc/.env
# Renseigner les tokens et clés dans chaque .env

# 3. Placer la clé SSH dans keys/
# (ex: keys/mc-host.pem, montée en lecture seule par bot-serveur-mc)

# 4. Créer la base de données SQLite pour bot-gepetesque
touch bot-gepetesque/bot.db

# 5. Démarrer les bots
cd bot-gepetesque && docker-compose up -d --build
cd ../bot-serveur-mc && docker-compose up -d --build
```

### Mise à jour automatique

Le script `update.sh` met à jour le code depuis Git et reconstruit les deux conteneurs :

```bash
./update.sh
```

Pour rendre le script exécutable si nécessaire :

```bash
chmod +x update.sh 
```

Ce script :
1. Fait un `git fetch` + `git reset --hard origin/main` pour une mise à jour sûre
2. Reconstruit et redémarre `bot-gepetesque` (conteneur : `gepetesque`)
3. Reconstruit et redémarre `bot-serveur-mc` (conteneur : `serveur-mc`)
4. Affiche l'état de tous les conteneurs Docker

> **Note :** Le script utilise `--remove-orphans` pour nettoyer les conteneurs obsolètes après renommage.

## Configuration des clés SSH

Le dossier `keys/` contient les clés SSH nécessaires à `bot-serveur-mc` pour se connecter aux instances EC2. Ce dossier est listé dans `.gitignore` — les clés ne doivent jamais être commitées.

```
keys/
└── mc-host.pem    # Clé PEM pour les instances EC2 Minecraft
```

La clé est montée en lecture seule dans le conteneur `serveur-mc` via :

```yaml
volumes:
  - ../keys/mc-host.pem:/keys/mc-host.pem:ro
```

## Aperçu rapide des bots

### bot-gepetesque — Bot conversationnel IA

Répond quand mentionné (`@Bot`) dans les salons autorisés. Maintient une mémoire long terme par utilisateur et un résumé automatique des conversations. Supporte la lecture de pages web via URL. Powered by DeepSeek.

Commandes clés : `/forget`, `/memory-list`, `/forget-all`, `/add-channel`, `/reset-history`

### bot-serveur-mc — Gestionnaire de serveurs Minecraft

Contrôle des instances EC2 AWS hébergeant des serveurs Minecraft. Gère le cycle de vie complet : démarrage EC2, lancement du processus Java, arrêt automatique en cas d'inactivité. Supporte les serveurs Vanilla, Fabric (avec mods d'optimisation) et Bedrock (via Geyser).

Commandes clés : `/start`, `/stop`, `/status`, `/ip`, `/createserver`, `/logs`

## Licence

MIT
