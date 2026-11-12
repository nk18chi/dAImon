import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { checkAndCount, decide, refusalText } from '../lib/limits.js';

const LIMITS = { user: 2, team: 3 };
const DAY = '2026-11-12';

function ask(state, user, day = DAY) {
  return decide(state, user, day, LIMITS);
}

test('allows questions up to the per-person limit, then refuses', () => {
  let s = null;
  for (let i = 0; i < 2; i++) {
    const r = ask(s, 'U1');
    assert.equal(r.allowed, true);
    s = r.state;
  }
  const r = ask(s, 'U1');
  assert.equal(r.allowed, false);
  assert.equal(r.reason, 'user');
  assert.equal(r.state.users.U1, 2, 'a refused question is not counted');
});

test('the team limit stops everyone once reached', () => {
  let s = ask(null, 'U1').state;
  s = ask(s, 'U2').state;
  s = ask(s, 'U3').state;
  const r = ask(s, 'U4');
  assert.equal(r.allowed, false);
  assert.equal(r.reason, 'team');
});

test('replies only to the first refusal of the day per person', () => {
  let s = ask(null, 'U1').state;
  s = ask(s, 'U1').state;
  const first = ask(s, 'U1');
  assert.equal(first.notify, true);
  const second = ask(first.state, 'U1');
  assert.equal(second.allowed, false);
  assert.equal(second.notify, false);
});

test('a new day starts from zero', () => {
  let s = ask(null, 'U1').state;
  s = ask(s, 'U1').state;
  assert.equal(ask(s, 'U1').allowed, false);
  const r = ask(s, 'U1', '2026-11-13');
  assert.equal(r.allowed, true);
  assert.deepEqual(r.state, { day: '2026-11-13', team: 1, users: { U1: 1 }, notified: [] });
});

test('refusal text names the limit that was hit', () => {
  assert.match(refusalText('user', LIMITS), /you've reached today's limit of 2 questions/);
  assert.match(refusalText('team', LIMITS), /the team has reached today's limit of 3 questions/);
});

test('checkAndCount persists counts and serializes concurrent calls', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'ask-limits-'));
  const file = path.join(dir, 'runtime', 'ask-limits.json');
  const opts = { file, limits: { user: 3, team: 100 } };
  const results = await Promise.all(Array.from({ length: 5 }, () => checkAndCount('U1', opts)));
  assert.equal(results.filter((r) => r.allowed).length, 3);
  const saved = JSON.parse(await readFile(file, 'utf8'));
  assert.equal(saved.users.U1, 3);
  const later = await checkAndCount('U1', opts);
  assert.equal(later.allowed, false, 'counts survive across calls via the file');
});
