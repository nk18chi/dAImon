import { ASK_CHANNELS } from '../lib/ask-channels.js';
import { enqueueCommand } from '../lib/enqueue.js';
import { imageCollector, questionDir } from '../lib/images.js';
import { checkAndCount, refusalText } from '../lib/limits.js';
import { messageLinks } from '../lib/links.js';
import { ackText, isRunning } from '../lib/queue.js';
import { react } from '../lib/reactions.js';
import { readThread } from '../lib/thread.js';

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
    await react(client, event.channel, event.ts, 'no_entry', logger);
    if (limit.notify) await say({ thread_ts: threadTs, text: refusalText(limit.reason) });
    return;
  }
  // Seen, right away: reading the thread and its images can take a few seconds.
  const seen = await react(client, event.channel, event.ts, 'eyes', logger);
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
  const ahead = queued - 1 + (busy ? 1 : 0);
  // 👀 says "on it"; a message is only worth posting when it adds something —
  // how many are ahead — or when the reaction couldn't be added.
  if (ahead > 0 || !seen) await say({ thread_ts: threadTs, text: ackText(ahead) });
}
