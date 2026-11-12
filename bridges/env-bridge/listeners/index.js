import { appMention } from './app-mention.js';
import { hubCommand } from './hub-command.js';

export const registerListeners = (app) => {
  app.command(process.env.BRIDGE_SLASH_COMMAND ?? '/hub', hubCommand);
  app.event('app_mention', appMention);
};
