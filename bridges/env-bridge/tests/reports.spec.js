import assert from 'node:assert/strict';
import { test } from 'node:test';
import { alreadyHandled, isNewReport } from '../lib/reports.js';

const CHANNELS = new Set(['CREPORT']);
const FORM = new Set(['AFORM']);
const is = (m, channel = 'CREPORT') => isNewReport(m, channel, CHANNELS, FORM);
const report = { app_id: 'AFORM', bot_id: 'B1', ts: '10.0', text: 'Homepage FAQ schema missing' };

test('a new top-level post by the form is a report', () => {
  assert.equal(is(report), true);
  assert.equal(is({ ...report, thread_ts: '10.0' }), true, 'a thread parent carries its own ts');
  assert.equal(is({ ...report, subtype: 'bot_message' }), true);
});

test('nothing else starts a run', () => {
  assert.equal(is({ ...report, app_id: 'AOTHER' }), false, 'another app');
  assert.equal(is({ user: 'U1', ts: '10.0', text: 'hi' }), false, 'a person');
  assert.equal(is({ ...report, thread_ts: '9.0' }), false, 'a reply in a thread');
  assert.equal(is({ ...report, subtype: 'message_changed' }), false, 'an edit');
  assert.equal(is(report, 'COTHER'), false, 'another channel');
});

test('a report this bot replied to or reacted to is already handled', () => {
  assert.equal(alreadyHandled({ reply_users: ['UBOT', 'U1'] }, 'UBOT'), true);
  assert.equal(alreadyHandled({ reactions: [{ name: 'eyes', users: ['UBOT'] }] }, 'UBOT'), true);
  assert.equal(alreadyHandled({ reply_users: ['U1'], reactions: [{ name: 'eyes', users: ['U1'] }] }, 'UBOT'), false);
  assert.equal(alreadyHandled({ reply_users: ['UBOT'] }, undefined), false);
});
