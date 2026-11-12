import { ASK_CHANNELS } from '../lib/ask-channels.js';
import { enqueueCommand } from '../lib/enqueue.js';
import { checkAndCount, refusalText } from '../lib/limits.js';
import { ackText, isRunning } from '../lib/queue.js';

const THREAD_LIMIT = 50;

/** The thread so far, oldest first. slack-ask has no Slack access of its own,
 * so this is the only conversation it sees. */
async function readThread(client, channel, threadTs, logger) {
  try {
    const { messages = [] } = await client.conversations.replies({
      channel,
      ts: threadTs,
      limit: THREAD_LIMIT,
    });
    return messages.map((m) => ({ user: m.user, bot: Boolean(m.bot_id), text: m.text }));
  } catch (err) {
    logger?.error(`reading thread ${channel}/${threadTs} failed: ${err.message}`);
    return [];
  }
}

export async function appMention({ event, client, say, logger }) {
  const text = event.text.replace(/<@[^>]+>/g, '').trim();
  if (!text) return;
  const ask = ASK_CHANNELS.has(event.channel);
  const threadTs = event.thread_ts ?? event.ts;
  const msg = {
    command: text,
    channel: event.channel,
    ts: event.ts,
    thread_ts: threadTs,
    user: event.user,
    via: 'mention',
  };
  if (!ask) {
    await enqueueCommand(msg, logger);
    await say({ thread_ts: threadTs, text: `:hourglass_flowing_sand: on it — \`${text}\`` });
    return;
  }
  const limit = await checkAndCount(event.user ?? 'unknown');
  if (!limit.allowed) {
    logger?.warn(`ask limit: refused ${event.user} in ${event.channel} (${limit.reason} daily limit)`);
    if (limit.notify) await say({ thread_ts: threadTs, text: refusalText(limit.reason) });
    return;
  }
  msg.thread = await readThread(client, event.channel, threadTs, logger);
  // Check before enqueueing: the enqueue starts a run for this very question.
  const busy = await isRunning('slack-ask');
  const queued = await enqueueCommand(msg, logger, 'slack-ask');
  await say({ thread_ts: threadTs, text: ackText(queued - 1 + (busy ? 1 : 0)) });
}
