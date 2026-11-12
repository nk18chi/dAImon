// Mentions in these channels are free-form questions for the slack-ask daemon;
// everywhere else they stay fixed commands for slack-commands. Its replies are
// posted back only into these channels.
export const ASK_CHANNELS = new Set(
  (process.env.BRIDGE_ASK_CHANNELS ?? '')
    .split(',')
    .map((c) => c.trim())
    .filter(Boolean),
);
