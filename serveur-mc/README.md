# Bot Discord Multi-Serveurs Minecraft

Bot Discord pour gérer plusieurs serveurs Minecraft EC2 sur AWS avec autocomplétion par serveur Discord.

## ✨ Fonctionnalités

- ✅ **Multi-serveurs** : Gérez jusqu'à 5 serveurs Minecraft par serveur Discord
- ✅ **Autocomplétion intelligente** : Chaque serveur Discord ne voit que ses propres serveurs Minecraft
- ✅ **Gestion AWS EC2** : Démarrage, arrêt, statut des instances
- ✅ **Suivi des coûts** : Calcul automatique de l'uptime et du coût mensuel
- ✅ **Multi-régions** : Supporte des serveurs dans différentes régions AWS

## 📋 Commandes disponibles

### Gestion des serveurs

- `/start [serveur]` - Démarre un serveur Minecraft
- `/stop [serveur]` - Arrête un serveur Minecraft
- `/status [serveur]` - Vérifie le statut d'un serveur
- `/uptime [serveur]` - Affiche l'uptime et le coût estimé du mois
- `/list` - Liste tous les serveurs Minecraft disponibles

### Administration (Administrateurs uniquement)

- `/addserver` - Ajoute un nouveau serveur à la configuration
  - `key` : Identifiant unique (ex: survival, creative)
  - `name` : Nom affiché
  - `instance_id` : ID de l'instance EC2
  - `region` : Région AWS
  - `hourly_cost` : Coût horaire en USD
  - `emoji` : Emoji (optionnel)
- `/removeserver [serveur]` - Supprime un serveur de la configuration

## 🚀 Installation

### 1. Prérequis

```bash
pip install discord.py boto3 python-dotenv
```

### 2. Configuration AWS

Créez un fichier `.env` :

```env
DISCORD_TOKEN=votre_token_discord
```

Configurez vos credentials AWS (via `aws configure` ou variables d'environnement).

### 3. Configuration des serveurs

Éditez le fichier `servers_config.json` :

```json
{
  "guilds": {
    "VOTRE_GUILD_ID_DISCORD": {
      "name": "Nom de votre serveur Discord",
      "servers": {
        "survival": {
          "name": "Survie",
          "instance_id": "i-xxxxxxxxxxxxx",
          "region": "eu-north-1",
          "hourly_cost": 0.0416,
          "emoji": "⛏️"
        },
        "creative": {
          "name": "Créatif",
          "instance_id": "i-yyyyyyyyyyyyy",
          "region": "eu-north-1",
          "hourly_cost": 0.0416,
          "emoji": "🎨"
        }
      }
    }
  }
}
```

#### Comment obtenir votre Guild ID Discord ?

1. Activez le "Mode développeur" dans Discord (Paramètres > Avancés > Mode développeur)
2. Faites un clic droit sur votre serveur Discord
3. Cliquez sur "Copier l'identifiant du serveur"

#### Paramètres des serveurs :

- **name** : Nom affiché dans Discord
- **instance_id** : ID de l'instance EC2 AWS
- **region** : Région AWS de l'instance
- **hourly_cost** : Coût horaire en USD (pour le calcul des coûts)
- **emoji** : Emoji affiché à côté du nom (optionnel)

### 4. Lancement

```bash
python minecraft-bot.py
```

Ou avec Docker :

```bash
docker-compose up -d
```

## 🏗️ Architecture

### Isolation par serveur Discord

Chaque serveur Discord (guild) a sa propre configuration de serveurs Minecraft. L'autocomplétion des commandes est dynamique et ne montre que les serveurs configurés pour le serveur Discord actuel.

**Exemple :**

- Serveur Discord A → voit uniquement ses serveurs Minecraft (Survie, Créatif)
- Serveur Discord B → voit uniquement ses serveurs Minecraft (Moddé, Skyblock)

### Gestion AWS

Le bot utilise Boto3 pour interagir avec AWS EC2 et CloudWatch :

- **EC2** : Démarrage/arrêt des instances
- **CloudWatch** : Collecte des métriques d'uptime

Chaque serveur Minecraft peut être dans une région AWS différente.

## 📝 Exemple d'utilisation

1. Un utilisateur tape `/start` dans Discord
2. L'autocomplétion affiche uniquement les serveurs de son serveur Discord
3. Il sélectionne "⛏️ Survie"
4. Le bot démarre l'instance EC2 correspondante
5. Un message de confirmation s'affiche : "🟢 ⛏️ Le serveur **Survie** est en cours de démarrage..."

## 🔧 Personnalisation

### Ajouter un nouveau serveur Minecraft

**Méthode 1 : Via Discord (Recommandée)**

Utilisez la commande `/addserver` directement dans Discord :

```
/addserver
  key: survival
  name: Survie
  instance_id: i-0123456789abcdef0
  region: eu-north-1
  hourly_cost: 0.0416
  emoji: ⛏️
```

Le serveur est ajouté instantanément, pas besoin de redémarrer le bot !

**Méthode 2 : Manuellement via JSON**

1. Créez une nouvelle instance EC2 sur AWS
2. Ajoutez une entrée dans `servers_config.json` sous la guild appropriée
3. Redémarrez le bot

### Ajouter un nouveau serveur Discord

1. Invitez le bot sur le nouveau serveur Discord
2. Récupérez le Guild ID
3. Ajoutez une nouvelle section dans `servers_config.json`

## 🐳 Docker

Le bot est conteneurisé avec Docker pour un déploiement facile.

```yaml
services:
  bot:
    build: .
    container_name: my-mc-bot
    env_file: .env
    restart: unless-stopped
```

## 📊 Permissions Discord requises

Le bot nécessite les permissions suivantes :

- `applications.commands` (pour les slash commands)
- `Send Messages` (pour envoyer des réponses)

## ⚠️ Sécurité

- Ne partagez jamais votre fichier `.env`
- Utilisez des rôles IAM AWS avec permissions minimales
- Considérez l'utilisation de AWS Secrets Manager pour les credentials sensibles

## 🤝 Support

Pour toute question ou problème, référez-vous aux logs du bot.

## 📄 Licence

MIT
