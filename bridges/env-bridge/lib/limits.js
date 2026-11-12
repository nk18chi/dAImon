import { promises as fs } from 'node:fs';
import path from 'node:path';
import { STATE_DIR } from './enqueue.js';

// A daily cap on questions to slack-ask, so a stolen Slack session can't pull
// data or run up cost without limit. Refused questions never reach the queue,
// so they cost nothing. Counts live in the state dir, so restarting the bridge
// doesn't reset them; the day rolls over at this machine's local midnight.
const FILE = path.join(STATE_DIR, 'runtime', 'ask-limits.json');

function positiveInt(raw, fallback) {
  const n = Number.parseInt(raw ?? '', 10);
  return n > 0 ? n : fallback;
}

export const LIMITS = {
  user: positiveInt(process.env.BRIDGE_ASK_DAILY_LIMIT, 30),
  team: positiveInt(process.env.BRIDGE_ASK_DAILY_TEAM_LIMIT, 100),
};

/** Today as YYYY-MM-DD in this machine's time zone. */
export function today(now = new Date()) {
  return now.toLocaleDateString('en-CA');
}

/** Count a question from `user`, unless today's per-person or team limit is
 * already reached. Returns the decision and the next state. When refused,
 * `reason` is 'user' or 'team', and `notify` is true only for that person's
 * first refusal of the day — a flood gets one reply, not one per message. */
export function decide(state, user, day, limits = LIMITS) {
  const fresh = state?.day !== day;
  const s = {
    day,
    team: fresh ? 0 : (state.team ?? 0),
    users: fresh ? {} : { ...state.users },
    notified: fresh ? [] : [...(state.notified ?? [])],
  };
  const used = s.users[user] ?? 0;
  const reason = used >= limits.user ? 'user' : s.team >= limits.team ? 'team' : null;
  if (!reason) {
    s.users[user] = used + 1;
    s.team += 1;
    return { allowed: true, state: s };
  }
  const notify = !s.notified.includes(user);
  if (notify) s.notified.push(user);
  return { allowed: false, reason, notify, state: s };
}

export function refusalText(reason, limits = LIMITS) {
  return reason === 'team'
    ? `:no_entry: the team has reached today's limit of ${limits.team} questions. Try again tomorrow.`
    : `:no_entry: you've reached today's limit of ${limits.user} questions. Try again tomorrow.`;
}

async function readState(file) {
  try {
    return JSON.parse(await fs.readFile(file, 'utf8'));
  } catch {
    return null;
  }
}

let chain = Promise.resolve();

/** decide() against the stored counts, saving the result. Calls run one at a
 * time: Bolt handles events concurrently, and two mentions racing on the file
 * would both read the old count. */
export function checkAndCount(user, { file = FILE, now = new Date(), limits = LIMITS } = {}) {
  const run = chain.then(async () => {
    const result = decide(await readState(file), user, today(now), limits);
    await fs.mkdir(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    await fs.writeFile(tmp, `${JSON.stringify(result.state, null, 2)}\n`);
    await fs.rename(tmp, file);
    return result;
  });
  chain = run.catch(() => {});
  return run;
}
