import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MAX_LINKS, messageLinks } from '../lib/links.js';

const HERE = 'C090P7YN5J7';
const link = (channel, p, query = '') => `https://acme.slack.com/archives/${channel}/p${p}${query}`;

test('a link to a top-level message reads that message thread', () => {
  const { kept } = messageLinks(`does this match <${link(HERE, '1762900000123456')}>?`, HERE);
  assert.deepEqual(kept, [{ url: link(HERE, '1762900000123456'), threadTs: '1762900000.123456' }]);
});

test('a link to a reply reads the whole thread it belongs to', () => {
  const url = link(HERE, '1762900500000200', '?thread_ts=1762900000.123456&amp;cid=C090P7YN5J7');
  const { kept } = messageLinks(`see <${url}|this reply>`, HERE);
  assert.equal(kept[0].threadTs, '1762900000.123456');
});

test('links to other channels are set aside, not read', () => {
  const { kept, elsewhere } = messageLinks(`<${link('C0OTHER0001', '1762900000123456')}>`, HERE);
  assert.deepEqual(kept, []);
  assert.equal(elsewhere.length, 1);
});

test('web links are not Slack message links', () => {
  const text = [
    '<https://example.com/p1762900000123456>',
    '<https://acme.slack.com/team/U1>',
    `<https://evil.example/slack.com/archives/${HERE}/p1762900000123456>`,
  ].join(' ');
  const { kept, elsewhere } = messageLinks(text, HERE);
  assert.deepEqual(kept, []);
  assert.deepEqual(elsewhere, []);
});

test('duplicates collapse and at most MAX_LINKS are kept', () => {
  const ps = ['1762900000000001', '1762900000000001', '1762900000000002', '1762900000000003', '1762900000000004'];
  const text = ps.map((p) => `<${link(HERE, p)}>`).join(' ');
  const { kept } = messageLinks(text, HERE);
  assert.equal(kept.length, MAX_LINKS);
  assert.deepEqual(
    kept.map((l) => l.threadTs),
    ['1762900000.000001', '1762900000.000002', '1762900000.000003'],
  );
});
