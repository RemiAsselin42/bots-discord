# 🎬 Démonstration - Commandes d'Administration

## Scénario : Ajout d'un nouveau serveur Minecraft

### 📝 Étape 1 : Vérifier les serveurs actuels

**Commande utilisateur :**

```
/list
```

**Réponse du bot :**

```
🖥️ Serveurs Minecraft disponibles :

⛏️ Survie (survival)
🎨 Créatif (creative)
```

---

### ➕ Étape 2 : Ajouter un nouveau serveur

**Commande administrateur :**

```
/addserver
  key: modded
  name: Moddé FTB
  instance_id: i-0abc123def456789a
  region: eu-west-1
  hourly_cost: 0.0832
  emoji: 🔧
```

**Réponse du bot :**

```
✅ Serveur 🔧 Moddé FTB (modded) ajouté avec succès !

📋 Détails :
• Instance: i-0abc123def456789a
• Région: eu-west-1
• Coût horaire: $0.0832

Utilisez /start modded pour le démarrer.
```

---

### ✨ Étape 3 : Vérifier que le serveur est disponible

**Commande utilisateur :**

```
/list
```

**Réponse du bot :**

```
🖥️ Serveurs Minecraft disponibles :

⛏️ Survie (survival)
🎨 Créatif (creative)
🔧 Moddé FTB (modded)
```

---

### 🚀 Étape 4 : Démarrer le nouveau serveur

**Commande utilisateur :**

```
/start
```

**Autocomplétion Discord affiche :**

```
⛏️ Survie
🎨 Créatif
🔧 Moddé FTB    ← Nouveau !
```

**Sélection : `🔧 Moddé FTB`**

**Réponse du bot :**

```
🟢 🔧 Le serveur Moddé FTB est en cours de démarrage...
```

---

### ❌ Étape 5 : Supprimer un ancien serveur

**Commande administrateur :**

```
/removeserver server:creative
```

**Réponse du bot :**

```
✅ Serveur 🎨 Créatif (creative) supprimé avec succès.
```

---

## 🛡️ Gestion des erreurs

### Tentative d'ajout avec une clé existante

**Commande :**

```
/addserver key:survival name:"Survie V2" ...
```

**Réponse :**

```
❌ Un serveur avec la clé `survival` existe déjà.
Utilisez une clé différente ou supprimez l'ancien serveur d'abord.
```

---

### Instance ID invalide

**Commande :**

```
/addserver instance_id:invalid-id ...
```

**Réponse :**

```
❌ Format d'instance_id invalide. Exemple: `i-0123456789abcdef0`
```

---

### Clé avec caractères invalides

**Commande :**

```
/addserver key:"survie!" ...
```

**Réponse :**

```
❌ La clé doit contenir uniquement des lettres, chiffres, tirets et underscores.
```

---

### Utilisateur non-administrateur

**Commande :**

```
/addserver (par un joueur normal)
```

**Réponse :**

```
❌ Seuls les administrateurs peuvent ajouter des serveurs.
```

---

## 🎯 Cas d'usage avancés

### Plusieurs serveurs en une fois

```bash
# Serveur Survie
/addserver key:survival name:"Survie Vanilla 1.20" instance_id:i-xxx region:eu-north-1 hourly_cost:0.0416 emoji:⛏️

# Serveur Créatif
/addserver key:creative name:"Créatif Plots" instance_id:i-yyy region:eu-north-1 hourly_cost:0.0416 emoji:🎨

# Serveur Moddé
/addserver key:modded name:"FTB Ultimate" instance_id:i-zzz region:eu-west-1 hourly_cost:0.0832 emoji:🔧

# Serveur PvP
/addserver key:pvp name:"Arène PvP" instance_id:i-aaa region:us-east-1 hourly_cost:0.0416 emoji:⚔️
```

### Migration d'un serveur

```bash
# 1. Ajouter le nouveau serveur
/addserver key:survival_v2 name:"Survie (Nouveau)" instance_id:i-new region:eu-north-1 hourly_cost:0.0416 emoji:⛏️

# 2. Tester le nouveau serveur
/status server:survival_v2
/start server:survival_v2

# 3. Supprimer l'ancien serveur
/removeserver server:survival
```

---

## 📊 Avantages de cette approche

✅ **Pas besoin d'accès au serveur** : Les administrateurs Discord peuvent gérer les serveurs sans SSH/FTP

✅ **Modifications instantanées** : Les changements sont immédiats, pas de redémarrage

✅ **Interface conviviale** : Autocomplétion et messages clairs

✅ **Audit trail** : Les messages Discord servent de log des modifications

✅ **Isolation** : Chaque serveur Discord gère ses propres serveurs Minecraft

✅ **Validation** : Le bot vérifie les formats avant de sauvegarder
