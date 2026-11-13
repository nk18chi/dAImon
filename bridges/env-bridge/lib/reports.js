import path from 'node:path';
import { ASK_CHANNELS } from './ask-channels.js';
import { enqueueCommand, STATE_DIR } from './enqueue.js';
import { imageCollector, questionDir } from './images.js';
import { checkAndCount } from './limits.js';
import { react } from './reactions.js';
import { readThread } from './thread.js';

// New issue reports get a first look without anyone tagging the bot. Only a
// new top-level post by the report form (matched by its app id) starts a run,
// so people chatting in the channel can't. Reports arrive as Slack events;
// a sweep every few minutes catches the ones missed while the Mac slept.

function csv(raw) {
  return new Set(
    (raw ?? '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

// A report channel must also be an ask channel: replies are posted only there.
export const REPORT_CHANNELS = new Set([...csv(process.env.BRIDGE_REPORT_CHANNELS)].filter((c) => ASK_CHANNELS.has(c)));
export const REPORT_APP_IDS = csv(process.env.BRIDGE_REPORT_APP_ID);
const DAILY_LIMIT =
  Number.parseInt(process.env.BRIDGE_REPORT_DAILY_LIMIT ?? '', 10) > 0
    ? Number.parseInt(process.env.BRIDGE_REPORT_DAILY_LIMIT, 10)
    : 20;
const LIMIT_FILE = path.join(STATE_DIR, 'runtime', 'report-limits.json');
const SWEEP_EVERY_MS = 5 * 60 * 1000;
const SWEEP_WINDOW_S = 6 * 60 * 60;
// The sweep never reaches back before the bridge started (less a margin for a
// quick restart), so turning this on doesn't answer last week's reports.
const STARTED_S = Date.now() / 1000 - 10 * 60;

/** A new report: a top-level post by the report form in a report channel. */
export function isNewReport(m, channel, channels = REPORT_CHANNELS, appIds = REPORT_APP_IDS) {
  const topLevel = !m.thread_ts || m.thread_ts === m.ts;
  const plain = !m.subtype || m.subtype === 'bot_message';
  return channels.has(channel) && appIds.has(m.app_id) && topLevel && plain;
}

/** Already picked up: this bot replied in its thread or reacted to it. */
export function alreadyHandled(m, botUserId) {
  if (!botUserId) return false;
  const replied = (m.reply_users ?? []).includes(botUserId);
  const reacted = (m.reactions ?? []).some((r) => (r.users ?? []).includes(botUserId));
  return replied || reacted;
}

const started = new Set();

/** Queue a first look at one report. */
export async function investigateReport(client, channel, ts, logger) {
  const key = `${channel}:${ts}`;
  if (started.has(key)) return;
  started.add(key);
  const limit = await checkAndCount('report-form', {
    file: LIMIT_FILE,
    limits: { user: DAILY_LIMIT, team: DAILY_LIMIT },
  });
  if (!limit.allowed) {
    logger?.warn(`report ${key} not investigated: ${DAILY_LIMIT} automatic first looks a day reached`);
    return;
  }
  await react(client, channel, ts, 'eyes', logger);
  const collectImages = imageCollector({
    dir: questionDir(channel, ts, ts),
    token: client.token ?? process.env.SLACK_BOT_TOKEN,
    logger,
  });
  const thread = await readThread(client, channel, ts, logger, collectImages);
  await enqueueCommand({ command: '', channel, ts, thread_ts: ts, via: 'report', thread }, logger, 'slack-ask');
  logger?.info(`report ${key} queued for a first look`);
}

/** Find recent reports the bot hasn't picked up yet, and queue them. */
export async function sweepReports(client, botUserId, logger, now = Date.now() / 1000) {
  const oldest = String(Math.max(now - SWEEP_WINDOW_S, STARTED_S));
  for (const channel of REPORT_CHANNELS) {
    let messages;
    try {
      ({ messages = [] } = await client.conversations.history({ channel, oldest, limit: 100 }));
    } catch (err) {
      logger?.warn(`report sweep of ${channel} failed: ${err.data?.error ?? err.message}`);
      continue;
    }
    for (const m of messages.reverse()) {
      if (isNewReport(m, channel) && !alreadyHandled(m, botUserId))
        await investigateReport(client, channel, m.ts, logger);
    }
  }
}

export async function startReportSweep(client, logger) {
  if (!REPORT_CHANNELS.size || !REPORT_APP_IDS.size) return;
  let botUserId;
  try {
    ({ user_id: botUserId } = await client.auth.test());
  } catch (err) {
    logger?.warn(`report sweep: auth.test failed: ${err.message}`);
  }
  const sweep = () =>
    sweepReports(client, botUserId, logger).catch((err) => logger?.warn(`report sweep failed: ${err.message}`));
  sweep();
  setInterval(sweep, SWEEP_EVERY_MS);
}
