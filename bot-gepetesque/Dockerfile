FROM node:22

# Crée un répertoire pour l'app
WORKDIR /app

# Copie les fichiers nécessaires
COPY package*.json ./
RUN npm install

# Copie le reste du projet
COPY . .

# Commande de lancement via PM2
RUN npm install pm2 -g
CMD ["pm2-runtime", "ecosystem.config.js"]
