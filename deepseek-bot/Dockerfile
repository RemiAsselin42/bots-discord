FROM node:18

# Crée un répertoire pour l'app
WORKDIR /app

# Copie les fichiers nécessaires
COPY package*.json ./
RUN npm install

# Copie le reste du projet
COPY . .

# Expose le port (si tu veux que le bot soit pingable via Express)
EXPOSE 3000

# Commande de lancement via PM2
RUN npm install pm2 -g
CMD ["pm2-runtime", "ecosystem.config.js"]
