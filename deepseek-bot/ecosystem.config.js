module.exports = {
    apps: [
        {
            name: 'discord-bot',
            script: 'index.js',
            watch: true,
            ignore_watch: ['messageHistory.json'], // ignore ce fichier
            env: {
                NODE_ENV: 'development',
                DISCORD_TOKEN: process.env.DISCORD_TOKEN,
                DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY,
                PORT: process.env.PORT || 3000
            },
            env_production: {
                NODE_ENV: 'production'
            }
        }
    ]
};
