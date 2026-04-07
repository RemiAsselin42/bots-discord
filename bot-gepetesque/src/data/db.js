const base = require("./dbCore");
const channel = require("./channelDb");
const memory = require("./memoryDb");
const facts = require("./factsDb");

const { init, save, escapeLikePattern, normalizeFactText, DB_PATH } = base;
module.exports = {
    init,
    save,
    escapeLikePattern,
    normalizeFactText,
    DB_PATH,
    ...channel,
    ...memory,
    ...facts,
};
