# Bot Discord Multi-Serveurs Minecraft

Bot Discord pour gérer plusieurs serveurs Minecraft EC2 sur AWS avec autocomplétion par serveur Discord.

## Fonctionnalités

- **Multi-serveurs** : Gérez plusieurs serveurs Minecraft par serveur Discord
- **Autocomplétion intelligente** : Chaque serveur Discord ne voit que ses propres serveurs Minecraft
- **Gestion AWS EC2** : Démarrage, arrêt, statut des instances
- **Notification de démarrage** : Le bot notifie dans le canal Discord dès que l'instance est prête
- **Auto-stop** : Arrêt automatique des serveurs inactifs (aucun joueur connecté depuis N minutes)
- **Statut des joueurs** : Interrogation directe du serveur Minecraft via `mcstatus`
- **Suivi des coûts** : Calcul automatique de l'uptime et du coût estimé
- **Multi-régions** : Supporte des serveurs dans différentes régions AWS
- **Gestion des permissions** : Contrôle fin par rôle Discord sur les commandes `/start` et `/stop`
- **Setup SSH automatique** : Création de la structure d'un serveur Minecraft sur l'instance EC2 via `/createserver`

## Commandes disponibles

### Gestion des serveurs

- `/start [serveur]` — Démarre un serveur Minecraft (notifie quand prêt)
- `/stop [serveur]` — Arrête un serveur Minecraft
- `/status [serveur]` — Vérifie le statut EC2 d'un serveur
- `/ip [serveur]` — Obtient l'adresse IP ou le domaine du serveur
- `/uptime [serveur]` — Affiche l'uptime et le coût estimé
- `/list` — Liste tous les serveurs Minecraft disponibles
- `/players [serveur]` — Affiche les joueurs connectés (ping Minecraft direct)
- `/cost [serveur]` — Affiche le coût détaillé depuis le dernier démarrage

### Administration (Administrateurs uniquement)

- `/createserver` — Crée un nouveau serveur avec attribution automatique de port et setup SSH
  - `name` : Nom affiché
  - `instance_id` : ID de l'instance EC2 (ex: `i-0123456789abcdef0`)
  - `ram` : RAM allouée (ex: `2G`, `1.5G`, `512M` — défaut: `1.5G`)
  - `duckdns_domain` : Domaine DuckDNS (optionnel)
- `/removeserver [serveur]` — Supprime un serveur de la configuration
- `/editserver [serveur]` — Modifie la configuration d'un serveur existant
  - `name`, `instance_id`, `region`, `duckdns_domain`, `hourly_cost` (tous optionnels)
- `/setchannel [canal]` — Définit le canal de notifications (auto-stop, etc.)
- `/setpermission [commande] [rôle]` — Autorise un rôle Discord à utiliser `/start` ou `/stop`
- `/resetpermission [commande]` — Remet les permissions d'une commande aux valeurs par défaut
- `/listpermissions` — Affiche les permissions configurées pour ce serveur Discord

## Installation

### 1. Prérequis

```bash
pip install -r requirements.txt
```

Dépendances principales : `discord.py`, `boto3`, `python-dotenv`, `mcstatus`, `paramiko`.

### 2. Configuration de l'environnement

Copiez `.env.example` en `.env` et renseignez les valeurs :

```env
# Token du bot Discord
DISCORD_TOKEN=votre_token_discord

# DuckDNS (utilisé par duck.sh sur l'instance EC2)
DUCKDNS_DOMAIN=
DUCKDNS_TOKEN=

# SSH : pour le setup automatique via /createserver
# MC_SERVER_HOST=ec2-xx-xx-xx-xx.eu-north-1.compute.amazonaws.com
# MC_SERVER_USER=ec2-user
# MC_SERVER_KEY_PATH=/keys/server-mc.pem
# MC_MCRCON_PATH=/usr/local/bin/mcrcon  # chemin vers le binaire mcrcon sur l'instance EC2

# AWS : à renseigner uniquement en dehors d'une instance EC2
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
```

