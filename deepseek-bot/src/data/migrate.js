const fs = require("fs");
const path = require("path");
const db = require("./db");

function migrateJsonIfNeeded() {
    const channelsFile = path.join(__dirname, "allowedChannels.json");
    const historyFile = path.join(__dirname, "messageHistory.json");

    if (fs.existsSync(channelsFile)) {
        try {
            const channels = JSON.parse(fs.readFileSync(channelsFile, "utf-8"));
            for (const id of channels) db.addAllowedChannel(id, null);
            fs.renameSync(channelsFile, channelsFile + ".migrated");
            console.log("✅ Migration allowedChannels.json → SQLite");
        } catch (e) {
            console.error("Erreur migration allowedChannels:", e.message);
        }
    }

    if (fs.existsSync(historyFile)) {
        try {
            const history = JSON.parse(fs.readFileSync(historyFile, "utf-8"));
            for (const [channelId, messages] of Object.entries(history)) {
                for (const msg of messages) {
                    db.addMessage(channelId, msg.username, msg.message);
                }
            }
            fs.renameSync(historyFile, historyFile + ".migrated");
            console.log("✅ Migration messageHistory.json → SQLite");
        } catch (e) {
            console.error("Erreur migration messageHistory:", e.message);
        }
    }
}

module.exports = { migrateJsonIfNeeded };
