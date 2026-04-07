const { REST, Routes, MessageFlags } = require("discord.js");
const db = require("../data/db");
const { normalizeTopic } = require("./memory");
const { resolveTopicsWithAI } = require("../services/ai");

// ─── Définitions des commandes ────────────────────────────────────────────────

const COMMAND_DEFINITIONS = [
    {
        name: "reset-history",
        description: "Supprime l'historique des messages du salon actuel",
        default_member_permissions: "8",
    },
    {
        name: "forget",
        description: "Oublie une information precise te concernant",
        options: [
            {
                name: "topic",
                description: 'Sujet a oublier (ex: "mon surnom", "mon âge", etc.)',
                type: 3,
                required: true,
                autocomplete: true,
            },
        ],
    },
    {
        name: "memory-list",
        description: "Affiche les informations personnelles indexées",
    },
    {
        name: "forget-all",
        description: "Oublie tout ce que je sais sur toi",
    },
    {
        name: "add-channel",
        description: "Autorise ce salon à utiliser le bot",
        default_member_permissions: "8",
    },
    {
        name: "remove-channel",
        description: "Retire ce salon de la liste des salons autorisés",
        default_member_permissions: "8",
    },
    {
        name: "list-channels",
        description: "Liste les salons autorisés",
        default_member_permissions: "8",
    },
];

// ─── Enregistrement des commandes auprès de l'API Discord ────────────────────

