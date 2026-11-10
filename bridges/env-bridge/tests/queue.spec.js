import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ackText } from '../lib/queue.js';

test('first in line: says work has started', () => {
  assert.equal(ackText(0), ':mag: looking into it…');
});

test('others ahead: says how many instead', () => {
  assert.equal(ackText(1), ":hourglass_flowing_sand: got it — 1 question ahead of yours. I'll answer here.");
  assert.equal(ackText(3), ":hourglass_flowing_sand: got it — 3 questions ahead of yours. I'll answer here.");
});
