import { enqueueCommand } from '../lib/enqueue.js';

// Mentions in these channels are free-form questions for the slack-ask daemon;
// everywhere else they stay fixed commands for slack-commands.
const ASK_CHANNELS = new Set(
  (process.env.BRIDGE_ASK_CHANNELS ?? '')
    .split(',')
    .map((c) => c.trim())
    .filter(Boolean),
);

export async function appMention({ event, say, logger }) {
  const text = event.text.replace(/<@[^>]+>/g, '').trim();
  if (!text) return;
  const ask = ASK_CHANNELS.has(event.channel);
  const threadTs = event.thread_ts ?? event.ts;
  await enqueueCommand(
    {
      command: text,
      channel: event.channel,
      ts: event.ts,
      thread_ts: threadTs,
      user: event.user,
      via: 'mention',
    },
    logger,
    ask ? 'slack-ask' : undefined,
  );
  await say({
    thread_ts: threadTs,
    text: ask ? ':mag: looking into it…' : `:hourglass_flowing_sand: on it — \`${text}\``,
  });
}
