const { queryAll, queryOne, run, save, HISTORY_LIMIT, escapeLikePattern } = require("./dbCore");

// ─── Salons autorisés ────────────────────────────────────────────────────────

function isAllowedChannel(channelId) {
    return !!queryOne("SELECT 1 FROM allowed_channels WHERE channel_id = ?", [channelId]);
}

function addAllowedChannel(channelId, guildId) {
    if (queryOne("SELECT 1 FROM allowed_channels WHERE channel_id = ?", [channelId])) return false;
    run("INSERT INTO allowed_channels (channel_id, guild_id) VALUES (?, ?)", [
        channelId,
        guildId ?? null,
    ]);
    save();
    return true;
}

function removeAllowedChannel(channelId) {
    if (!queryOne("SELECT 1 FROM allowed_channels WHERE channel_id = ?", [channelId])) return false;
    run("DELETE FROM allowed_channels WHERE channel_id = ?", [channelId]);
    save();
    return true;
}

function getAllowedChannels(guildId) {
    if (guildId) {
        return queryAll("SELECT channel_id FROM allowed_channels WHERE guild_id = ?", [
            guildId,
        ]).map((r) => r.channel_id);
    }
    return queryAll("SELECT channel_id FROM allowed_channels").map((r) => r.channel_id);
}

// ─── Historique de conversation ──────────────────────────────────────────────

// Retourne les N derniers messages dans l'ordre chronologique (ancien → récent)
function getChannelHistory(channelId) {
    return queryAll(
        "SELECT user_id, username, content, created_at FROM message_history WHERE channel_id = ? ORDER BY id DESC LIMIT ?",
        [channelId, HISTORY_LIMIT]
    ).reverse();
}

function addMessage(channelId, username, content, userId = null) {
    run(
        "INSERT INTO message_history (channel_id, user_id, username, content) VALUES (?, ?, ?, ?)",
        [channelId, userId, username, content]
    );
    save();
}

// Nombre total de messages dans un salon (pour déclencher la résumé)
function getChannelMessageCount(channelId) {
    const row = queryOne("SELECT COUNT(*) as cnt FROM message_history WHERE channel_id = ?", [
        channelId,
    ]);
    return row ? Number(row.cnt) : 0;
}

// Messages qui seront compressés (tous sauf les `keepLast` derniers)
function getMessagesToSummarize(channelId, keepLast) {
    return queryAll(
        `SELECT username, content FROM message_history
         WHERE channel_id = ?
           AND id NOT IN (SELECT id FROM message_history WHERE channel_id = ? ORDER BY id DESC LIMIT ?)
         ORDER BY id ASC`,
        [channelId, channelId, keepLast]
    );
}

// Supprime les vieux messages, garde uniquement les `keepLast` derniers
function pruneOldMessages(channelId, keepLast) {
    run(
        `DELETE FROM message_history
         WHERE channel_id = ?
           AND id NOT IN (SELECT id FROM message_history WHERE channel_id = ? ORDER BY id DESC LIMIT ?)`,
        [channelId, channelId, keepLast]
    );
    save();
}

function clearChannelHistory(channelId) {
    if (!queryOne("SELECT 1 FROM message_history WHERE channel_id = ?", [channelId])) return false;
    run("DELETE FROM message_history WHERE channel_id = ?", [channelId]);
    save();
    return true;
}

// ─── Résumé de conversation par salon ───────────────────────────────────────

function getChannelSummary(channelId) {
    const row = queryOne("SELECT summary FROM channel_summary WHERE channel_id = ?", [channelId]);
    return row ? row.summary : null;
}

function setChannelSummary(channelId, summary) {
    run(
        `INSERT INTO channel_summary (channel_id, summary, updated_at)
         VALUES (?, ?, strftime('%s', 'now'))
         ON CONFLICT(channel_id)
         DO UPDATE SET summary = excluded.summary, updated_at = strftime('%s', 'now')`,
        [channelId, summary]
    );
    save();
}

function clearChannelSummary(channelId) {
    run("DELETE FROM channel_summary WHERE channel_id = ?", [channelId]);
    save();
}

// ─── Suppression de messages par mot-clé ─────────────────────────────────────

/**
 * Supprime les messages d'un salon correspondant à l'un des mots-clés fournis,
 * et retourne le nombre total de messages supprimés.
 *
 * Limitation : si deux mots-clés se chevauchent (ex. "hello" et "hello world"),
 * un message peut correspondre aux deux patterns. Il sera supprimé dès le premier
 * DELETE, mais `before.cnt` pour le second mot-clé aura déjà comptabilisé ces
 * messages comme présents. En conséquence, `totalRemoved` peut être sur-estimé
 * lorsque des mots-clés se chevauchent sémantiquement.
 *
 * Ce comportement est acceptable pour l'usage actuel (retour d'information
 * approximatif à l'utilisateur), mais ne doit pas être utilisé pour un décompte
 * exact de lignes supprimées en base.
 */
function removeChannelMessagesByKeywords(channelId, userId, username, keywords) {
    const raw = Array.isArray(keywords) ? keywords : [];
    const uniqueNeedles = [
        ...new Set(
            raw
                .map((v) =>
                    String(v || "")
                        .trim()
                        .toLowerCase()
                )
                .filter(Boolean)
        ),
    ];
    if (uniqueNeedles.length === 0) return 0;

    let totalRemoved = 0;
    for (const needle of uniqueNeedles) {
        const escaped = escapeLikePattern(needle);
        const before = queryOne(
            `SELECT COUNT(*) as cnt
             FROM message_history
             WHERE channel_id = ?
               AND (user_id = ? OR (user_id IS NULL AND username = ?))
               AND LOWER(content) LIKE ? ESCAPE '\\'`,
            [channelId, userId ?? null, username, `%${escaped}%`]
        );

        run(
            `DELETE FROM message_history
             WHERE channel_id = ?
               AND (user_id = ? OR (user_id IS NULL AND username = ?))
               AND LOWER(content) LIKE ? ESCAPE '\\'`,
            [channelId, userId ?? null, username, `%${escaped}%`]
        );

        totalRemoved += Number(before?.cnt || 0);
    }

    if (totalRemoved > 0) save();
    return totalRemoved;
}

module.exports = {
    isAllowedChannel,
    addAllowedChannel,
    removeAllowedChannel,
    getAllowedChannels,
    getChannelHistory,
    addMessage,
    getChannelMessageCount,
    getMessagesToSummarize,
    pruneOldMessages,
    clearChannelHistory,
    getChannelSummary,
    setChannelSummary,
    clearChannelSummary,
    removeChannelMessagesByKeywords,
};
