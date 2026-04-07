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
- **Support Fabric** : Installation automatique du loader Fabric et des mods d'optimisation via Modrinth
- **Support Bedrock** : Déploiement automatique de Paper + Geyser + Floodgate + ViaVersion pour les clients Bedrock
- **Logs à distance** : Récupération des logs de la console Minecraft via `/logs`

## Commandes disponibles

### Gestion des serveurs (publiques)

| Commande              | Description                                          |
| --------------------- | ---------------------------------------------------- |
| `/list`               | Liste tous les serveurs Minecraft disponibles        |
| `/ip [serveur]`       | Obtient l'adresse IP ou le domaine du serveur        |
| `/status [serveur]`   | Vérifie l'état EC2 et le processus Java du serveur   |
| `/uptime [serveur]`   | Affiche l'uptime et le coût estimé                   |
| `/players [serveur]`  | Affiche les joueurs connectés (ping Minecraft direct) |

### Contrôle des serveurs (configurables)

| Commande              | Permission par défaut | Description                          |
| --------------------- | --------------------- | ------------------------------------ |
| `/start [serveur]`    | Tout le monde         | Démarre un serveur Minecraft         |
| `/stop [serveur]`     | Admin                 | Arrête un serveur Minecraft          |
| `/restart [serveur]`  | Admin                 | Redémarre le processus Java (sans toucher à l'instance EC2) |

### Administration (Administrateurs uniquement)

| Commande                        | Description                                                                               |
| ------------------------------- | ----------------------------------------------------------------------------------------- |
| `/createserver`                 | Crée un nouveau serveur avec attribution automatique de port et setup SSH                 |
| `/removeserver [serveur]`       | Supprime un serveur de la configuration (avec option de supprimer les fichiers sur l'instance) |
| `/editserver [serveur]`         | Modifie la configuration d'un serveur existant                                            |
| `/properties [serveur]`         | Modifie les propriétés du serveur (motd, max_players, ops, whitelist, icône)             |
| `/logs [serveur] [number]`      | Affiche les dernières lignes de logs de la console (max 100 lignes)                      |
| `/setchannel [canal]`           | Définit le canal de notifications (auto-stop, etc.)                                       |
| `/setpermission [cmd] [rôle]`   | Autorise un rôle Discord à utiliser `/start` ou `/stop`                                  |
| `/resetpermission [cmd]`        | Remet les permissions d'une commande aux valeurs par défaut                               |
| `/listpermissions`              | Affiche toutes les permissions configurées pour ce serveur Discord                        |
| `/setdefault [param] [valeur]`  | Définit un paramètre par défaut pour la guild (instance_id, region, hourly_cost, max_ram) |
| `/showdefaults`                 | Affiche les paramètres par défaut configurés pour ce serveur Discord                      |

#### Paramètres de `/createserver`

| Paramètre         | Description                                                                       |
| ----------------- | --------------------------------------------------------------------------------- |
| `name`            | Nom affiché du serveur                                                            |
| `instance_id`     | ID de l'instance EC2 (ex: `i-0123456789abcdef0`) — utilise le défaut si omis    |
| `ram`             | RAM allouée (ex: `2G`, `1536M`, `512M` — défaut: `1536M`)                       |
| `region`          | Région AWS (ex: `eu-north-1`) — utilise le défaut si omis                        |
| `version`         | Version Minecraft (ex: `1.21.4`, `latest`)                                        |
| `motd`            | Description affichée dans la liste de serveurs                                    |
| `max_players`     | Nombre maximum de joueurs (défaut: 20)                                            |
| `gamemode`        | Mode de jeu (Survie, Créatif, Hardcore)                                           |
| `seed`            | Graine de génération du monde (optionnel)                                         |
| `icon_url`        | URL d'une image PNG 64×64 pour l'icône du serveur (optionnel)                    |
| `server_type`     | Type de serveur : `Vanilla`, `Bedrock` (Paper + Geyser), `Modé (Fabric)`        |

## Installation

### 1. Prérequis

```bash
pip install -r requirements.txt
```

Dépendances principales : `discord.py`, `boto3`, `python-dotenv`, `mcstatus`, `paramiko`, `aiohttp`.

### 2. Configuration de l'environnement

Copiez `.env.example` en `.env` et renseignez les valeurs :

```env
# Token du bot Discord
DISCORD_TOKEN=votre_token_discord

# DuckDNS (utilisé pour avoir un domaine fixe malgré les IP dynamiques)
DUCKDNS_DOMAIN=mon-serveur
DUCKDNS_TOKEN=votre-token-duckdns

# SSH : connexion à l'instance EC2 pour le setup et le contrôle
MC_SERVER_INSTANCE_ID=i-xxxxxxxxxxxxxxxxx   # résout l'IP publique via boto3
MC_SERVER_REGION=eu-north-1
# MC_SERVER_HOST=                           # override statique optionnel
MC_SERVER_USER=ec2-user
MC_SERVER_KEY_PATH=/keys/server-mc.pem
# MC_MCRCON_PATH=/usr/local/bin/mcrcon     # chemin vers mcrcon (défaut: /usr/local/bin/mcrcon)

# AWS : NE PAS RENSEIGNER si le bot tourne sur une instance EC2 avec un IAM Role.
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
docker-compose up -d --build
```

> `servers_config.json` est créé automatiquement au premier démarrage. Configurez ensuite vos serveurs directement depuis Discord avec `/createserver`, `/setchannel`, etc.

## Architecture

```
bot-serveur-mc/
├── main.py                     # Point d'entrée : initialisation du bot
├── bot/
│   ├── commands/
│   │   ├── control.py          # /start, /stop, /restart, /status
│   │   ├── info.py             # /list, /ip, /uptime
│   │   ├── stats.py            # /players
│   │   ├── logs.py             # /logs (récupération via SSH)
│   │   ├── admin.py            # /createserver, /removeserver, /editserver,
│   │   │                       # /properties, /setchannel, /setpermission,
│   │   │                       # /resetpermission, /listpermissions,
│   │   │                       # /setdefault, /showdefaults
│   │   └── helpers.py          # Utilitaires partagés entre commandes
│   ├── tasks.py                # Tâches asyncio : notify_server_ready, auto_stop_loop
│   ├── aws.py                  # Client EC2 boto3
│   ├── config.py               # Chargement/sauvegarde de servers_config.json
│   ├── permissions.py          # Vérification des permissions par rôle
│   ├── minecraft_process.py    # Cycle de vie du processus Java (start, stop, setup)
│   ├── ssh.py                  # Connexion SSH paramiko, résolution d'hôte
│   ├── autocomplete.py         # Autocomplétion Discord par guild
│   ├── port_manager.py         # Attribution automatique de ports (avec instance_id)
│   ├── helpers.py              # Utilitaires globaux (@require_admin, slugify…)
│   ├── mojang.py               # Résolution de version et UUID joueur via API Mojang
│   ├── papermc.py              # URLs PaperMC, Geyser, Floodgate, ViaVersion
│   └── fabric.py               # URLs Fabric server et mods Modrinth
├── scripts/                    # Scripts déployés sur l'instance EC2
│   ├── duck.sh                 # Mise à jour DuckDNS
│   ├── check_idle.sh           # Vérification d'inactivité
│   ├── check_players.sh        # Comptage des joueurs
│   └── stop_minecraft.sh       # Arrêt du serveur Minecraft
├── tests/
│   ├── test_core.py
│   └── test_tasks.py
├── servers_config.json         # Configuration des guilds et serveurs (auto-créé)
├── .env
├── .env.example
├── Dockerfile
└── docker-compose.yaml
```

### Isolation par serveur Discord

Chaque serveur Discord (guild) a sa propre configuration de serveurs Minecraft. L'autocomplétion des commandes est dynamique et ne montre que les serveurs configurés pour le serveur Discord actuel.

**Exemple :**

- Serveur Discord A — voit uniquement ses serveurs Minecraft (Survie, Créatif)
- Serveur Discord B — voit uniquement ses serveurs Minecraft (Moddé, Skyblock)

### Gestion AWS

Le bot utilise boto3 pour interagir avec AWS EC2 :

- **EC2** : Démarrage, arrêt, statut des instances, récupération de l'IP publique
- Chaque serveur Minecraft peut être dans une région AWS différente
- L'IP publique est résolue dynamiquement via `MC_SERVER_INSTANCE_ID` (recommandé) ou statiquement via `MC_SERVER_HOST`

> Sur une instance EC2 avec IAM Role, aucune clé AWS n'est nécessaire dans l'environnement.

### Types de serveurs

| Type    | Moteur                              | Description                                         |
| ------- | ----------------------------------- | --------------------------------------------------- |
| Vanilla | server.jar officiel Mojang          | Serveur standard sans mods                          |
| Bedrock | Paper + Geyser + Floodgate + ViaVersion | Compatibilité clients Bedrock et Java          |
| Fabric  | Fabric server + mods Modrinth       | Mods d'optimisation : fabric-api, ferrite-core, lithium, modernfix, memoryleakfix, krypton, chunky, noisium |

La liste des mods Fabric peut être personnalisée via la clé `optimization_mods` dans `servers_config.json`.

### Auto-stop

La boucle `auto_stop_loop` s'exécute toutes les 5 minutes. Pour chaque serveur en état `running`, elle pinge le serveur Minecraft via `mcstatus` puis applique deux logiques d'arrêt distinctes :

#### Arrêt par inactivité

Le serveur Minecraft répond au ping mais aucun joueur n'est connecté. Si cette situation dure plus de `idle_timeout_minutes` minutes (défaut : 30 min), l'arrêt est déclenché :

1. Arrêt gracieux du processus Java via RCON.
2. Vérification SSH des autres serveurs sur la même instance.
3. Si aucun autre serveur actif → arrêt de l'instance EC2.

Notification Discord : `:red_circle: **Auto-stop** : … après X minutes sans joueur connecté.`

#### Arrêt zombie

Le serveur Minecraft ne répond plus au ping (timeout `mcstatus`). Deux causes possibles : le serveur est encore en cours de démarrage, ou le processus Java s'est arrêté anormalement en laissant l'instance EC2 allumée.

Le bot vérifie via SSH si le processus Java est toujours en cours d'exécution :

- **Java en cours / SSH injoignable** → on considère que le serveur est en démarrage et on attend le prochain cycle.
- **Java arrêté** → instance zombie. Le bot vérifie si d'autres serveurs tournent sur la même instance. Si aucun autre serveur n'est actif, l'instance EC2 est arrêtée immédiatement (sans attendre `idle_timeout_minutes`).

Notification Discord : `:red_circle: **Auto-stop (zombie)** : … processus Java n'est plus en cours d'exécution.`

### Arrêt intelligent multi-serveurs

Lors d'un `/stop`, le bot vérifie via SSH si d'autres serveurs Minecraft tournent sur la même instance. L'instance EC2 n'est arrêtée que si aucun autre serveur n'est actif. Si le SSH est injoignable, l'instance est conservée par précaution.

### Setup SSH automatique (`/createserver`)

La commande `/createserver` :

1. Attribue automatiquement un port disponible (en tenant compte de l'`instance_id`)
2. Enregistre la configuration dans `servers_config.json`
3. Si l'instance est démarrée : se connecte en SSH via `paramiko` pour créer la structure du serveur
4. Si l'instance est arrêtée : propose de la démarrer d'abord ou d'installer plus tard

Structure créée sur l'instance : `~/minecraft-servers/<key>/` avec `server.jar`, `eula.txt` et `server.properties`.

### Commande `/properties`

Permet de modifier à chaud les propriétés d'un serveur existant :

- `motd`, `max_players`, `gamemode` (nécessitent un `/restart` pour être appliqués)
- `add_admin` : promeut un joueur opérateur (résolution UUID via API Mojang)
- `add_whitelist` : ajoute des joueurs à la whitelist (virgule-séparés, résolution UUID)
- `icon_url` : définit l'icône du serveur

Si l'instance est arrêtée, le bot propose de la démarrer avant la modification.

### Commande `/logs`

Récupère via SSH les dernières lignes de log du serveur (jusqu'à 100 lignes). Lit `logs/latest.log` en priorité, puis `stdout.log` en fallback. Le résultat est découpé automatiquement en plusieurs messages si le contenu dépasse la limite Discord.

### Paramètres par défaut de la guild

`/setdefault` permet de définir des valeurs par défaut pour la guild (`instance_id`, `region`, `hourly_cost`, `max_ram`). Ces valeurs sont utilisées automatiquement par `/createserver` si le paramètre n'est pas fourni explicitement, ce qui simplifie la création de serveurs sur une infrastructure partagée.

### Attribution automatique de ports

Le `port_manager.py` attribue les ports Minecraft (TCP) et Bedrock (UDP) sans collision, en tenant compte de l'`instance_id` pour isoler les plages de ports par instance.

## Prérequis sur l'instance EC2

Le bot contrôle les serveurs Minecraft via SSH et RCON. L'instance EC2 doit avoir :

- **Java 21** (installé automatiquement par `/createserver` via `amazon-corretto-headless`)
- **mcrcon** — client RCON en ligne de commande

Installation de `mcrcon` sur l'instance (Amazon Linux 2) :

```bash
sudo yum install -y gcc git
git clone https://github.com/Tiiffi/mcrcon.git /tmp/mcrcon
cd /tmp/mcrcon && make && sudo make install
# Binaire installé dans /usr/local/bin/mcrcon (chemin par défaut)
```

Le chemin du binaire est configurable via `MC_MCRCON_PATH` (défaut : `/usr/local/bin/mcrcon`).

## Configuration DuckDNS

Lorsqu'une instance EC2 redémarre, son adresse IP publique change. DuckDNS permet d'avoir un domaine fixe (ex: `mc-survival.duckdns.org`).

### Mise à jour automatique de l'IP

Le script `scripts/duck.sh` est à exécuter sur l'instance EC2 (crontab ou User Data) :

```bash
# Exemple crontab (toutes les 5 minutes)
*/5 * * * * DUCKDNS_DOMAIN=mc-survival DUCKDNS_TOKEN=votre-token /path/to/duck.sh
```

### Configuration du domaine dans le bot

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
  serveur-mc:
    build: .
    container_name: serveur-mc
    env_file: .env
    restart: unless-stopped
    volumes:
      - ../keys/mc-host.pem:/keys/mc-host.pem:ro
    working_dir: /app
    command: python -u main.py
```

La clé SSH est montée en lecture seule depuis `../keys/mc-host.pem` (partagé avec les autres bots du dépôt).

## Permissions Discord requises

- `applications.commands` (pour les slash commands)
- `Send Messages` (pour envoyer des réponses)

## Sécurité

- Ne partagez jamais votre fichier `.env`
- Utilisez des rôles IAM AWS avec permissions minimales : `ec2:StartInstances`, `ec2:StopInstances`, `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus`
- La clé SSH PEM ne doit pas être commitée — elle est montée via un volume Docker
- `servers_config.json` est listé dans `.gitignore`