> Si le bot tourne sur une instance EC2 avec un IAM Role, boto3 récupère les credentials AWS automatiquement — ne pas renseigner `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

### 3. Lancement

```bash
python main.py
```

Ou avec Docker :

```bash
docker-compose up -d
```

> `servers_config.json` est créé automatiquement au premier démarrage. Configurez ensuite vos serveurs directement depuis Discord avec `/createserver`, `/setchannel`, etc.

## Architecture

```
bot-serveur-mc/
├── main.py                  # Point d'entrée : initialisation du bot et enregistrement des commandes
├── bot/
│   ├── commands/
│   │   ├── control.py       # /start, /stop, /status
│   │   ├── info.py          # /list, /ip, /uptime
│   │   ├── stats.py         # /cost, /players
│   │   └── admin.py         # /createserver, /removeserver, /editserver, /setchannel, permissions
│   ├── tasks.py             # Tâches asyncio : notify_server_ready, auto_stop_loop
│   ├── aws.py               # Client EC2 boto3
│   ├── config.py            # Chargement/sauvegarde de servers_config.json
│   ├── permissions.py       # Vérification des permissions par rôle
│   ├── ssh.py               # Setup SSH des instances EC2 (paramiko)
│   ├── autocomplete.py      # Autocomplétion Discord par guild
│   ├── port_manager.py      # Attribution automatique de ports
│   └── helpers.py           # Utilitaires (slugify, etc.)
├── scripts/                 # Scripts utilitaires pour l'instance EC2
│   ├── duck.sh              # Mise à jour DuckDNS
│   ├── check_idle.sh        # Vérification d'inactivité
│   ├── check_players.sh     # Comptage des joueurs
│   └── stop_minecraft.sh    # Arrêt du serveur Minecraft
├── tests/
│   ├── test_core.py
│   └── test_tasks.py
├── servers_config.json      # Configuration des guilds et serveurs (auto-créé au démarrage)
├── .env                     # Variables d'environnement (à créer)
├── .env.example
├── Dockerfile
└── docker-compose.yaml
```

### Isolation par serveur Discord

Chaque serveur Discord (guild) a sa propre configuration de serveurs Minecraft. L'autocomplétion des commandes est dynamique et ne montre que les serveurs configurés pour le serveur Discord actuel.

**Exemple :**

- Serveur Discord A → voit uniquement ses serveurs Minecraft (Survie, Créatif)
- Serveur Discord B → voit uniquement ses serveurs Minecraft (Moddé, Skyblock)

### Gestion AWS

Le bot utilise boto3 pour interagir avec AWS EC2 :

- **EC2** : Démarrage, arrêt, statut des instances, récupération de l'IP publique
- Chaque serveur Minecraft peut être dans une région AWS différente

> Sur une instance EC2 avec IAM Role, aucune clé AWS n'est nécessaire dans l'environnement.

### Auto-stop

La boucle `auto_stop_loop` s'exécute toutes les 5 minutes. Pour chaque serveur en état `running`, elle pinge le serveur Minecraft via `mcstatus`. Si aucun joueur n'est connecté depuis `idle_timeout_minutes`, l'instance EC2 est arrêtée et une notification est envoyée dans le canal configuré via `/setchannel`.

### Setup SSH automatique (`/createserver`)

La commande `/createserver` :

1. Attribue automatiquement un port disponible
2. Enregistre la configuration dans `servers_config.json`
3. Se connecte en SSH à l'instance EC2 (`paramiko`) pour créer la structure du serveur :
   - Dossier `~/minecraft-servers/<key>`
   - Téléchargement de `server.jar`
   - Génération de `eula.txt` et `server.properties`

Variables d'environnement requises pour le SSH : `MC_SERVER_HOST`, `MC_SERVER_KEY_PATH` (et optionnellement `MC_SERVER_USER`, `MC_SERVER_JAR_URL`).

### Prérequis sur l'instance EC2

Le bot contrôle les serveurs Minecraft via SSH et RCON. L'instance EC2 doit avoir les outils suivants installés :

- **Java 21** (installé automatiquement par `/createserver` via `amazon-corretto-headless`)
- **mcrcon** — client RCON en ligne de commande, utilisé par le bot pour envoyer des commandes aux serveurs et vérifier leur disponibilité

Installation de `mcrcon` sur l'instance (Amazon Linux 2023 / AL2) :

```bash
# Compilation depuis les sources (recommandé)
sudo dnf install -y gcc git
git clone https://github.com/Tiiffi/mcrcon.git /tmp/mcrcon
cd /tmp/mcrcon && make && sudo make install
# Binaire installé dans /usr/local/bin/mcrcon (chemin par défaut)
```

Le chemin du binaire est configurable via la variable d'environnement `MC_MCRCON_PATH` (défaut : `/usr/local/bin/mcrcon`). Utile si l'instance EC2 utilise un chemin d'installation différent.

## Configuration DuckDNS

Lorsqu'une instance EC2 redémarre, son adresse IP publique change. DuckDNS permet d'avoir un domaine fixe (ex: `mc-survival.duckdns.org`) qui pointe toujours vers votre serveur.

### Mise à jour automatique de l'IP

Le script `scripts/duck.sh` est à exécuter sur l'instance EC2 (crontab ou User Data). Il lit les variables d'environnement `DUCKDNS_DOMAIN` et `DUCKDNS_TOKEN` :

```bash
# Exemple crontab (toutes les 5 minutes)
*/5 * * * * DUCKDNS_DOMAIN=mc-survival DUCKDNS_TOKEN=votre-token /path/to/duck.sh
```

### Configuration du domaine dans le bot

Via Discord :

```
/createserver
  name: Survie
  instance_id: i-0123456789abcdef0
  duckdns_domain: mc-survival.duckdns.org
```

Utilisez `/ip survival` pour obtenir l'adresse du serveur.

## Docker

```yaml
services:
  bot:
    build: .
    container_name: my-mc-bot
    env_file: .env
    restart: unless-stopped
    volumes:
      - .:/app
      - ../keys/mc-host.pem:/keys/mc-host.pem:ro
    working_dir: /app
    command: python -u main.py
```

La clé SSH pour le setup des instances EC2 est montée en lecture seule depuis `../keys/mc-host.pem`.

## Permissions Discord requises

Le bot nécessite les permissions suivantes :

- `applications.commands` (pour les slash commands)
- `Send Messages` (pour envoyer des réponses)

## Sécurité

- Ne partagez jamais votre fichier `.env`
- Utilisez des rôles IAM AWS avec permissions minimales (EC2: `StartInstances`, `StopInstances`, `DescribeInstances`, `DescribeInstanceStatus`)
- La clé SSH PEM ne doit pas être commitée — elle est montée via un volume Docker

## Licence

MIT
