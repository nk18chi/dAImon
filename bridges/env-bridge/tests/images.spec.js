import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { chooseFiles, imageCollector, MAX_BYTES, MAX_IMAGES, questionDir, sweepImages } from '../lib/images.js';

const png = (name, extra = {}) => ({
  name,
  mimetype: 'image/png',
  size: 1000,
  url_private_download: `https://files.slack.com/${name}`,
  ...extra,
});

/** A fake fetch: image bytes for every URL, unless the URL names an HTML page. */
const fakeFetch = (calls) => async (url, opts) => {
  calls.push({ url, auth: opts.headers.Authorization });
  const html = url.includes('login');
  return {
    ok: true,
    status: 200,
    headers: { get: () => (html ? 'text/html' : 'image/png') },
    arrayBuffer: async () => new TextEncoder().encode(html ? '<html>' : 'PNGDATA').buffer,
  };
};

test('chooses images only, within type, size and budget', () => {
  const files = [
    png('a.png'),
    { ...png('b.json'), mimetype: 'application/json' },
    png('c.png', { size: MAX_BYTES + 1 }),
    { name: 'd.mp4', mimetype: 'video/mp4', size: 10 },
    png('e.png'),
    png('f.png'),
  ];
  const { take, skipped } = chooseFiles(files, 2);
  assert.deepEqual(
    take.map((f) => f.name),
    ['a.png', 'e.png'],
  );
  assert.deepEqual(skipped, ['b.json', 'c.png', 'd.mp4', 'f.png']);
});

test('downloads with the bot token and caps images per question', async () => {
  const dir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'img-')), 'q');
  const calls = [];
  const collect = imageCollector({ dir, token: 'xoxb-test', fetchImpl: fakeFetch(calls) });
  const first = await collect([png('1.png'), png('2.png'), png('3.png')]);
  const second = await collect([png('4.png'), png('5.png')]);
  assert.equal(first.images.length, 3);
  assert.deepEqual(second.images, [path.join(dir, '4.png')]);
  assert.deepEqual(second.files_skipped, ['5.png']);
  assert.equal(calls.length, MAX_IMAGES);
  assert.ok(calls.every((c) => c.auth === 'Bearer xoxb-test'));
  assert.equal(await fs.readFile(path.join(dir, '1.png'), 'utf8'), 'PNGDATA');
});

test('an HTML answer (no files:read) is skipped, not saved as an image', async () => {
  const dir = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'img-')), 'q');
  const collect = imageCollector({ dir, token: 't', fetchImpl: fakeFetch([]) });
  const out = await collect([png('login.png')]);
  assert.equal(out.images, undefined);
  assert.deepEqual(out.files_skipped, ['login.png']);
  assert.deepEqual(await fs.readdir(dir), []);
});

test("a question's folder sits under its thread's folder", () => {
  assert.equal(questionDir('C1', '1.0', '2.0', '/root'), path.join('/root', 'C1-1.0', '2.0'));
});

test('the sweep removes only thread folders older than a day', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'img-'));
  await fs.mkdir(path.join(root, 'old'));
  await fs.mkdir(path.join(root, 'new'));
  const now = Date.now();
  const twoDaysAgo = new Date(now - 2 * 24 * 60 * 60 * 1000);
  await fs.utimes(path.join(root, 'old'), twoDaysAgo, twoDaysAgo);
  await sweepImages(root, now);
  assert.deepEqual(await fs.readdir(root), ['new']);
});
