const { queryAll, queryOne, run, save, normalizeFactText } = require("./dbCore");

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

// ─── État oubli par utilisateur ───────────────────────────────────────────────

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

// ─── Suppression par mot-clé ──────────────────────────────────────────────────

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

// ─── Nettoyage par guild ──────────────────────────────────────────────────────

function clearGuildMemories(guildId) {
    run("DELETE FROM user_memory WHERE guild_id = ?", [guildId ?? ""]);
    run("DELETE FROM user_fact_index WHERE guild_id = ?", [guildId ?? ""]);
    run("DELETE FROM user_forget_state WHERE guild_id = ?", [guildId ?? ""]);
    save();
}

module.exports = {
    getUserMemory,
    setUserMemory,
    clearUserMemory,
    setUserForgetCutoff,
    getUserForgetCutoff,
    getUserForgetCutoffMap,
    removeUserMemoryByKeyword,
    clearGuildMemories,
};