async function registerCommands(client) {
    const rest = new REST({ version: "10" }).setToken(process.env.DISCORD_TOKEN);
    try {
        console.log("⏳ Mise à jour des commandes slash...");
        await rest.put(Routes.applicationCommands(client.user.id), { body: COMMAND_DEFINITIONS });
        console.log(":white_check_mark: Commandes enregistrées avec succès !");
    } catch (error) {
        console.error(":x: Erreur lors de l'enregistrement des commandes:", error);
    }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function hasAdminPermission(interaction) {
    return Boolean(interaction.memberPermissions?.has("Administrator"));
}

// ─── Handler des interactions (slash commands + autocomplete) ─────────────────

async function handleInteraction(interaction) {
    // Autocomplete
    if (interaction.isAutocomplete()) {
        if (interaction.commandName !== "forget") return;

        const userId = interaction.user.id;
        const guildId = interaction.guild?.id;
        const focused = interaction.options.getFocused(true);
        const query = focused?.name === "topic" ? String(focused.value || "") : "";
        const facts = db.searchUserFacts(userId, guildId, query).slice(0, 25);

        if (facts.length === 0) {
            await interaction.respond([
                { name: "Aucune info indexée — discutez avec le bot d'abord", value: "__none__" },
            ]);
            return;
        }

        await interaction.respond(
            facts.map((fact) => ({
                name: `${fact.key} : ${fact.value}`.slice(0, 100),
                value: fact.key.slice(0, 100),
            }))
        );
        return;
    }

    if (!interaction.isCommand()) return;

    // /add-channel
    if (interaction.commandName === "add-channel") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });
        if (!hasAdminPermission(interaction)) {
            await interaction.editReply(
                ":x: Vous devez être administrateur pour utiliser cette commande !"
            );
            return;
        }
        const added = db.addAllowedChannel(interaction.channelId, interaction.guildId);
        await interaction.editReply(
            added
                ? ":white_check_mark: Je peux maintenant répondre dans ce salon !"
                : "Ce salon est déjà autorisé ;)"
        );
    }

    // /remove-channel
    if (interaction.commandName === "remove-channel") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });
        if (!hasAdminPermission(interaction)) {
            await interaction.editReply(
                ":x: Vous devez être administrateur pour utiliser cette commande !"
            );
            return;
        }
        const removed = db.removeAllowedChannel(interaction.channelId);
        await interaction.editReply(
            removed
                ? ":white_check_mark: Ce salon a été retiré des salons autorisés."
                : ":warning: Ce salon n'est pas dans la liste des salons autorisés."
        );
    }

    // /list-channels
    if (interaction.commandName === "list-channels") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });
        if (!hasAdminPermission(interaction)) {
            await interaction.editReply(
                ":x: Vous devez être administrateur pour utiliser cette commande !"
            );
            return;
        }
        const channels = db.getAllowedChannels(interaction.guildId);
        await interaction.editReply(
            channels.length === 0
                ? "Aucun salon autorisé pour l'instant."
                : `**Salons autorisés :**\n${channels.map((id) => `<#${id}>`).join("\n")}`
        );
    }

    // /reset-history
    if (interaction.commandName === "reset-history") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });
        if (!hasAdminPermission(interaction)) {
            await interaction.editReply(
                ":x: Vous devez être administrateur pour utiliser cette commande !"
            );
            return;
        }
        console.log("Commande /reset-history reçue");
        db.clearChannelHistory(interaction.channelId);
        db.clearChannelSummary(interaction.channelId);
        db.clearGuildMemories(interaction.guildId);
        await interaction.editReply(
            "🗑️ Historique et mémoires de tous les utilisateurs réinitialisés avec succès !"
        );
    }

    // /forget
    if (interaction.commandName === "forget") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });

        const topic = interaction.options.getString("topic", true).trim();
        if (!topic || topic === "__none__") {
            await interaction.editReply(
                "ℹ️ Aucune information indexée pour l'instant. Discutez avec le bot pour qu'il apprenne des choses sur vous."
            );
            return;
        }
        const normalizedTopic = normalizeTopic(topic);

        const userId = interaction.user.id;
        const userName = interaction.user.username;
        const guildId = interaction.guild?.id;
        const channelId = interaction.channelId;

        // Passe 1 : exact match sur la clé normalisée
        let deletedFact = db.deleteUserFactByKey(userId, guildId, normalizedTopic || topic);
        let deletedFacts = deletedFact ? [deletedFact] : [];

        // Passe 2 : fallback LIKE search
        if (!deletedFact) {
            deletedFacts = db.deleteUserFactsByTopic(userId, guildId, normalizedTopic || topic);
        }

        // Passe 3 : résolution sémantique via IA
        if (deletedFacts.length === 0) {
            const allFacts = db.getUserFacts(userId, guildId);
            if (allFacts.length > 0) {
                const indexedKeys = allFacts.map((f) => f.key);
                const resolvedKeys = await resolveTopicsWithAI(
                    indexedKeys,
                    normalizedTopic || topic
                );
                for (const key of resolvedKeys) {
                    const deleted = db.deleteUserFactByKey(userId, guildId, key);
                    if (deleted) deletedFacts.push(deleted);
                }
            }
        }

        if (deletedFacts.length === 0) {
            const suggestions = db
                .searchUserFacts(userId, guildId, normalizedTopic || topic)
                .slice(0, 5)
                .map((fact) => `• ${fact.key} : ${fact.value}`)
                .join("\n");

            await interaction.editReply(
                suggestions
                    ? `:warning: Je n'ai pas trouvé ce sujet exact. Essaie un sujet indexé :\n${suggestions}`
                    : ":warning: Je n'ai pas trouvé ce sujet dans les infos indexées. Utilise /memory-list pour voir les sujets disponibles."
            );
            return;
        }

        const botUser = interaction.client.user;
        const allKeywords = deletedFacts.flatMap((f) => [f.key, f.value]);
        for (const fact of deletedFacts) {
            db.removeUserMemoryByKeyword(userId, guildId, fact.key);
        }
        db.removeChannelMessagesByKeywords(channelId, userId, userName, allKeywords);
        db.removeChannelMessagesByKeywords(channelId, botUser.id, botUser.username, allKeywords);
        db.clearChannelSummary(channelId);

        const deletedLabel = deletedFacts.map((f) => f.key).join(", ");
        await interaction.editReply(`:white_check_mark: C'est oublié pour "${deletedLabel}".`);
    }

    // /memory-list
    if (interaction.commandName === "memory-list") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });

        const userId = interaction.user.id;
        const guildId = interaction.guild?.id;
        const facts = db.getUserFacts(userId, guildId);
        const freeMemory = db.getUserMemory(userId, guildId);

        if (facts.length === 0 && !freeMemory) {
            await interaction.editReply(
                "ℹ️ Aucune information personnelle indexée pour le moment."
            );
            return;
        }

        const parts = [];
        if (facts.length > 0) {
            const lines = facts.slice(0, 25).map((fact) => `• ${fact.key} : ${fact.value}`);
            parts.push(`🧠 Voici ce que je sais sur toi :\n${lines.join("\n")}`);
        }
        if (freeMemory) {
            const truncated =
                freeMemory.length > 800 ? freeMemory.slice(0, 800) + "\n…(tronqué)" : freeMemory;
            parts.push(`📝 Notes libres :\n${truncated}`);
        }

        await interaction.editReply(parts.join("\n\n"));
    }

    // /forget-all
    if (interaction.commandName === "forget-all") {
        await interaction.deferReply({ flags: MessageFlags.Ephemeral });

        const userId = interaction.user.id;
        const guildId = interaction.guild?.id;
        const removed = db.clearUserMemory(userId, guildId);
        const removedFacts = db.clearUserFacts(userId, guildId);
        db.setUserForgetCutoff(userId, guildId, Math.floor(Date.now() / 1000));
        db.clearChannelSummary(interaction.channelId);

        await interaction.editReply(
            removed || removedFacts
                ? ":white_check_mark: C'est effacé, je ne me souviens plus de rien sur toi."
                : "ℹ️ Je n'avais pas d'information personnelle en mémoire sur toi."
        );
    }
}

module.exports = { registerCommands, handleInteraction };
