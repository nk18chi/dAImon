import { promises as fs } from 'node:fs';
import path from 'node:path';
import { STATE_DIR } from './enqueue.js';

// Screenshots attached in the threads a question brings along, downloaded so
// slack-ask can look at them. They often show emails, names and message text,
// so they're kept only until the answer is posted; a sweep removes any that a
// failed run left behind.
export const IMAGES_DIR = path.join(STATE_DIR, 'runtime', 'slack-ask-images');
export const MAX_IMAGES = 4;
export const MAX_BYTES = 5 * 1024 * 1024;
const EXT = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp' };
const SWEEP_AFTER_MS = 24 * 60 * 60 * 1000;
const SWEEP_EVERY_MS = 60 * 60 * 1000;

/** Which of a message's files to download: images of an allowed type and
 * size, at most `budget`. The rest are named in `skipped`, so the bot can ask
 * for what they show in words. */
export function chooseFiles(files, budget) {
  const take = [];
  const skipped = [];
  for (const f of files ?? []) {
    const ok = EXT[f.mimetype] && f.size <= MAX_BYTES && (f.url_private_download || f.url_private);
    if (ok && take.length < budget) take.push(f);
    else skipped.push(f.name ?? 'file');
  }
  return { take, skipped };
}

/** Download one Slack file. Without `files:read` Slack answers with an HTML
 * page, not an error, so the response type is checked. */
export async function download(file, dest, token, fetchImpl = fetch) {
  const res = await fetchImpl(file.url_private_download ?? file.url_private, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const type = res.headers.get('content-type') ?? '';
  if (!res.ok || !type.startsWith('image/')) {
    throw new Error(`got ${res.status} ${type || 'no content type'} (is files:read granted?)`);
  }
  const body = Buffer.from(await res.arrayBuffer());
  if (body.length > MAX_BYTES) throw new Error('larger than 5 MB');
  await fs.writeFile(dest, body, { mode: 0o600 });
}

/** The folder a question's images go in. Everything for one thread sits under
 * one folder, so posting that thread's answer can remove it. */
export function questionDir(channel, threadTs, mentionTs, root = IMAGES_DIR) {
  return path.join(root, `${channel}-${threadTs}`, mentionTs);
}

/** A per-question downloader: call it with each message's files, in thread
 * order; it returns `{images, files_skipped}` for that message and stops
 * downloading once the question has MAX_IMAGES. */
export function imageCollector({ dir, token, logger, fetchImpl = fetch }) {
  let left = MAX_IMAGES;
  let n = 0;
  return async (files) => {
    const { take, skipped } = chooseFiles(files, left);
    left -= take.length;
    const images = [];
    for (const f of take) {
      n += 1;
      const dest = path.join(dir, `${n}.${EXT[f.mimetype]}`);
      try {
        await fs.mkdir(dir, { recursive: true, mode: 0o700 });
        await download(f, dest, token, fetchImpl);
        images.push(dest);
      } catch (err) {
        logger?.warn(`image ${f.name ?? 'file'} not downloaded: ${err.message}`);
        skipped.push(f.name ?? 'file');
      }
    }
    const out = {};
    if (images.length) out.images = images;
    if (skipped.length) out.files_skipped = skipped;
    return out;
  };
}

/** Remove a thread's images once its answer is posted. */
export async function removeThreadImages(channel, threadTs, root = IMAGES_DIR) {
  await fs.rm(path.join(root, `${channel}-${threadTs}`), { recursive: true, force: true });
}

/** Remove thread folders untouched for a day: runs that failed before posting. */
export async function sweepImages(root = IMAGES_DIR, now = Date.now()) {
  let names;
  try {
    names = await fs.readdir(root);
  } catch {
    return;
  }
  for (const name of names) {
    const dir = path.join(root, name);
    const { mtimeMs } = await fs.stat(dir).catch(() => ({ mtimeMs: now }));
    if (now - mtimeMs > SWEEP_AFTER_MS) await fs.rm(dir, { recursive: true, force: true });
  }
}

export function startImageSweep(logger) {
  const sweep = () => sweepImages().catch((err) => logger?.warn(`image sweep failed: ${err.message}`));
  sweep();
  setInterval(sweep, SWEEP_EVERY_MS);
}
