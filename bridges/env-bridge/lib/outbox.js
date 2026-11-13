import { promises as fs } from 'node:fs';
import path from 'node:path';
import { STATE_DIR } from './enqueue.js';
import { IMAGES_DIR, removeThreadImages } from './images.js';
import { react, unreact } from './reactions.js';

export const OUTBOX = path.join(STATE_DIR, 'outbox', 'slack-ask');
const POLL_MS = 2000;
// A file that still won't parse after this long is not mid-write; it's broken.
const UNPARSEABLE_GRACE_MS = 60_000;

async function setAside(file, suffix, reason, logger) {
  logger?.error(`outbox: ${path.basename(file)} ${reason}`);
  await fs.rename(file, `${file}.${suffix}`).catch(() => {});
}

/** Post the replies slack-ask left in its outbox, as this bot, then remove
 * them. The daemon has no Slack access of its own, so this is its only way to
 * answer — and only into a thread in one of the ask channels. */
export async function flushOutbox(client, allowedChannels, logger, dir = OUTBOX, imagesDir = IMAGES_DIR) {
  let names;
  try {
    names = await fs.readdir(dir);
  } catch {
    return;
  }
  for (const name of names.filter((n) => n.endsWith('.json'))) {
    const file = path.join(dir, name);
    let reply;
    try {
      reply = JSON.parse(await fs.readFile(file, 'utf8'));
    } catch {
      const { mtimeMs } = await fs.stat(file).catch(() => ({ mtimeMs: Date.now() }));
      if (Date.now() - mtimeMs > UNPARSEABLE_GRACE_MS) {
        await setAside(file, 'rejected', 'is not valid JSON', logger);
      }
      continue;
    }
    const { channel, thread_ts: threadTs, ts, text } = reply ?? {};
    if (!allowedChannels.has(channel) || typeof threadTs !== 'string' || typeof text !== 'string' || !text) {
      await setAside(file, 'rejected', 'needs channel (an ask channel), thread_ts and text', logger);
      continue;
    }
    try {
      await client.chat.postMessage({ channel, thread_ts: threadTs, text, unfurl_links: false });
      await fs.unlink(file);
    } catch (err) {
      await setAside(file, 'failed', `could not be posted: ${err.message}`, logger);
      continue;
    }
    // The answer is out, so the screenshots it looked at go.
    await removeThreadImages(channel, threadTs, imagesDir).catch((err) =>
      logger?.warn(`outbox: removing images for ${channel}/${threadTs} failed: ${err.message}`),
    );
    // Mark the question answered: 👀 becomes ✅.
    if (typeof ts === 'string') {
      await unreact(client, channel, ts, 'eyes', logger);
      await react(client, channel, ts, 'white_check_mark', logger);
    }
  }
}

export function startOutbox(client, allowedChannels, logger) {
  let busy = false;
  setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
      await flushOutbox(client, allowedChannels, logger);
    } finally {
      busy = false;
    }
  }, POLL_MS);
}
