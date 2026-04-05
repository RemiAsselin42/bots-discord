const { queryAll, queryOne, run, save, normalizeFactText, escapeLikePattern } = require("./dbCore");

// ─── Index de faits utilisateur ──────────────────────────────────────────────

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

module.exports = {
    upsertUserFact,
    getUserFacts,
    searchUserFacts,
    deleteUserFactByKey,
    clearUserFacts,
    deleteUserFactsByTopic,
};
