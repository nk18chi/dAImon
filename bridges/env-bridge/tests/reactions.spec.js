import assert from 'node:assert/strict';
import { test } from 'node:test';
import { react, unreact } from '../lib/reactions.js';

const slackError = (code) => Object.assign(new Error(`An API error occurred: ${code}`), { data: { error: code } });

test('adds the reaction to the question', async () => {
  const calls = [];
  const client = { reactions: { add: async (args) => calls.push(args) } };
  assert.equal(await react(client, 'C1', '1.5', 'eyes'), true);
  assert.deepEqual(calls, [{ channel: 'C1', timestamp: '1.5', name: 'eyes' }]);
});

test('an existing or already-removed reaction counts as done', async () => {
  const client = {
    reactions: {
      add: async () => {
        throw slackError('already_reacted');
      },
      remove: async () => {
        throw slackError('no_reaction');
      },
    },
  };
  assert.equal(await react(client, 'C1', '1.5', 'eyes'), true);
  assert.equal(await unreact(client, 'C1', '1.5', 'eyes'), true);
});

test('without reactions:write it reports false and logs, so the caller can fall back', async () => {
  const warnings = [];
  const client = {
    reactions: {
      add: async () => {
        throw slackError('missing_scope');
      },
    },
  };
  assert.equal(await react(client, 'C1', '1.5', 'eyes', { warn: (m) => warnings.push(m) }), false);
  assert.match(warnings[0], /missing_scope/);
});
