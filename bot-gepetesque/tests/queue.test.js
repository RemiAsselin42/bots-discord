/**
 * Tests pour src/bot/queue.js
 *
 * Stratégie de mock : Module._load intercepte les dépendances externes avant le
 * require de queue.js. Le stub db enregistre les appels pour introspection.
 * Les modules sans effets de bord (memory, prompt, config) sont chargés normalement.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");
const originalLoad = Module._load;

// ─── Stubs mutables ───────────────────────────────────────────────────────────

let _callDeepSeekImpl = async () => ({
    status: 200,
    data: { choices: [{ message: { content: "Réponse IA de test" } }] },
});
let _maybeSummarizeImpl = async () => {};
let _indexTopicsImpl = async () => {};

// db stub : enregistre les appels pour introspection
const _dbCalls = [];
const _dbMock = {
    addMessage: (...a) => _dbCalls.push({ fn: "addMessage", args: a }),
    getChannelHistory: () => [],
    getUserMemory: () => null,
    getUserFacts: () => [],
    getChannelSummary: () => null,
    getUserForgetCutoff: () => null,
    getUserForgetCutoffMap: () => ({}),
    clearUserMemory: () => {},
    clearUserFacts: () => {},
    setUserForgetCutoff: () => {},
    clearChannelSummary: () => {},
    setUserMemory: () => {},
    deleteUserFactsByTopic: () => [],
    removeUserMemoryByKeyword: () => false,
    removeChannelMessagesByKeywords: () => 0,
};

Module._load = function (request, _parent, _isMain) {
    if (request === "../services/ai")
        return {
            callDeepSeek: (...a) => _callDeepSeekImpl(...a),
            maybeSummarize: (...a) => _maybeSummarizeImpl(...a),
            indexTopicsWithAI: (...a) => _indexTopicsImpl(...a),
        };
    if (request === "../services/webFetch")
        return { fetchWebPage: async () => ({ title: "", content: "", url: "" }) };
    if (request === "../data/db") return _dbMock;
    return originalLoad.apply(this, arguments);
};

const { enqueue, handleMessageUpdate, handleMessageDelete } = require("../src/bot/queue");

// ─── Helper ───────────────────────────────────────────────────────────────────

const BOT_USER = { id: "bot-999", username: "TestBot" };
let _msgCounter = 0;

function makeMessage({
    id,
    content = "bonjour",
    userId = "user-1",
    mentionsBot = true,
    reply,
} = {}) {
    const _id = id ?? `msg-${++_msgCounter}`;
    const msg = {
        id: _id,
        content,
        author: { id: userId, username: "TestUser" },
        guild: { id: "guild-1" },
        channel: {
            id: "chan-1",
            sendTyping: () => {},
            messages: { fetch: async () => msg },
        },
        mentions: { has: (u) => mentionsBot && u === BOT_USER },
        client: { user: BOT_USER },
        reply: reply ?? (async () => {}),
    };
    return msg;
}

test.after(() => {
    Module._load = originalLoad;
});

// ─── Tests ────────────────────────────────────────────────────────────────────

test("Message sans mention bot : addMessage appelé, callDeepSeek non appelé", async () => {
    _dbCalls.length = 0;
    let deepSeekCalled = false;
    _callDeepSeekImpl = async () => {
        deepSeekCalled = true;
        return { status: 200, data: { choices: [] } };
    };

    const msg = makeMessage({ userId: "user-no-mention", mentionsBot: false });
    await enqueue(msg);

    assert.ok(
        _dbCalls.some((c) => c.fn === "addMessage"),
        "addMessage doit être appelé"
    );
    assert.equal(deepSeekCalled, false, "callDeepSeek ne doit pas être appelé");
});

test("handleMessageUpdate remplace un message en attente dans la queue", async () => {
    _dbCalls.length = 0;
    _callDeepSeekImpl = async () => ({
        status: 200,
        data: { choices: [{ message: { content: "Réponse IA" } }] },
    });
    _maybeSummarizeImpl = async () => {};

    const msg1 = makeMessage({ userId: "user-upd-1", mentionsBot: true });
    const msg2 = makeMessage({
        id: "msg-upd-2",
        content: "Message 2 original",
        userId: "user-upd-2",
        mentionsBot: true,
    });
    const msg2Updated = makeMessage({
        id: "msg-upd-2",
        content: "Message 2 mis à jour",
        userId: "user-upd-2",
        mentionsBot: true,
    });

    // msg1 démarre le traitement (suspendu au premier await dans processMessage)
    const done = enqueue(msg1);
    enqueue(msg2); // s'ajoute à la queue pendant le traitement de msg1
    handleMessageUpdate(msg2, msg2Updated); // remplace msg2 dans la queue

    await done;

    const contents = _dbCalls.filter((c) => c.fn === "addMessage").map((c) => c.args[2]);
    assert.ok(
        contents.includes("Message 2 mis à jour"),
        `Le message mis à jour doit être enregistré ; contenus: ${JSON.stringify(contents)}`
    );
    assert.ok(!contents.includes("Message 2 original"), "L'original ne doit pas être enregistré");
});

test("handleMessageDelete retire un message en attente dans la queue", async () => {
    _dbCalls.length = 0;
    _callDeepSeekImpl = async () => ({
        status: 200,
        data: { choices: [{ message: { content: "Réponse IA" } }] },
    });

    const msg1 = makeMessage({ userId: "user-del-1", mentionsBot: true });
    const msg2 = makeMessage({
        id: "msg-del-2",
        content: "Message à supprimer",
        userId: "user-del-2",
        mentionsBot: true,
    });

    // msg1 démarre le traitement ; msg2 est ajouté puis immédiatement supprimé
    const done = enqueue(msg1);
    enqueue(msg2);
    handleMessageDelete(msg2);

    await done;

    const contents = _dbCalls.filter((c) => c.fn === "addMessage").map((c) => c.args[2]);
    assert.ok(
        !contents.includes("Message à supprimer"),
        `Le message supprimé ne doit pas être enregistré ; contenus: ${JSON.stringify(contents)}`
    );
});

test("Cooldown : 2 requêtes successives du même user → réponse cooldown sur la 2e", async () => {
    const userId = "user-cooldown";
    const replies = [];
    _callDeepSeekImpl = async () => ({
        status: 200,
        data: { choices: [{ message: { content: "Réponse IA" } }] },
    });

    const msg1 = makeMessage({ userId, mentionsBot: true });
    const msg2 = makeMessage({
        userId,
        mentionsBot: true,
        reply: async (t) => replies.push(t),
    });

    await enqueue(msg1); // traité normalement, met à jour userLastRequest
    await enqueue(msg2); // cooldown déclenché (< 10 s depuis msg1)

    assert.ok(
        replies.some((r) => r.includes("⏳")),
        `Réponse de cooldown attendue ; réponses reçues: ${JSON.stringify(replies)}`
    );
});

test("Réponse bot enregistrée en DB après appel DeepSeek réussi", async () => {
    _dbCalls.length = 0;
    const BOT_RESPONSE = "Voici ma réponse de test.";
    _callDeepSeekImpl = async () => ({
        status: 200,
        data: { choices: [{ message: { content: BOT_RESPONSE } }] },
    });

    const msg = makeMessage({ userId: "user-save-5", mentionsBot: true });
    await enqueue(msg);

    const contents = _dbCalls.filter((c) => c.fn === "addMessage").map((c) => c.args[2]);
    assert.ok(
        contents.includes(BOT_RESPONSE),
        `La réponse du bot doit être enregistrée en DB ; contenus: ${JSON.stringify(contents)}`
    );
});

test("Erreur API (status 500) → message d'erreur envoyé à l'utilisateur", async () => {
    _callDeepSeekImpl = async () => ({ status: 500, data: {} });

    const replies = [];
    const msg = makeMessage({
        userId: "user-err-6",
        mentionsBot: true,
        reply: async (t) => replies.push(t),
    });

    await enqueue(msg);

    assert.ok(
        replies.some((r) => r.toLowerCase().includes("désolé")),
        `Un message d'erreur doit être envoyé ; réponses: ${JSON.stringify(replies)}`
    );
});
