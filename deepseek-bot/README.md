# Bot Discord DeepSeek

Bot Discord conversationnel basé sur l'IA de [DeepSeek](https://deepseek.com), avec mémoire persistante, résumé automatique et accès web intégré.

## Fonctionnalités

- **Conversation** — répond quand il est mentionné (`@bot`), avec historique des 20 derniers messages par salon
- **Mémoire long terme** — retient des informations sur chaque utilisateur entre les sessions
- **Résumé automatique** — compresse les vieilles conversations en résumé pour conserver le contexte sans exploser les tokens
- **Accès web automatique** — détecte les URLs dans les messages et injecte le contenu de la page dans le contexte
- **Persistance SQLite** — historique, mémoire et résumés stockés dans `bot.db`

## Utilisation

### Conversation normale

Mentionner le bot dans un salon autorisé :

```
@Bot c'est quoi une monade en Haskell ?
@Bot résume https://example.com
@Bot compare ces deux pages https://... et https://...
```

### Mémoire long terme

```
@Bot souviens-toi que je suis dev backend Python
@Bot retiens que je préfère les réponses courtes
@Bot n'oublie pas que je travaille sur un projet Flask
@Bot oublie tout ce que tu sais sur moi
```

### Commandes slash

| Commande          | Permission | Description                           |
| ----------------- | ---------- | ------------------------------------- |
| `/add-channel`    | Admin      | Autorise le salon actuel              |
| `/remove-channel` | Admin      | Retire le salon actuel                |
| `/list-channels`  | Admin      | Liste les salons autorisés            |
| `/reset-history`  | Tous       | Efface l'historique + résumé du salon |

## Installation

### Prérequis

- Node.js 22+
- Un bot Discord ([Discord Developer Portal](https://discord.com/developers/applications))
- Une clé API DeepSeek

### Variables d'environnement

Créer un fichier `.env` :

```env
DISCORD_TOKEN=ton_token_discord
DEEPSEEK_API_KEY=ta_clé_deepseek
PORT=3000
CUSTOM_PROMPT="Ton prompt personnalisé ici (optionnel)"
```

### Lancement local

```bash
npm install
node index.js
```

### Déploiement Docker

```bash
# Premier démarrage
touch bot.db
docker-compose up -d --build

# Mise à jour après modification du code
docker-compose down
docker-compose up -d --build

# Voir les logs
docker-compose logs -f deepseek-bot
```

> **Note :** `bot.db` est monté en volume pour persister la base SQLite entre les rebuilds.

## Architecture

```
index.js          — point d'entrée, gestion Discord, file de messages
db.js             — couche SQLite (sql.js, pure WASM)
webFetch.js       — fetch de pages web avec protection SSRF
prompt.js         — prompt système du bot
ecosystem.config.js — configuration PM2
```

### Base de données (`bot.db`)

| Table              | Contenu                                            |
| ------------------ | -------------------------------------------------- |
| `allowed_channels` | Salons autorisés par guild                         |
| `message_history`  | Historique de conversation par salon (20 derniers) |
| `channel_summary`  | Résumé compressé des vieilles conversations        |
| `user_memory`      | Mémoire long terme par utilisateur et par guild    |

### Résumé automatique

Quand un salon dépasse **40 messages**, le bot génère automatiquement un résumé des 20 messages les plus anciens via DeepSeek, le stocke dans `channel_summary`, et supprime ces vieux messages. Ce résumé est injecté en tête de contexte à chaque réponse.

### Accès web

Les URLs `http://` et `https://` dans les messages sont détectées automatiquement. Le bot fetch la page, extrait le texte lisible (4 000 caractères max) et l'injecte dans le contexte. Protections : blocage des IP internes (SSRF), timeout 10s, limite 500 Ko.

## Sécurité web (anti-SSRF)

Les adresses suivantes sont bloquées : `localhost`, `127.x`, `10.x`, `192.168.x`, `172.16-31.x`, link-local, IPv6 privées. Seuls les protocoles `http` et `https` sont acceptés.
