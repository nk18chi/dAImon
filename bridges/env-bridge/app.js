import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { App, LogLevel } from '@slack/bolt';
import { config } from 'dotenv';
import { ASK_CHANNELS } from './lib/ask-channels.js';
import { startOutbox } from './lib/outbox.js';
import { registerListeners } from './listeners/index.js';

config();

// Setup gate: the manifest is generated per-instance and untracked, so a
// fresh clone can't start (or register a misnamed app) before setup ran.
if (!existsSync(join(dirname(fileURLToPath(import.meta.url)), 'manifest.json'))) {
  console.error('manifest.json missing — run `npm run setup` (or `npm run manifest`) first.');
  process.exit(1);
}

/** Initialization */
const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  socketMode: true,
  appToken: process.env.SLACK_APP_TOKEN,
  logLevel: LogLevel.DEBUG,
  clientOptions: {
    slackApiUrl: process.env.SLACK_API_URL,
  },
});

/** Register Listeners */
registerListeners(app);

/** Start the Bolt App */
(async () => {
  try {
    await app.start();
    startOutbox(app.client, ASK_CHANNELS, app.logger);
    app.logger.info('⚡️ Bolt app is running!');
  } catch (error) {
    app.logger.error('Failed to start the app', error);
  }
})();
