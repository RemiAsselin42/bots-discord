// axios@1.x expose ses méthodes directement en CJS mais TS voit le type ESM (module namespace).
// On normalise vers AxiosStatic via .default pour que les types soient corrects.
/** @type {import('axios').AxiosStatic} */
const axios = /** @type {any} */ (require("axios")).default ?? require("axios");
const { DEEPSEEK_API_KEY, DEEPSEEK_API_URL, SUMMARY_THRESHOLD } = require("../config");
const db = require("../data/db");

// ─── Appel générique DeepSeek ─────────────────────────────────────────────────

/**
 * @param {unknown[]} messages
 * @param {{ signal?: AbortSignal, timeout?: number }} [options]
 * @returns {Promise<import('axios').AxiosResponse>}
 */
async function callDeepSeek(messages, { signal, timeout = 30000 } = {}) {
    return axios.post(
        DEEPSEEK_API_URL,
        { model: "deepseek-chat", messages },
        {
            signal,
            headers: {
                Authorization: `Bearer ${DEEPSEEK_API_KEY}`,
                "Content-Type": "application/json",
            },
            timeout,
        }
    );
}

// ─── Résumé automatique des vieux messages ────────────────────────────────────

async function maybeSummarize(channelId) {
    const count = db.getChannelMessageCount(channelId);
    if (count <= SUMMARY_THRESHOLD) return;

    const toSummarize = db.getMessagesToSummarize(channelId, db.HISTORY_LIMIT);
    if (toSummarize.length === 0) return;

    const existing = db.getChannelSummary(channelId);
    const prompt =
        (existing ? `Résumé existant :\n${existing}\n\n` : "") +
        `Nouveaux messages à intégrer :\n` +
        toSummarize.map((m) => `${m.username} : ${m.content}`).join("\n") +
        `\n\nFais un résumé concis (5-10 lignes max) en retenant : sujets abordés, ` +
        `préférences exprimées, décisions prises, infos importantes sur les participants. ` +
        (existing ? `Fusionne avec le résumé existant. ` : "") +
        `Réponds uniquement avec le résumé, sans introduction.`;

    try {
        const response = await callDeepSeek([{ role: "user", content: prompt }]);
        const summary = response.data.choices[0]?.message?.content;
        if (summary) {
            db.setChannelSummary(channelId, summary);
            db.pruneOldMessages(channelId, db.HISTORY_LIMIT);
            console.log(
                `Résumé généré pour le salon ${channelId} (${toSummarize.length} messages compressés)`
            );
        }
    } catch (err) {
        console.error("Erreur génération résumé:", err.message);
    }
}

// ─── Indexation thématique autonome ──────────────────────────────────────────

let _pendingIndexing = 0;
const MAX_CONCURRENT_INDEXING = 2;

async function indexTopicsWithAI(userId, guildId, userMessage, botReply) {
    if (_pendingIndexing >= MAX_CONCURRENT_INDEXING) return;

    _pendingIndexing++;
    const prompt = `Message de l'utilisateur : ${userMessage}\nRéponse du bot : ${botReply}`;
    try {
        const response = await callDeepSeek(
            [
                {
                    role: "system",
                    content:
                        "Tu es un extracteur de faits sur un utilisateur Discord. " +
                        "À partir d'un échange, extrais TOUS les faits que l'utilisateur exprime sur lui-même. " +
                        "Catégories à capturer (liste non exhaustive) : " +
                        "prénom, nom, surnom, âge, genre, ville, pays, profession, études, " +
                        "hobbies, passions, goûts (musique, films, sports, nourriture...), " +
                        "situation familiale, animaux, langue préférée, " +
                        "traits de personnalité de l'utilisateur (froid, chaleureux, etc.), " +
                        "préférences de style envers le bot (ton souhaité, humour, sérieux, etc.). " +
                        'Réponds UNIQUEMENT avec un JSON valide : {"topics": [{"key": "prénom", "value": "Thomas"}, {"key": "passion", "value": "F1"}, {"key": "frère", "value": "Bastien"}, {"key": "style bot", "value": "blagueur"}]}. ' +
                        "Règles :\n" +
                        '- Clés : minuscules, mots séparés par des espaces, JAMAIS d\'underscore ("date naissance" pas "date_naissance")\n' +
                        '- Clés courtes et sans article ("prénom" pas "le prénom de")\n' +
                        '- Valeurs : données brutes, 1 à 4 mots max, PAS de phrases ("lavande" pas "odeur de la lavande", "Bastien" pas "a un frère nommé Bastien")\n' +
                        '- Relations familiales : utiliser le lien comme clé et le prénom comme valeur ("frère": "Bastien")\n' +
                        "- Un fait = une entrée distincte\n" +
                        "- N'invente rien, n'infère que ce qui est dit explicitement par l'utilisateur\n" +
                        "- key ≤ 30 chars, value ≤ 60 chars\n" +
                        'Si rien à indexer : {"topics": []}',
                },
                { role: "user", content: prompt },
            ],
            { timeout: 8000 }
        );

        const raw = response.data.choices?.[0]?.message?.content || "";
        const jsonMatch = raw.match(/\{[\s\S]*\}/);
        if (!jsonMatch) return;

        const parsed = JSON.parse(jsonMatch[0]);
        if (!Array.isArray(parsed.topics)) return;

        for (const topic of parsed.topics) {
            const key = String(topic.key || "").trim();
            const value = String(topic.value || "").trim();
            if (key && value && key.length <= 30 && value.length <= 60) {
                db.upsertUserFact(userId, guildId, key, value);
            }
        }
        // eslint-disable-next-line no-unused-vars
    } catch (_err) {
        // Fire-and-forget : on ne laisse jamais une erreur remonter
    } finally {
        _pendingIndexing--;
    }
}

// ─── Résolution sémantique des topics à oublier ───────────────────────────────

async function resolveTopicsWithAI(indexedKeys, requestedTopic) {
    if (!indexedKeys.length || !requestedTopic) return [];
    try {
        const response = await callDeepSeek(
            [
                {
                    role: "system",
                    content:
                        "Tu es un assistant de correspondance thématique. " +
                        "On te donne une liste de topics indexés et un sujet à oublier. " +
                        'Retourne les clés à supprimer en JSON : {"delete": ["key1", "key2"]}. ' +
                        'Ne retourne que les clés de la liste fournie. Si aucun match : {"delete": []}',
                },
                {
                    role: "user",
                    content:
                        `Topics indexés : ${indexedKeys.join(", ")}\n` +
                        `L'utilisateur veut oublier : "${requestedTopic}"`,
                },
            ],
            { timeout: 8000 }
        );

        const raw = response.data.choices?.[0]?.message?.content || "";
        const jsonMatch = raw.match(/\{[\s\S]*\}/);
        if (!jsonMatch) return [];

        const parsed = JSON.parse(jsonMatch[0]);
        if (!Array.isArray(parsed.delete)) return [];

        const validSet = new Set(indexedKeys);
        return parsed.delete.filter((k) => validSet.has(String(k)));
        // eslint-disable-next-line no-unused-vars
    } catch (_err) {
        return [];
    }
}

module.exports = {
    callDeepSeek,
    maybeSummarize,
    indexTopicsWithAI,
    resolveTopicsWithAI,
};
