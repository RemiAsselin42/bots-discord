const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "bot-gepetesque-test-"));
process.env.BOT_DB_PATH = path.join(tempDir, "bot.test.db");

const db = require("../src/data/db");

function uid(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

test.before(async () => {
    await db.init();
});

test.after(() => {
    fs.rmSync(tempDir, { recursive: true, force: true });
});

test("removeUserMemoryByKeyword normalise les accents", () => {
    const userId = uid("u");
    const guildId = uid("g");

    db.setUserMemory(userId, guildId, "Mon fruit prefere est peche\nMon surnom est Pepito");

    const removed = db.removeUserMemoryByKeyword(userId, guildId, "pêche");
    const memory = db.getUserMemory(userId, guildId);

    assert.equal(removed, true);
    assert.equal(memory, "Mon surnom est Pepito");
});

test("getUserForgetCutoffMap retourne les cutoffs par utilisateur", () => {
    const guildId = uid("g");
    const user1 = uid("u1");
    const user2 = uid("u2");

    db.setUserForgetCutoff(user1, guildId, 111);
    db.setUserForgetCutoff(user2, guildId, 222);

    const result = db.getUserForgetCutoffMap([user1, user2, "inconnu"], guildId);

    assert.equal(result[user1], 111);
    assert.equal(result[user2], 222);
    assert.equal(Object.prototype.hasOwnProperty.call(result, "inconnu"), false);
});

test("removeChannelMessagesByKeywords respecte user_id et fallback legacy username", () => {
    const channelId = uid("c");
    const userId = uid("u");

    db.addMessage(channelId, "alice", "Mon surnom est Toto", userId);
    db.addMessage(channelId, "alice", "Message d un autre user", uid("other"));
    db.addMessage(channelId, "alice", "Legacy: mon surnom est Toto");

    const removed = db.removeChannelMessagesByKeywords(channelId, userId, "alice", ["surnom"]);
    const history = db.getChannelHistory(channelId);

    assert.equal(removed, 2);
    assert.equal(history.length, 1);
    assert.equal(history[0].content, "Message d un autre user");
});
