// Emoji status on the question itself: 👀 while it's being worked on, ✅ once
// it's answered, 🚫 when it's over the daily limit. Reactions keep threads to
// real answers. They need the reactions:write scope; without it these return
// false and the caller falls back to a message where one matters.

const ALREADY = new Set(['already_reacted', 'no_reaction']);

async function call(fn, what, logger) {
  try {
    await fn();
    return true;
  } catch (err) {
    const code = err.data?.error ?? err.message;
    if (ALREADY.has(code)) return true;
    logger?.warn(`${what} failed: ${code}`);
    return false;
  }
}

export function react(client, channel, ts, name, logger) {
  return call(() => client.reactions.add({ channel, timestamp: ts, name }), `reaction :${name}:`, logger);
}

export function unreact(client, channel, ts, name, logger) {
  return call(() => client.reactions.remove({ channel, timestamp: ts, name }), `removing :${name}:`, logger);
}
