import { enqueueCommand } from '../lib/enqueue.js';

const USAGE = 'Usage: `/hub <command>` — try `help`, `standup`, `epic-status <id>`, `staging-status`, `daemon-status`.';

export async function hubCommand({ command, ack, respond, logger }) {
  await ack();
  const text = command.text.trim();
  if (!text) {
    await respond({ response_type: 'ephemeral', text: USAGE });
    return;
  }
  await enqueueCommand({ command: text, channel: command.channel_id, user: command.user_id, via: 'slash' }, logger);
  await respond({
    response_type: 'ephemeral',
    text: `:hourglass_flowing_sand: queued \`${text}\` — the reply lands in this channel shortly.`,
  });
}
