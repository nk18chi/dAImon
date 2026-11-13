import assert from 'node:assert/strict';
import { test } from 'node:test';
import { threadEntry } from '../lib/thread.js';

test('a person keeps user and text, with no app or cards', () => {
  assert.deepEqual(threadEntry({ user: 'U1', text: 'hi' }), { user: 'U1', bot: false, text: 'hi' });
});

test("a Shortcut post carries its story card, but not who requested it", () => {
  const entry = threadEntry({
    bot_id: 'B1',
    bot_profile: { name: 'Shortcut' },
    text: '',
    attachments: [
      {
        pretext: 'Requested by Someone from <https://x.slack.com/archives/C1/p1|this message>',
        title: 'Issues if enter blank space',
        title_link: 'https://app.shortcut.com/acme/story/63118',
        footer: 'Shortcut',
        text: 'long card body',
      },
    ],
  });
  assert.deepEqual(entry, {
    user: undefined,
    bot: true,
    text: '',
    app: 'Shortcut',
    cards: [{ title: 'Issues if enter blank space', link: 'https://app.shortcut.com/acme/story/63118', source: 'Shortcut' }],
  });
  assert.doesNotMatch(JSON.stringify(entry), /Someone/);
});

test('a workflow post is named by its app', () => {
  const entry = threadEntry({ bot_id: 'B2', bot_profile: { name: 'Launch issue report form' }, text: 'report' });
  assert.equal(entry.app, 'Launch issue report form');
  assert.equal(entry.cards, undefined);
});
