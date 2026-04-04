const base    = require("./dbCore");
const channel = require("./channelDb");
const memory  = require("./memoryDb");
const facts   = require("./factsDb");

module.exports = { ...base, ...channel, ...memory, ...facts };
