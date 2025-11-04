# 🚀 Guide de Démarrage Rapide

## Configuration en 5 minutes

### Étape 1 : Récupérer votre Guild ID Discord

1. Dans Discord, allez dans **Paramètres utilisateur** > **Avancés**
2. Activez le **Mode développeur**
3. Faites un **clic droit** sur votre serveur Discord dans la liste
4. Cliquez sur **"Copier l'identifiant du serveur"**
5. Conservez cet ID (format : `123456789012345678`)

### Étape 2 : Configurer vos serveurs

1. Copiez le fichier d'exemple :

   ```bash
   cp servers_config.example.json servers_config.json
   ```

2. Éditez `servers_config.json` :

   ```json
   {
     "guilds": {
       "VOTRE_GUILD_ID_ICI": {
         "name": "Nom de votre serveur",
         "servers": {
           "survival": {
             "name": "Survie",
             "instance_id": "i-XXXXXXXXXXXXXXXXX",
             "region": "eu-north-1",
             "hourly_cost": 0.0416,
             "emoji": "⛏️"
           }
         }
       }
     }
   }
   ```

3. Remplacez :
   - `VOTRE_GUILD_ID_ICI` par l'ID copié à l'étape 1
   - `instance_id` par l'ID de votre instance EC2
   - `region` par la région AWS de votre instance
   - `hourly_cost` par le coût horaire de votre instance

### Étape 3 : Configurer le token Discord

1. Créez un fichier `.env` :

   ```bash
   echo "DISCORD_TOKEN=votre_token_discord" > .env
   ```

2. Pour obtenir le token :
   - Allez sur [Discord Developer Portal](https://discord.com/developers/applications)
   - Créez une nouvelle application ou sélectionnez-en une existante
   - Allez dans **Bot** > **Token** > **Reset Token**
   - Copiez le token et remplacez `votre_token_discord`

### Étape 4 : Lancer le bot

#### Avec Docker (recommandé)

```bash
docker-compose up -d
```

#### Sans Docker

```bash
pip install -r requirements.txt
python minecraft-bot.py
```

### Étape 5 : Tester

Dans Discord, tapez :

```
/list
```

Vous devriez voir la liste de vos serveurs Minecraft ! 🎉

## 🔧 Ajouter plus de serveurs

Ajoutez simplement plus d'entrées dans `servers_config.json` :

```json
{
  "guilds": {
    "123456789012345678": {
      "name": "Mon Serveur",
      "servers": {
        "survival": { ... },
        "creative": {
          "name": "Créatif",
          "instance_id": "i-yyyyyyyyyyyyy",
          "region": "eu-north-1",
          "hourly_cost": 0.0416,
          "emoji": "🎨"
        },
        "modded": {
          "name": "Moddé",
          "instance_id": "i-zzzzzzzzzzzzz",
          "region": "eu-west-1",
          "hourly_cost": 0.0832,
          "emoji": "🔧"
        }
      }
    }
  }
}
```

Redémarrez le bot pour appliquer les changements.

## ❓ Problèmes fréquents

### Le bot ne répond pas

- Vérifiez que le bot est en ligne dans Discord
- Vérifiez les logs : `docker-compose logs -f` ou regardez la console

### L'autocomplétion ne fonctionne pas

- Attendez quelques minutes après le démarrage (Discord met à jour les commandes)
- Vérifiez que le Guild ID est correct dans `servers_config.json`

### Erreur AWS

- Vérifiez vos credentials AWS (`aws configure`)
- Vérifiez que votre utilisateur IAM a les permissions EC2 nécessaires

## 📚 Plus d'aide

Consultez le [README.md](README.md) pour plus de détails.
