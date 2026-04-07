module.exports = {
    apps: [
        {
            name: 'discord-bot',
            script: 'src/index.js',
            watch: true,
            ignore_watch: ['node_modules', 'src/data/bot.db', '*.json', '*.migrated'],
            env: {
                NODE_ENV: 'development',
                DISCORD_TOKEN: process.env.DISCORD_TOKEN,
                DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY
            },
            env_production: {
                NODE_ENV: 'production'
            }
        }
    ]
};
