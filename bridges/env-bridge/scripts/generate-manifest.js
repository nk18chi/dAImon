#!/usr/bin/env node
/** Render manifest.json from manifest.template.json using the same .env the
 * runtime reads — BRIDGE_NAME names the app and bot (make it yours, e.g.
 * "hub-jesse"); BRIDGE_SLASH_COMMAND must be workspace-unique. Run before
 * the first `slack run`. */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { config } from 'dotenv';

config();

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const vars = {
  BRIDGE_NAME: process.env.BRIDGE_NAME ?? 'env-bridge',
  BRIDGE_SLASH_COMMAND: process.env.BRIDGE_SLASH_COMMAND ?? '/hub',
};

const template = readFileSync(join(root, 'manifest.template.json'), 'utf8');
const rendered = template.replace(/\{\{(\w+)\}\}/g, (_, name) => {
  if (!(name in vars)) throw new Error(`unknown template variable: ${name}`);
  return vars[name];
});

writeFileSync(join(root, 'manifest.json'), rendered);
console.log(`manifest.json: name=${vars.BRIDGE_NAME} slash=${vars.BRIDGE_SLASH_COMMAND}`);
