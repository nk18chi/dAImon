import { execFile } from 'node:child_process';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const STATE_DIR = process.env.DAIMON_STATE_DIR ?? path.join(os.homedir(), '.local/state/daimon');
const INBOX = path.join(STATE_DIR, 'runtime', 'inbox.json');
const DAIMON = process.env.DAIMON_BIN ?? path.join(os.homedir(), '.local/bin/daimon');
const DEFAULT_TARGET = 'slack-commands';

async function readInbox() {
  try {
    return JSON.parse(await fs.readFile(INBOX, 'utf8'));
  } catch {
    return { messages: [] };
  }
}

/** Append a command message to the daimon inbox and nudge the daemon.
 * The inbox gate in daimon's run.sh launches immediately when a message
 * is addressed to the target daemon — this is the whole bridge. */
export async function enqueueCommand(msg, logger, target = DEFAULT_TARGET) {
  const inbox = await readInbox();
  inbox.messages = [...(inbox.messages ?? []), { to: target, ...msg }];
  await fs.mkdir(path.dirname(INBOX), { recursive: true });
  await fs.writeFile(INBOX, `${JSON.stringify(inbox, null, 2)}\n`);
  execFile(DAIMON, ['run', target], (err) => {
    if (err) logger?.error(`daimon run ${target} failed: ${err.message}`);
  });
}
