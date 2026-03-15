const initSqlJs = require("sql.js");
const fs = require("fs");
const path = require("path");

const DB_PATH = path.join(__dirname, "bot.db");
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

        CREATE TABLE IF NOT EXISTS channel_summary (
            channel_id TEXT PRIMARY KEY,
            summary    TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
    `);

    save();
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
        "SELECT username, content FROM message_history WHERE channel_id = ? ORDER BY id DESC LIMIT ?",
        [channelId, HISTORY_LIMIT]
    ).reverse();
}

function addMessage(channelId, username, content) {
    run("INSERT INTO message_history (channel_id, username, content) VALUES (?, ?, ?)", [
        channelId, username, content,
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
};
