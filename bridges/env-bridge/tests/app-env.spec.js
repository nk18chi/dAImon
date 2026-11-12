import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

// lib/ask-channels.js and lib/enqueue.js read process.env when imported. Under
// the launchd service nothing loads .env before node starts, so .env must load
// as the first import — otherwise every ask channel is silently treated as a
// command channel and mentions go to slack-commands.
test('app.js loads .env before any other import', async () => {
  const src = await readFile(new URL('../app.js', import.meta.url), 'utf8');
  const firstImport = src.split('\n').find((line) => line.startsWith('import '));
  assert.equal(firstImport, "import 'dotenv/config';");
});
