# 🔧 Guide d'Administration - Gestion des Serveurs

## Ajouter un serveur depuis Discord

### Commande : `/addserver`

Permet d'ajouter un nouveau serveur Minecraft à votre configuration sans éditer de fichier !

### 📝 Paramètres requis

| Paramètre     | Description                                                                       | Exemple                                |
| ------------- | --------------------------------------------------------------------------------- | -------------------------------------- |
| `key`         | Identifiant unique du serveur (lettres, chiffres, tirets, underscores uniquement) | `survival`, `creative`, `modded_v2`    |
| `name`        | Nom affiché dans Discord                                                          | `Survie`, `Créatif`, `Moddé`           |
| `instance_id` | ID de l'instance EC2 AWS (format: `i-` suivi de 17 caractères)                    | `i-0123456789abcdef0`                  |
| `region`      | Région AWS où se trouve l'instance                                                | `eu-north-1`, `us-east-1`, `eu-west-1` |
| `hourly_cost` | Coût horaire en USD (pour calcul des coûts)                                       | `0.0416`, `0.0832`                     |
| `emoji`       | Emoji affiché (optionnel, par défaut: 🖥️)                                         | `⛏️`, `🎨`, `🔧`                       |

### ✅ Exemple d'utilisation

```
/addserver
  key: skyblock
  name: Skyblock
  instance_id: i-XXXXXXXXXXXXXXXXX
  region: eu-north-1
  hourly_cost: 0.0416
  emoji: 🌍
```

**Résultat :**

```
✅ Serveur 🌍 Skyblock (skyblock) ajouté avec succès !

📋 Détails :
• Instance: i-XXXXXXXXXXXXXXXXX
• Région: eu-north-1
• Coût horaire: $0.0416

Utilisez /start skyblock pour le démarrer.
```

### 🔍 Comment obtenir les informations ?

#### 1. Instance ID

1. Connectez-vous à la [Console AWS EC2](https://console.aws.amazon.com/ec2/)
2. Cliquez sur "Instances"
3. Sélectionnez votre serveur Minecraft
4. Copiez l'**ID d'instance** (format `i-xxxxxxxxxxxxx`)

#### 2. Région AWS

Dans la console AWS, en haut à droite, vous verrez la région (ex: `eu-north-1`, `us-east-1`)

#### 3. Coût horaire

Consultez la [page des tarifs AWS EC2](https://aws.amazon.com/ec2/pricing/on-demand/)

**Exemples de coûts (à vérifier sur AWS) :**

- `t3.medium` : ~$0.0416/h
- `t3.large` : ~$0.0832/h
- `t3.xlarge` : ~$0.1664/h

#### 4. Emoji

Copiez-collez simplement un emoji depuis votre clavier ou un site comme [emojipedia.com](https://emojipedia.org/)

**Suggestions d'emojis :**

- ⛏️ Survie
- 🎨 Créatif
- 🔧 Moddé
- 🌍 Skyblock
- ⚔️ PvP
- 🏰 Médiéval

---

## Supprimer un serveur depuis Discord

### Commande : `/removeserver`

Supprime un serveur de la configuration. **Attention : cette action est irréversible !**

### ✅ Exemple d'utilisation

```
/removeserver server:skyblock
```

Le bot vous proposera l'autocomplétion avec tous vos serveurs configurés.

**Résultat :**

```
✅ Serveur 🌍 Skyblock (skyblock) supprimé avec succès.
```

---

## 🔐 Permissions

**Seuls les administrateurs du serveur Discord peuvent utiliser ces commandes.**

Pour donner les permissions d'administrateur :

1. Dans Discord, clic droit sur un rôle
2. Paramètres du rôle > Permissions
3. Activez "Administrateur"

---

## ⚠️ Cas d'erreur

### ❌ "Format d'instance_id invalide"

- Vérifiez que l'instance_id commence par `i-` et fait 19 caractères
- Exemple valide : `i-0123456789abcdef0`

### ❌ "La clé doit contenir uniquement..."

- Utilisez uniquement : lettres, chiffres, tirets (`-`), underscores (`_`)
- ✅ Valide : `survival`, `creative-1`, `modded_v2`
- ❌ Invalide : `survie!`, `créatif`, `modded v2`

### ❌ "Un serveur avec la clé X existe déjà"

- Choisissez une clé différente (ex: `survival2`, `survival_v2`)
- Ou supprimez d'abord l'ancien serveur avec `/removeserver`

### ❌ "Seuls les administrateurs peuvent..."

- Vous devez avoir les permissions d'administrateur sur le serveur Discord

---

## 💡 Bonnes pratiques

1. **Nommage cohérent** : Utilisez des clés descriptives (ex: `survival_vanilla`, `creative_build`)
2. **Vérifiez les coûts** : Consultez AWS pour avoir les tarifs à jour
3. **Testez immédiatement** : Après l'ajout, testez avec `/status` et `/start`
4. **Documentez** : Notez quelque part quelle instance correspond à quel serveur

---

## 🎯 Workflow typique

1. **Créer une instance EC2** sur AWS
2. **Installer Minecraft** sur l'instance
3. **Ajouter via Discord** avec `/addserver`
4. **Tester** avec `/start` et `/status`
5. **Partager** avec vos joueurs !

---

## 📊 Exemple de configuration complète

Pour un serveur Discord avec plusieurs serveurs Minecraft :

```
/addserver key:survival name:"Survie Vanilla" instance_id:i-xxx region:eu-north-1 hourly_cost:0.0416 emoji:⛏️
/addserver key:creative name:"Créatif" instance_id:i-yyy region:eu-north-1 hourly_cost:0.0416 emoji:🎨
/addserver key:modded name:"Moddé (FTB)" instance_id:i-zzz region:eu-west-1 hourly_cost:0.0832 emoji:🔧
/addserver key:pvp name:"Arène PvP" instance_id:i-aaa region:us-east-1 hourly_cost:0.0416 emoji:⚔️
```

Tous vos serveurs sont maintenant disponibles avec autocomplétion ! 🎉
