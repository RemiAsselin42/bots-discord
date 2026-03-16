const initSqlJs = require("sql.js");
const fs = require("fs");
const path = require("path");

const DB_PATH = process.env.BOT_DB_PATH || path.join(__dirname, "bot.db");
const HISTORY_LIMIT = 20;

let db = null;

// ─── Initialisation ──────────────────────────────────────────────────────────

async function init() {
    const SQL = await initSqlJs();

    if (fs.existsSync(DB_PATH)) {
        const buffer = fs.readFileSync(DB_PATH);
        db = new SQL.Database(buffer);
    } else {
        db = new SQL.Database();
    }

    db.exec(`
        CREATE TABLE IF NOT EXISTS allowed_channels (
            channel_id TEXT PRIMARY KEY,
            guild_id   TEXT,
            added_at   INTEGER DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS message_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT    NOT NULL,
            user_id    TEXT,
            username   TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_history_channel
            ON message_history(channel_id, id);

        CREATE TABLE IF NOT EXISTS user_memory (
            user_id    TEXT NOT NULL,
            guild_id   TEXT NOT NULL,
            content    TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now')),
            PRIMARY KEY (user_id, guild_id)
        );

        CREATE TABLE IF NOT EXISTS user_forget_state (
            user_id   TEXT NOT NULL,
            guild_id  TEXT NOT NULL,
            forgot_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, guild_id)
        );

        CREATE TABLE IF NOT EXISTS user_fact_index (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            guild_id   TEXT NOT NULL,
            fact_key   TEXT NOT NULL,
            fact_value TEXT NOT NULL,
            norm_key   TEXT NOT NULL,
            norm_value TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now')),
            UNIQUE(user_id, guild_id, norm_key)
        );

        CREATE TABLE IF NOT EXISTS channel_summary (
            channel_id TEXT PRIMARY KEY,
            summary    TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
    `);

    if (!tableHasColumn("message_history", "user_id")) {
        run("ALTER TABLE message_history ADD COLUMN user_id TEXT");
    }

    save();
}

function tableHasColumn(tableName, columnName) {
    const rows = queryAll(`PRAGMA table_info(${tableName})`);
    return rows.some((row) => row.name === columnName);
}

// Écrit la DB en mémoire sur le disque
function save() {
    const data = db.export();
    fs.writeFileSync(DB_PATH, Buffer.from(data));
}

// ─── Helpers de requête ───────────────────────────────────────────────────────

function queryAll(sql, params = []) {
    const stmt = db.prepare(sql);
    if (params.length) stmt.bind(params);
    const rows = [];
    while (stmt.step()) rows.push(stmt.getAsObject());
    stmt.free();
    return rows;
}

function queryOne(sql, params = []) {
    const stmt = db.prepare(sql);
    if (params.length) stmt.bind(params);
    const row = stmt.step() ? stmt.getAsObject() : null;
    stmt.free();
    return row;
}

function run(sql, params = []) {
    db.run(sql, params);
}

// ─── Salons autorisés ────────────────────────────────────────────────────────

function isAllowedChannel(channelId) {
    return !!queryOne("SELECT 1 FROM allowed_channels WHERE channel_id = ?", [channelId]);
}

function addAllowedChannel(channelId, guildId) {
    if (queryOne("SELECT 1 FROM allowed_channels WHERE channel_id = ?", [channelId])) return false;
    run("INSERT INTO allowed_channels (channel_id, guild_id) VALUES (?, ?)", [channelId, guildId ?? null]);
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
        return queryAll(
            "SELECT channel_id FROM allowed_channels WHERE guild_id = ?",
            [guildId]
        ).map((r) => r.channel_id);
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
    run("INSERT INTO message_history (channel_id, user_id, username, content) VALUES (?, ?, ?, ?)", [
        channelId, userId,
        username, content,
    ]);
    save();
}

