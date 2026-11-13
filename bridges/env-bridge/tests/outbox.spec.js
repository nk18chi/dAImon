import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { beforeEach, test } from 'node:test';
import { flushOutbox } from '../lib/outbox.js';

let dir;
let posted;
const client = {
  chat: {
    postMessage: async (args) => {
      if (args.channel === 'CFAIL') throw new Error('channel_not_found');
      posted.push(args);
    },
  },
};
const allowed = new Set(['CASK', 'CFAIL']);

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'outbox-'));
  posted = [];
});

const put = (name, body) =>
  fs.writeFile(path.join(dir, name), typeof body === 'string' ? body : JSON.stringify(body));

test('posts a reply into its thread and removes the file', async () => {
  await put('CASK-1.json', { channel: 'CASK', thread_ts: '1.0', text: 'hi' });
  await flushOutbox(client, allowed, null, dir);
  assert.deepEqual(posted, [{ channel: 'CASK', thread_ts: '1.0', text: 'hi', unfurl_links: false }]);
  assert.deepEqual(await fs.readdir(dir), []);
});

test('never posts outside the ask channels', async () => {
  await put('COTHER-1.json', { channel: 'COTHER', thread_ts: '1.0', text: 'hi' });
  await flushOutbox(client, allowed, null, dir);
  assert.deepEqual(posted, []);
  assert.deepEqual(await fs.readdir(dir), ['COTHER-1.json.rejected']);
});

test('rejects a reply missing its thread or text', async () => {
  await put('CASK-1.json', { channel: 'CASK', text: 'hi' });
  await put('CASK-2.json', { channel: 'CASK', thread_ts: '1.0', text: '' });
  await flushOutbox(client, allowed, null, dir);
  assert.deepEqual(posted, []);
  assert.deepEqual((await fs.readdir(dir)).sort(), ['CASK-1.json.rejected', 'CASK-2.json.rejected']);
});

test('leaves a fresh unparseable file for the next pass (it may be mid-write)', async () => {
  await put('CASK-1.json', '{"channel": "CA');
  await flushOutbox(client, allowed, null, dir);
  assert.deepEqual(await fs.readdir(dir), ['CASK-1.json']);
});

test('sets aside a reply Slack refuses, so it is not retried forever', async () => {
  await put('CFAIL-1.json', { channel: 'CFAIL', thread_ts: '1.0', text: 'hi' });
  await flushOutbox(client, allowed, null, dir);
  assert.deepEqual(await fs.readdir(dir), ['CFAIL-1.json.failed']);
});

test('ignores files that are not pending replies', async () => {
  await put('CASK-1.json.failed', { channel: 'CASK', thread_ts: '1.0', text: 'hi' });
  await flushOutbox(client, allowed, null, dir);
  assert.deepEqual(posted, []);
});

test("removes that thread's downloaded images once the answer is posted", async () => {
  const images = await fs.mkdtemp(path.join(os.tmpdir(), 'images-'));
  await fs.mkdir(path.join(images, 'CASK-1.0', '1.5'), { recursive: true });
  await fs.mkdir(path.join(images, 'CASK-2.0', '2.5'), { recursive: true });
  await put('CASK-1.json', { channel: 'CASK', thread_ts: '1.0', text: 'hi' });
  await flushOutbox(client, allowed, null, dir, images);
  assert.deepEqual(await fs.readdir(images), ['CASK-2.0'], 'only the answered thread is cleaned up');
});

test('keeps the images when the answer could not be posted', async () => {
  const images = await fs.mkdtemp(path.join(os.tmpdir(), 'images-'));
  await fs.mkdir(path.join(images, 'CFAIL-1.0'), { recursive: true });
  await put('CFAIL-1.json', { channel: 'CFAIL', thread_ts: '1.0', text: 'hi' });
  await flushOutbox(client, allowed, null, dir, images);
  assert.deepEqual(await fs.readdir(images), ['CFAIL-1.0']);
});
