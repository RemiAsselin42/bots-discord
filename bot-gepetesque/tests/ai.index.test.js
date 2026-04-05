const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// ─── DB isolée ───────────────────────────────────────────────────────────────

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "deepseek-ai-test-"));
process.env.BOT_DB_PATH = path.join(tempDir, "bot.test.db");

// ─── Mock axios (doit être configuré AVANT require("ai.js")) ────────────────
// On remplace le module axios dans le cache de Node pour que ai.js reçoive
// notre faux objet. L'implémentation de post() est changeable via _axiosPostImpl.

const Module = require("node:module");
const originalLoad = Module._load;

let _axiosPostImpl = async () => {
    throw new Error("axiosMock: aucune implémentation configurée pour ce test");
};

const _axiosMock = {
    post: (...args) => _axiosPostImpl(...args),
};

Module._load = function (request, _parent, _isMain) {
    if (request === "axios") return _axiosMock;
    return originalLoad.apply(this, arguments);
};

// ─── Chargement des modules après le mock ────────────────────────────────────

const db = require("../src/data/db");
const { indexTopicsWithAI, resolveTopicsWithAI } = require("../src/services/ai");

// ─── Helpers ──────────────────────────────────────────────────────────────────

function uid(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function makeDeepSeekResponse(content) {
    return { data: { choices: [{ message: { content } }] } };
}

test.before(async () => {
    await db.init();
});

test.after(() => {
    Module._load = originalLoad;
    fs.rmSync(tempDir, { recursive: true, force: true });
});

// ─── indexTopicsWithAI ────────────────────────────────────────────────────────

test("indexTopicsWithAI persiste les faits extraits par l'IA", async () => {
    const userId = uid("u");
    const guildId = uid("g");

    _axiosPostImpl = async () =>
        makeDeepSeekResponse(
            '{"topics": [{"key": "prénom", "value": "Alice"}, {"key": "ville", "value": "Lyon"}]}'
        );

    await indexTopicsWithAI(userId, guildId, "Je m'appelle Alice, j'habite à Lyon", "Super !");

    const facts = db.getUserFacts(userId, guildId);
    const keys = facts.map((f) => f.key);

    assert.ok(keys.includes("prénom"), "La clé 'prénom' doit être indexée");
    assert.ok(keys.includes("ville"), "La clé 'ville' doit être indexée");

    const prenom = facts.find((f) => f.key === "prénom");
    assert.equal(prenom.value, "Alice");
});

test("indexTopicsWithAI ignore les topics avec clé vide ou trop longue", async () => {
    const userId = uid("u");
    const guildId = uid("g");

    _axiosPostImpl = async () =>
        makeDeepSeekResponse(
            '{"topics": [' +
            '{"key": "", "value": "oublie-moi"},' +
            '{"key": "cette-cle-est-vraiment-beaucoup-trop-longue-pour-etre-valide", "value": "valeur"},' +
            '{"key": "surnom", "value": "Toto"}' +
            "]}"
        );

    await indexTopicsWithAI(userId, guildId, "Mon surnom c'est Toto", "Ok !");

    const facts = db.getUserFacts(userId, guildId);
    const keys = facts.map((f) => f.key);

    assert.ok(!keys.includes(""), "Les clés vides ne doivent pas être indexées");
    assert.ok(
        !keys.some((k) => k.length > 30),
        "Les clés trop longues ne doivent pas être indexées"
    );
    assert.ok(keys.includes("surnom"), "La clé 'surnom' valide doit être indexée");
});

test("indexTopicsWithAI ne crashe pas sur une réponse IA non-JSON", async () => {
    const userId = uid("u");
    const guildId = uid("g");

    _axiosPostImpl = async () =>
        makeDeepSeekResponse("Je n'ai rien à indexer.");

    await assert.doesNotReject(() =>
        indexTopicsWithAI(userId, guildId, "Bonjour", "Salut !")
    );
});

test("indexTopicsWithAI ne crashe pas si l'appel API échoue", async () => {
    const userId = uid("u");
    const guildId = uid("g");

    _axiosPostImpl = async () => {
        throw new Error("Network error");
    };

    await assert.doesNotReject(() =>
        indexTopicsWithAI(userId, guildId, "Bonjour", "Salut !")
    );
});

// ─── resolveTopicsWithAI ──────────────────────────────────────────────────────

test("resolveTopicsWithAI retourne les clés valides et filtre les hallucinations", async () => {
    _axiosPostImpl = async () =>
        makeDeepSeekResponse(
            '{"delete": ["prénom", "surnom", "cle-inventee-par-ia"]}'
        );

    const indexedKeys = ["prénom", "surnom", "ville"];
    const result = await resolveTopicsWithAI(indexedKeys, "mon identité");

    // "cle-inventee-par-ia" ne fait pas partie de indexedKeys → filtrée
    assert.deepEqual(result, ["prénom", "surnom"]);
});

test("resolveTopicsWithAI retourne [] si liste de clés vide", async () => {
    const result = await resolveTopicsWithAI([], "quelque chose");
    assert.deepEqual(result, []);
});

test("resolveTopicsWithAI retourne [] si topic vide", async () => {
    const result = await resolveTopicsWithAI(["prénom"], "");
    assert.deepEqual(result, []);
});

test("resolveTopicsWithAI retourne [] si l'IA répond sans JSON valide", async () => {
    _axiosPostImpl = async () =>
        makeDeepSeekResponse("Aucune correspondance trouvée.");

    const result = await resolveTopicsWithAI(["prénom", "ville"], "identité");
    assert.deepEqual(result, []);
});
