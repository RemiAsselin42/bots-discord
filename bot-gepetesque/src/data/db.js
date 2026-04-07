const base = require("./dbCore");
const channel = require("./channelDb");
const memory = require("./memoryDb");
const facts = require("./factsDb");

const { init, save, escapeLikePattern, normalizeFactText, DB_PATH, HISTORY_LIMIT } = base;
module.exports = {
    init,
    save,
    escapeLikePattern,
    normalizeFactText,
    DB_PATH,
    HISTORY_LIMIT,
    ...channel,
    ...memory,
    ...facts,
};
