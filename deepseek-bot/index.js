require("dotenv").config();
const { Client, GatewayIntentBits } = require("discord.js");
const axios = require("axios");
const express = require("express");
const fs = require("fs");
const path = require("path");
const CUSTOM_PROMPT = require("./prompt");

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers,
        GatewayIntentBits.GuildMessageReactions,
    ],
});

const DEEPSEEK_API_KEY = process.env.DEEPSEEK_API_KEY;
const DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions";

const app = express();
const PORT = process.env.PORT || 3000;

// Route pour "ping" le bot
app.get("/", (_req, res) => {
    res.send("Bot is alive!");
});

// Démarre le serveur Express
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});

const MESSAGE_HISTORY_FILE = path.join(__dirname, "messageHistory.json");

let messageHistory = {};
if (fs.existsSync(MESSAGE_HISTORY_FILE)) {
    try {
        const data = fs.readFileSync(MESSAGE_HISTORY_FILE, "utf-8");
        messageHistory = JSON.parse(data);
    } catch (error) {
        console.error(
            "Erreur lors du chargement de l'historique des messages:",
            error
        );
        messageHistory = {};
    }
}

const ALLOWED_CHANNELS_FILE = path.join(__dirname, "allowedChannels.json");

let allowedChannels = [];
if (fs.existsSync(ALLOWED_CHANNELS_FILE)) {
    try {
        const data = fs.readFileSync(ALLOWED_CHANNELS_FILE, "utf-8");
        allowedChannels = JSON.parse(data);
    } catch (error) {
        console.error("Erreur lors du chargement des salons autorisés:", error);
        allowedChannels = [];
    }
}

function saveAllowedChannels() {
    fs.writeFileSync(
        ALLOWED_CHANNELS_FILE,
        JSON.stringify(allowedChannels, null, 2)
    );
}

// Fonction pour sauvegarder l'historique des messages dans le fichier JSON
function saveMessageHistory() {
    fs.writeFileSync(
        MESSAGE_HISTORY_FILE,
        JSON.stringify(messageHistory, null, 2)
    );
}

client.once("ready", () => {
    console.log(`Bot connecté en tant que ${client.user.tag}`);
    saveMessageHistory();
    const { REST, Routes } = require("discord.js");

    const commands = [
        {
            name: "reset-history",
            description: "Supprime l'historique des messages du salon actuel",
        },
        {
            name: "add-channel",
            description: "Autorise ce salon à utiliser le bot",
            default_member_permissions: "8",
        },
    ];

    const rest = new REST({ version: "10" }).setToken(process.env.DISCORD_TOKEN);

    (async () => {
        try {
            console.log("⏳ Mise à jour des commandes slash...");
            await rest.put(Routes.applicationCommands(client.user.id), {
                body: commands,
            });
            console.log("✅ Commandes enregistrées avec succès !");
        } catch (error) {
            console.error("❌ Erreur lors de l'enregistrement des commandes:", error);
        }
    })();
});

client.on("interactionCreate", async (interaction) => {
    if (!interaction.isCommand()) return;

    if (interaction.commandName === "add-channel") {
        await interaction.deferReply({ ephemeral: true });

        if (!interaction.member.permissions.has("Administrator")) {
            await interaction.editReply(
                "❌ Vous devez être administrateur pour utiliser cette commande !"
            );
            return;
        }

        if (!allowedChannels.includes(interaction.channelId)) {
            allowedChannels.push(interaction.channelId);
            saveAllowedChannels();
            await interaction.editReply(
                "✅ Je peux maintenant répondre dans ce salon !"
            );
        } else {
            await interaction.editReply("Ce salon est déjà autorisé ;)");
        }
    }

    if (interaction.commandName === "reset-history") {
        console.log("Commande /reset-history reçue");
        if (messageHistory[interaction.channelId]) {
            messageHistory[interaction.channelId] = [];
            saveMessageHistory();
            await interaction.reply(
                "🗑️ Historique des messages réinitialisé avec succès !"
            );
        } else {
            await interaction.reply("⚠️ Aucun historique à supprimer dans ce salon.");
        }
    }
});

const messageQueue = [];
let isProcessingQueue = false;
let currentMessageId = null;
let typingInterval = null;
let currentController = null;

