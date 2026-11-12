import { execFile } from 'node:child_process';

// dAImon runs each daemon in a tmux session named `<namespace>-<slug>`;
// set DAIMON_NS if your config changes `core.namespace`.
const NAMESPACE = process.env.DAIMON_NS ?? 'daimon';

/** True while the daemon's agent session is up, i.e. answering a question. */
export function isRunning(slug) {
  return new Promise((resolve) => {
    execFile('tmux', ['has-session', '-t', `${NAMESPACE}-${slug}`], (err) => resolve(!err));
  });
}

/** The thread note for a new question. slack-ask answers one question per run,
 * so with others ahead it says so instead of implying work has started. */
export function ackText(ahead) {
  if (ahead <= 0) return ':mag: looking into it…';
  const qs = ahead === 1 ? '1 question' : `${ahead} questions`;
  return `:hourglass_flowing_sand: got it — ${qs} ahead of yours. I'll answer here.`;
}
