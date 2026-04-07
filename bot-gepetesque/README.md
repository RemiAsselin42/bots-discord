# Bot Discord DeepSeek (Gépétesque)

Bot Discord conversationnel basé sur l'IA de [DeepSeek](https://deepseek.com), avec mémoire persistante, résumé automatique et accès web intégré.

## Fonctionnalités

- **Conversation** — répond quand il est mentionné (`@bot`), avec historique des 20 derniers messages par salon
- **Mémoire long terme** — retient des informations sur chaque utilisateur entre les sessions
- **Index de faits utilisateur** — structure les infos (ex : surnom, ville, préférences) pour les oublier précisément
- **Résumé automatique** — compresse les vieilles conversations en résumé pour conserver le contexte sans exploser les tokens
- **Accès web automatique** — détecte les URLs dans les messages et injecte le contenu de la page dans le contexte
- **Persistance SQLite** — historique, mémoire et résumés stockés dans `src/data/bot.db`

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

| Commande          | Permission | Description                                                                                                     |
| ----------------- | ---------- | --------------------------------------------------------------------------------------------------------------- |
| `/forget`         | Tous       | Oublie un fait indexé précis (autocomplétion + résolution sémantique IA), nettoie les messages liés            |
| `/memory-list`    | Tous       | Affiche les faits indexés et les notes libres mémorisées                                                        |
| `/forget-all`     | Tous       | Efface toute ta mémoire et tes faits indexés, pose un cutoff (contexte antérieur ignoré), purge le résumé salon |
| `/add-channel`    | Admin      | Autorise le salon actuel                                                                                         |
| `/remove-channel` | Admin      | Retire le salon actuel                                                                                           |
| `/list-channels`  | Admin      | Liste les salons autorisés                                                                                       |
| `/reset-history`  | Admin      | Efface l'historique, le résumé et les mémoires de tous les membres du serveur                                   |

## Installation

### Prérequis

- Node.js 22+
- Un bot Discord ([Discord Developer Portal](https://discord.com/developers/applications))
- Une clé API DeepSeek

### Variables d'environnement

Créer un fichier `.env` à partir de `.env.example` :

```env
DISCORD_TOKEN=ton_token_discord
DEEPSEEK_API_KEY=ta_clé_deepseek

# Active l'indexation automatique des faits utilisateur.
# ATTENTION : double le nombre d'appels API DeepSeek (1 appel supplémentaire par message).
ENABLE_AI_TOPIC_INDEXING=false

CUSTOM_PROMPT="Ton prompt personnalisé ici (optionnel)"
```

### Lancement local

```bash
npm install
npm start
```

### Déploiement Docker

```bash
# Premier démarrage : créer la base de données vide
touch bot.db
docker-compose up -d --build

# Mise à jour après modification du code
docker-compose down
docker-compose up -d --build

# Voir les logs
docker-compose logs -f gepetesque
```

### Déploiement PM2

```bash
# Démarrer avec PM2
pm2 start ecosystem.config.js

# Commandes de gestion
npm run stop       # Arrêter le bot
npm run restart    # Redémarrer et recharger les variables d'environnement
npm run status     # Voir l'état du processus
```

## Architecture

```
src/
├── index.js              — point d'entrée, initialisation Discord
├── config.js             — variables d'environnement et constantes
├── prompt.js             — prompt système du bot
├── bot/
│   ├── commands.js       — enregistrement et gestion des commandes slash
│   ├── memory.js         — détection et écriture de mémoire en langage naturel
│   └── queue.js          — file de traitement des messages (anti-concurrence, cooldown)
├── data/
│   ├── db.js             — point d'entrée de la couche base de données
│   ├── dbCore.js         — initialisation SQLite et migrations de schéma
│   ├── channelDb.js      — opérations sur les salons (historique, résumés, salons autorisés)
│   ├── memoryDb.js       — mémoire long terme par utilisateur
│   ├── factsDb.js        — index de faits utilisateur (clé/valeur)
│   └── migrate.js        — migration des anciens fichiers JSON vers SQLite
└── services/
    ├── ai.js             — appels API DeepSeek (réponse + indexation de faits)
    └── webFetch.js       — fetch de pages web avec protection SSRF
ecosystem.config.js       — configuration PM2
```

### Base de données (`bot.db`)

| Table              | Contenu                                            |
| ------------------ | -------------------------------------------------- |
| `allowed_channels` | Salons autorisés par guild                         |
| `message_history`  | Historique de conversation par salon (20 derniers) |
| `channel_summary`  | Résumé compressé des vieilles conversations        |
| `user_memory`      | Mémoire long terme par utilisateur et par guild    |
| `user_fact_index`  | Faits utilisateur indexés (clé/valeur)             |

### Index de faits utilisateur (`ENABLE_AI_TOPIC_INDEXING`)

Quand activé, chaque échange déclenche un appel DeepSeek supplémentaire pour extraire et stocker les faits mentionnés par l'utilisateur (surnom, ville, préférences…) dans `user_fact_index`. Ces faits sont injectés dans le contexte de chaque réponse.

> **Impact coût** : activé = 2 appels API par message (réponse + indexation). Désactiver (`ENABLE_AI_TOPIC_INDEXING=false`) si la consommation est un problème.

### Oubli précis

`/forget` supprime un sujet exact de l'index (ex : `surnom`, `fruit préféré`) au lieu d'une suppression texte trop large. Utilise `/memory-list` pour voir les sujets disponibles et sélectionner le bon.

### Résumé automatique

Quand un salon dépasse **40 messages**, le bot génère automatiquement un résumé des 20 messages les plus anciens via DeepSeek, le stocke dans `channel_summary`, et supprime ces vieux messages. Ce résumé est injecté en tête de contexte à chaque réponse.

### Accès web

Les URLs `http://` et `https://` dans les messages sont détectées automatiquement. Le bot fetch la page, extrait le texte lisible (4 000 caractères max) et l'injecte dans le contexte. Protections : blocage des IP internes (SSRF), timeout 10s, limite 500 Ko.

### File de traitement et cooldown

Les messages sont traités séquentiellement via une file (`queue.js`) pour éviter les requêtes concurrentes vers l'API DeepSeek. Un cooldown de **10 secondes** entre deux requêtes du même utilisateur est appliqué. Si un message plus récent arrive pendant le traitement, le précédent est annulé.

## Sécurité web (anti-SSRF)

Les adresses suivantes sont bloquées : `localhost`, `127.x`, `10.x`, `192.168.x`, `172.16-31.x`, link-local, IPv6 privées. Seuls les protocoles `http` et `https` sont acceptés.

## Qualité & Validation

Pour garantir la robustesse, la confidentialité et la maintenabilité du bot, des scripts de validation sont disponibles :

### Lint (ESLint)

Analyse statique du code pour détecter les erreurs, incohérences et mauvaises pratiques.

```bash
npm run lint
```

### Tests (Node.js)

Exécute les tests unitaires et d'intégration (notamment sur la mémoire et la confidentialité).

```bash
npm test
```

> **Astuce :** Exécutez ces deux commandes avant chaque commit ou déploiement pour garantir la qualité et la conformité du code.
