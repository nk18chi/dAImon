import { ASK_CHANNELS } from '../lib/ask-channels.js';
import { enqueueCommand } from '../lib/enqueue.js';
import { imageCollector, questionDir } from '../lib/images.js';
import { checkAndCount, refusalText } from '../lib/limits.js';
import { messageLinks } from '../lib/links.js';
import { ackText, isRunning } from '../lib/queue.js';
import { threadEntry } from '../lib/thread-entry.js';

const THREAD_LIMIT = 50;

/** The thread so far, oldest first. slack-ask has no Slack access of its own,
 * so this is the only conversation it sees. Images attached to its messages
 * are downloaded through `collectImages`, which caps them per question. */
async function readThread(client, channel, threadTs, logger, collectImages) {
  let messages;
  try {
    ({ messages = [] } = await client.conversations.replies({ channel, ts: threadTs, limit: THREAD_LIMIT }));
  } catch (err) {
    logger?.error(`reading thread ${channel}/${threadTs} failed: ${err.message}`);
    return [];
  }
  const entries = [];
  for (const m of messages) {
    const entry = threadEntry(m);
    if (m.files?.length) Object.assign(entry, await collectImages(m.files));
    entries.push(entry);
  }
  return entries;
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
  const collectImages = imageCollector({
    dir: questionDir(event.channel, threadTs, event.ts),
    token: client.token ?? process.env.SLACK_BOT_TOKEN,
    logger,
  });
  msg.thread = await readThread(client, event.channel, threadTs, logger, collectImages);
  const links = messageLinks(event.text, event.channel);
  if (links.elsewhere.length) logger?.info(`ignored ${links.elsewhere.length} link(s) to other channels`);
  const linked = links.kept.filter((l) => l.threadTs !== threadTs);
  if (linked.length) {
    // One at a time, so the asker's own thread gets the image budget first.
    msg.linked = [];
    for (const l of linked) {
      msg.linked.push({
        url: l.url,
        thread: await readThread(client, event.channel, l.threadTs, logger, collectImages),
      });
    }
  }
  // Check before enqueueing: the enqueue starts a run for this very question.
  const busy = await isRunning('slack-ask');
  const queued = await enqueueCommand(msg, logger, 'slack-ask');
  await say({ thread_ts: threadTs, text: ackText(queued - 1 + (busy ? 1 : 0)) });
}
