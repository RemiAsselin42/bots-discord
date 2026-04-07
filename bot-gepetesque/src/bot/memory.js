// ─── Détection de mémoire en langage naturel ─────────────────────────────────

// "souviens-toi que X", "retiens que X", "n'oublie pas que X", "mémorise X"
const MEMORY_STORE_RE =
    /(?:souviens?-?toi|retiens?|n[''']oublie?\s*pas|mémorise?)\s+(?:bien\s+)?(?:que\s+)?(.+)/i;
// "oublie tout ce que tu sais sur moi", "efface ma mémoire", etc.
const MEMORY_FORGET_RE =
    /(?:oublie?|efface?|supprime?)\s+(?:tout\s+)?(?:ce\s+que\s+tu\s+sais?\s+sur\s+moi|ma\s+mémoire|mes?\s+données?|mes?\s+infos?)/i;
// "oublie mon fruit préféré", "efface ma couleur préférée", etc.
const MEMORY_FORGET_TOPIC_RE = /(?:oublie?|efface?|supprime?)\s+(?:mon|ma|mes)\s+(.+)/i;

function extractMemoryRequest(text) {
    const m = text.match(MEMORY_STORE_RE);
    return m ? m[1].trim() : null;
}

function extractForgetTopic(text) {
    const m = text.match(MEMORY_FORGET_TOPIC_RE);
    return m ? m[1].trim() : null;
}

function normalizeTopic(text) {
    return String(text || "")
        .replace(/[\[\]"]/g, " ")
        .replace(/^\s*(mon|ma|mes)\s+/i, "")
        .replace(/\s+/g, " ")
        .trim();
}

module.exports = {
    MEMORY_STORE_RE,
    MEMORY_FORGET_RE,
    extractMemoryRequest,
    extractForgetTopic,
    normalizeTopic,
};
