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

// ─── Helpers de normalisation ─────────────────────────────────────────────────

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

module.exports = {
    DB_PATH,
    HISTORY_LIMIT,
    init,
    save,
    tableHasColumn,
    queryAll,
    queryOne,
    run,
    escapeLikePattern,
    normalizeFactText,
};