// Nombre total de messages dans un salon (pour déclencher la résumé)
function getChannelMessageCount(channelId) {
    const row = queryOne(
        "SELECT COUNT(*) as cnt FROM message_history WHERE channel_id = ?",
        [channelId]
    );
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

// ─── Mémoire long terme par utilisateur ──────────────────────────────────────

function getUserMemory(userId, guildId) {
    const row = queryOne(
        "SELECT content FROM user_memory WHERE user_id = ? AND guild_id = ?",
        [userId, guildId ?? ""]
    );
    return row ? row.content : null;
}

function setUserMemory(userId, guildId, content) {
    run(
        `INSERT INTO user_memory (user_id, guild_id, content, updated_at)
         VALUES (?, ?, ?, strftime('%s', 'now'))
         ON CONFLICT(user_id, guild_id)
         DO UPDATE SET content = excluded.content, updated_at = strftime('%s', 'now')`,
        [userId, guildId ?? "", content]
    );
    save();
}

function clearUserMemory(userId, guildId) {
    if (!queryOne("SELECT 1 FROM user_memory WHERE user_id = ? AND guild_id = ?", [userId, guildId ?? ""])) return false;
    run("DELETE FROM user_memory WHERE user_id = ? AND guild_id = ?", [userId, guildId ?? ""]);
    save();
    return true;
}

function setUserForgetCutoff(userId, guildId, unixSeconds) {
    const ts = Number(unixSeconds) || Math.floor(Date.now() / 1000);
    run(
        `INSERT INTO user_forget_state (user_id, guild_id, forgot_at)
         VALUES (?, ?, ?)
         ON CONFLICT(user_id, guild_id)
         DO UPDATE SET forgot_at = excluded.forgot_at`,
        [userId, guildId ?? "", ts]
    );
    save();
}

function getUserForgetCutoff(userId, guildId) {
    const row = queryOne(
        "SELECT forgot_at FROM user_forget_state WHERE user_id = ? AND guild_id = ?",
        [userId, guildId ?? ""]
    );
    return row ? Number(row.forgot_at) : null;
}

function getUserForgetCutoffMap(userIds, guildId) {
    const ids = [...new Set((Array.isArray(userIds) ? userIds : [])
        .map((id) => String(id || "").trim())
        .filter(Boolean))];
    if (ids.length === 0) return {};

    const placeholders = ids.map(() => "?").join(", ");
    const rows = queryAll(
        `SELECT user_id, forgot_at
         FROM user_forget_state
         WHERE guild_id = ? AND user_id IN (${placeholders})`,
        [guildId ?? "", ...ids]
    );

    const byUser = {};
    for (const row of rows) {
        byUser[row.user_id] = Number(row.forgot_at);
    }
    return byUser;
}

function escapeLikePattern(value) {
    return value
        .replace(/\\/g, "\\\\")
        .replace(/%/g, "\\%")
        .replace(/_/g, "\\_");
}

function normalizeFactText(value) {
    return String(value || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/["'`\[\](){}]/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function upsertUserFact(userId, guildId, factKey, factValue) {
    const key = String(factKey || "").trim().toLowerCase().replace(/_/g, " ").replace(/\s+/g, " ");
    const value = String(factValue || "").trim();
    if (!key || !value) return false;

    const normKey = normalizeFactText(key);
    const normValue = normalizeFactText(value);
    if (!normKey || !normValue) return false;

    run(
        `INSERT INTO user_fact_index (user_id, guild_id, fact_key, fact_value, norm_key, norm_value, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
         ON CONFLICT(user_id, guild_id, norm_key)
         DO UPDATE SET
            fact_value = excluded.fact_value,
            norm_value = excluded.norm_value,
            updated_at = strftime('%s', 'now')`,
        [userId, guildId ?? "", key, value, normKey, normValue]
    );
    save();
    return true;
}

function getUserFacts(userId, guildId) {
    return queryAll(
        `SELECT id, fact_key, fact_value
         FROM user_fact_index
         WHERE user_id = ? AND guild_id = ?
         ORDER BY fact_key ASC`,
        [userId, guildId ?? ""]
    ).map((row) => ({
        id: Number(row.id),
        key: row.fact_key,
        value: row.fact_value,
    }));
}

function searchUserFacts(userId, guildId, queryText) {
    const needle = normalizeFactText(queryText);
    const facts = getUserFacts(userId, guildId);
    if (!needle) return facts;
    return facts.filter((fact) => {
        const key = normalizeFactText(fact.key);
        const value = normalizeFactText(fact.value);
        return key.includes(needle) || value.includes(needle);
    });
}

function deleteUserFactByKey(userId, guildId, factKey) {
    const normKey = normalizeFactText(factKey);
    if (!normKey) return null;

    const row = queryOne(
        `SELECT id, fact_key, fact_value
         FROM user_fact_index
         WHERE user_id = ? AND guild_id = ? AND norm_key = ?`,
        [userId, guildId ?? "", normKey]
    );

    if (!row) return null;

    run(
        `DELETE FROM user_fact_index
         WHERE user_id = ? AND guild_id = ? AND norm_key = ?`,
        [userId, guildId ?? "", normKey]
    );
    save();

    return {
        id: Number(row.id),
        key: row.fact_key,
        value: row.fact_value,
    };
}

function clearUserFacts(userId, guildId) {
    const exists = queryOne(
        "SELECT 1 FROM user_fact_index WHERE user_id = ? AND guild_id = ?",
        [userId, guildId ?? ""]
    );
    if (!exists) return false;
    run("DELETE FROM user_fact_index WHERE user_id = ? AND guild_id = ?", [userId, guildId ?? ""]);
    save();
    return true;
}

function deleteUserFactsByTopic(userId, guildId, topic) {
    const needle = normalizeFactText(topic);
    if (!needle) return [];

    const matches = queryAll(
        `SELECT id, fact_key, fact_value
         FROM user_fact_index
         WHERE user_id = ?
           AND guild_id = ?
           AND (norm_key LIKE ? ESCAPE '\\' OR norm_value LIKE ? ESCAPE '\\')`,
        [
            userId,
            guildId ?? "",
            `%${escapeLikePattern(needle)}%`,
            `%${escapeLikePattern(needle)}%`,
        ]
    ).map((row) => ({
        id: Number(row.id),
        key: row.fact_key,
        value: row.fact_value,
    }));

    if (matches.length === 0) return [];

    run(
        `DELETE FROM user_fact_index
         WHERE user_id = ?
           AND guild_id = ?
           AND (norm_key LIKE ? ESCAPE '\\' OR norm_value LIKE ? ESCAPE '\\')`,
        [
            userId,
            guildId ?? "",
            `%${escapeLikePattern(needle)}%`,
            `%${escapeLikePattern(needle)}%`,
        ]
    );

    save();
    return matches;
}

function removeUserMemoryByKeyword(userId, guildId, keyword) {
    const memory = getUserMemory(userId, guildId);
    if (!memory) return false;

    const needle = normalizeFactText(keyword);
    if (!needle) return false;

    const lines = memory
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

    const filtered = lines.filter((line) => !normalizeFactText(line).includes(needle));
    if (filtered.length === lines.length) return false;

    if (filtered.length === 0) {
        run("DELETE FROM user_memory WHERE user_id = ? AND guild_id = ?", [
            userId,
            guildId ?? "",
        ]);
    } else {
        run(
            `UPDATE user_memory
             SET content = ?, updated_at = strftime('%s', 'now')
             WHERE user_id = ? AND guild_id = ?`,
            [filtered.join("\n"), userId, guildId ?? ""]
        );
    }

    save();
    return true;
}

function removeChannelMessagesByKeywords(channelId, userId, username, keywords) {
    const raw = Array.isArray(keywords) ? keywords : [];
    const uniqueNeedles = [...new Set(raw.map((v) => String(v || "").trim().toLowerCase()).filter(Boolean))];
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

        const after = queryOne(
            `SELECT COUNT(*) as cnt
             FROM message_history
             WHERE channel_id = ?
               AND (user_id = ? OR (user_id IS NULL AND username = ?))
               AND LOWER(content) LIKE ? ESCAPE '\\'`,
            [channelId, userId ?? null, username, `%${escaped}%`]
        );

        totalRemoved += Number(before?.cnt || 0) - Number(after?.cnt || 0);
    }

    if (totalRemoved > 0) save();
    return totalRemoved;
}

function clearGuildMemories(guildId) {
    run("DELETE FROM user_memory WHERE guild_id = ?", [guildId ?? ""]);
    run("DELETE FROM user_fact_index WHERE guild_id = ?", [guildId ?? ""]);
    run("DELETE FROM user_forget_state WHERE guild_id = ?", [guildId ?? ""]);
    save();
}

module.exports = {
    HISTORY_LIMIT,
    init,
    isAllowedChannel,
    addAllowedChannel,
    removeAllowedChannel,
    getAllowedChannels,
    getChannelHistory,
    getChannelMessageCount,
    getMessagesToSummarize,
    pruneOldMessages,
    addMessage,
    clearChannelHistory,
    getChannelSummary,
    setChannelSummary,
    clearChannelSummary,
    getUserMemory,
    setUserMemory,
    clearUserMemory,
    setUserForgetCutoff,
    getUserForgetCutoff,
    getUserForgetCutoffMap,
    upsertUserFact,
    getUserFacts,
    searchUserFacts,
    deleteUserFactByKey,
    clearUserFacts,
    deleteUserFactsByTopic,
    removeUserMemoryByKeyword,
    removeChannelMessagesByKeywords,
    clearGuildMemories,
};
