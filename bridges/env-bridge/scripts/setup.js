#!/usr/bin/env node
/** Interactive first-run walkthrough: verify the toolchain, pick this
 * instance's identity, render the manifest, and print what's left.
 * Safe to re-run — it re-reads current values as defaults. */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function tryRun(cmd, args) {
  try {
    return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch {
    return null;
  }
}

function checkToolchain() {
  const results = [
    ['slack CLI', tryRun('slack', ['version'])],
    ['slack auth', tryRun('slack', ['auth', 'list'])?.split('\n')[0] ?? null],
    ['daimon CLI', tryRun('daimon', ['config', 'validate'])],
  ];
  for (const [label, detail] of results) {
    console.log(detail != null ? `  ✓ ${label}: ${detail.split('\n')[0]}` : `  ✗ ${label}: missing`);
  }
  return results.filter(([, detail]) => detail == null).map(([label]) => label);
}

function readEnv() {
  const path = join(root, '.env');
  const text = existsSync(path) ? readFileSync(path, 'utf8') : '';
  const get = (key) => text.match(new RegExp(`^${key}=(.*)$`, 'm'))?.[1];
  return { text, name: get('BRIDGE_NAME'), slash: get('BRIDGE_SLASH_COMMAND') };
}

function writeEnv(prev, name, slash) {
  const withoutOurs = prev
    .split('\n')
    .filter((l) => !/^(BRIDGE_NAME|BRIDGE_SLASH_COMMAND)=/.test(l) && l !== '')
    .join('\n');
  const ours = `BRIDGE_NAME=${name}\nBRIDGE_SLASH_COMMAND=${slash}\n`;
  writeFileSync(join(root, '.env'), withoutOurs ? `${withoutOurs}\n${ours}` : ours);
}

function ask(rl, prompt) {
  // rl.question never settles if stdin closes (EOF / piped input) — race it
  // against close so defaults apply instead of hanging the process.
  const closed = new Promise((resolve) => rl.once('close', () => resolve('')));
  return Promise.race([rl.question(prompt), closed]);
}

async function askIdentity(rl, current) {
  const name = (await ask(rl, `App/bot name [${current.name ?? 'env-bridge'}]: `)).trim();
  const slash = (await ask(rl, `Slash command, workspace-unique [${current.slash ?? '/hub'}]: `)).trim();
  const finalName = name || current.name || 'env-bridge';
  let finalSlash = slash || current.slash || '/hub';
  if (!finalSlash.startsWith('/')) finalSlash = `/${finalSlash}`;
  return { name: finalName, slash: finalSlash };
}

const missing = (console.log('Toolchain:'), checkToolchain());
if (missing.includes('slack CLI')) {
  console.error('\nInstall the Slack CLI first: https://docs.slack.dev/tools/slack-cli');
  process.exit(1);
}

const rl = createInterface({ input: process.stdin, output: process.stdout });
const current = readEnv();
const identity = await askIdentity(rl, current);
rl.close();

writeEnv(current.text, identity.name, identity.slash);
execFileSync(process.execPath, [join(root, 'scripts/generate-manifest.js')], { stdio: 'inherit' });

console.log(`
Done. Next steps:
  1. slack run            — creates + installs "${identity.name}" (pick your workspace)
  2. Invite @${identity.name} to the channels the watcher reads
  3. Store the bot token for the scripted gate:
     security add-generic-password -U -s slack-service-token -w 'xoxb-...'
${missing.length ? `\nStill missing: ${missing.join(', ')}` : ''}`);
