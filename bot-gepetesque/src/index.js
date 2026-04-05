require("dotenv").config();
const express = require("express");
const { Client, GatewayIntentBits } = require("discord.js");
const db = require("./data/db");
const { migrateJsonIfNeeded } = require("./data/migrate");
const { registerCommands, handleInteraction } = require("./bot/commands");
const { enqueue, handleMessageUpdate, handleMessageDelete } = require("./bot/queue");

// ─── Serveur HTTP keepalive ───────────────────────────────────────────────────

const app = express();
const PORT = process.env.PORT || 3000;
app.get("/", (_req, res) => res.send("Bot is alive!"));
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));

// ─── Client Discord ───────────────────────────────────────────────────────────

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers,
        GatewayIntentBits.GuildMessageReactions,
    ],
});

// ─── Événements ───────────────────────────────────────────────────────────────

client.once("ready", () => {
    console.log(`Bot connecté en tant que ${client.user.tag}`);
    registerCommands(client);
});

client.on("interactionCreate", handleInteraction);

client.on("messageCreate", async (message) => {
    if (message.author.bot) return;
    if (!db.isAllowedChannel(message.channel.id)) return;
    console.log(`Message reçu de ${message.author.username}: ${message.content}`);
    await enqueue(message);
});

client.on("messageUpdate", (oldMessage, newMessage) => {
    if (!db.isAllowedChannel(oldMessage.channel.id)) return;
    handleMessageUpdate(oldMessage, newMessage);
});

client.on("messageDelete", (deletedMessage) => {
    if (!db.isAllowedChannel(deletedMessage.channel.id)) return;
    handleMessageDelete(deletedMessage);
});

client.on("error", (error) => {
    console.error("Erreur de connexion:", error);
});

// ─── Démarrage ────────────────────────────────────────────────────────────────

(async () => {
    await db.init();
    migrateJsonIfNeeded();
    client.login(process.env.DISCORD_TOKEN);
})();