async function processQueue() {
    if (isProcessingQueue) return;
    isProcessingQueue = true;

    while (messageQueue.length > 0) {
        const message = messageQueue.shift();
        currentMessageId = message.id;
        const userMessage = message.content;
        const userName = message.author.username;

        if (!messageHistory[message.channel.id]) {
            messageHistory[message.channel.id] = [];
        }

        const channelHistory = messageHistory[message.channel.id];
        channelHistory.push({ username: userName, message: userMessage });

        if (channelHistory.length > 20) {
            channelHistory.shift();
        }

        saveMessageHistory();

        if (message.mentions.has(client.user)) {
            currentController = new AbortController();

            try {
                const fetchedMessage = await message.channel.messages.fetch(message.id);
                if (!fetchedMessage) {
                    console.log(
                        "Le message a été supprimé avant que le bot ne puisse répondre."
                    );
                    break;
                }
                const context = `Contexte facultatif (messages précédents) :\n${channelHistory
                    .slice(0, -1)
                    .map((entry) => `${entry.username} a dit : ${entry.message}`)
                    .join(
                        "\n"
                    )}\n\nDernier message (à prendre en compte) :\n${userName} a dit : ${userMessage}`;

                console.log("Question de l'utilisateur:", context);

                const response = await axios.post(
                    DEEPSEEK_API_URL,
                    {
                        model: "deepseek-chat",
                        messages: [
                            { role: "system", content: CUSTOM_PROMPT },
                            { role: "user", content: context },
                        ],
                    },
                    {
                        signal: currentController.signal,
                        headers: {
                            Authorization: `Bearer ${DEEPSEEK_API_KEY}`,
                            "Content-Type": "application/json",
                        },
                        timeout: 30000,
                    }
                );

                if (response.status < 200 || response.status >= 300) {
                    console.error(
                        `DeepSeek a peut-être planté: statut de la réponse = ${response.status}`
                    );
                    await message.reply(
                        "Désolé, le service semble indisponible pour le moment. Réessaie plus tard."
                    );
                    break;
                }

                if (!response.data.choices || response.data.choices.length === 0) {
                    console.error(
                        "Réponse vide ou mal formattée de l'API DeepSeek:",
                        response.data
                    );
                    await message.reply(
                        "Désolé, je n'ai pas pu générer de réponse. Réessaie plus tard."
                    );
                    break;
                }

                const botResponse =
                    response.data.choices[0]?.message?.content ||
                    "Désolé, je ne peux pas répondre pour l'instant.";
                console.log("Réponse de l'API DeepSeek:", botResponse);
                await message.reply(botResponse);

                // Ajouter la réponse du bot à l'historique des messages
                channelHistory.push({
                    username: client.user.username,
                    message: botResponse,
                });

                if (channelHistory.length > 20) {
                    channelHistory.shift();
                }
                saveMessageHistory();

            } catch (error) {
                if (error.code === "ECONNRESET") {
                    console.error("Connexion interrompue par le serveur.");
                    clearInterval(typingInterval);
                    message.retryCount = (message.retryCount || 0) + 1;
                    if (message.retryCount < 3) {
                        messageQueue.unshift(message);
                        isProcessingQueue = false;
                        processQueue();
                        return;
                    } else {
                        await message.reply(
                            "Impossible de se connecter au serveur après plusieurs tentatives."
                        );
                        break;
                    }
                }
                console.error("Erreur lors de la requête à l'API DeepSeek:", error);
                break;
            }
            clearInterval(typingInterval);
        }
    }
    isProcessingQueue = false;
    currentMessageId = null;
}

client.on("messageCreate", async (message) => {
    if (message.author.bot) return;
    if (!allowedChannels.includes(message.channel.id)) return;
    console.log(`Message reçu de ${message.author.username}: ${message.content}`);

    if (message.mentions.has(client.user)) {
        message.channel.sendTyping();
    }

    messageQueue.push(message);
    await processQueue();
});

client.on("messageUpdate", (oldMessage, newMessage) => {
    if (!allowedChannels.includes(oldMessage.channel.id)) return;
    // Si le message est déjà dans la file, on le met à jour pour la prochaine requête
    const queueIndex = messageQueue.findIndex((msg) => msg.id === oldMessage.id);
    if (queueIndex !== -1) {
        messageQueue[queueIndex] = newMessage;
    }
    // Si on traite le message en cours et qu'il change, on arrête et on relance avec la nouvelle version
    if (isProcessingQueue && oldMessage.id === currentMessageId) {
        console.log(
            "Le message en cours de traitement a été mis à jour. Annulation de la requête."
        );
        currentController.abort();
        clearInterval(typingInterval);
        // ...arrêter proprement la requête en cours...
        isProcessingQueue = false;
        messageQueue.unshift(newMessage);
        processQueue(); // Relance la requête
    }
});

client.on("messageDelete", (deletedMessage) => {
    if (!allowedChannels.includes(deletedMessage.channel.id)) return;
    // Si le message est dans la file, on le retire
    const queueIndex = messageQueue.findIndex(
        (msg) => msg.id === deletedMessage.id
    );
    if (queueIndex !== -1) {
        messageQueue.splice(queueIndex, 1);
    }
    // Si on traite ce message en cours, on arrête
    if (isProcessingQueue && deletedMessage.id === currentMessageId) {
        console.log(
            "Le message en cours de traitement a été supprimé. Annulation."
        );
        currentController.abort();
        clearInterval(typingInterval);
        isProcessingQueue = false;
    }
});

client.on("error", (error) => {
    console.error("Erreur de connexion:", error);
});

client.login(process.env.DISCORD_TOKEN);
