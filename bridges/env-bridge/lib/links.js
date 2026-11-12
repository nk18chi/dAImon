// Slack message links in a question are context the asker chose: the bridge
// reads those threads into the queued message so slack-ask sees the earlier
// discussion. Only links into the same channel count — the answer is posted
// there, so it can't carry another channel's content to a different audience.
export const MAX_LINKS = 3;

// Slack wraps links in event text as <url> or <url|label>; `&` arrives as `&amp;`.
const LINK = /<(https:\/\/(?:[\w-]+\.)*slack\.com\/archives\/([A-Z0-9]+)\/p(\d{10})(\d{6})[^\s|>]*)(?:\|[^>]*)?>/g;
const THREAD_TS = /[?&](?:amp;)?thread_ts=(\d+\.\d+)/;

/** The Slack message links in `text`, split by whether they point into
 * `channel`. Each kept link names the thread to read: the thread a reply
 * belongs to, or the message itself. Deduped, at most MAX_LINKS. */
export function messageLinks(text, channel) {
  const kept = [];
  const elsewhere = [];
  for (const [, url, linkChannel, secs, micros] of text.matchAll(LINK)) {
    if (linkChannel !== channel) {
      elsewhere.push(url);
      continue;
    }
    const threadTs = url.match(THREAD_TS)?.[1] ?? `${secs}.${micros}`;
    if (!kept.some((l) => l.threadTs === threadTs)) kept.push({ url, threadTs });
  }
  return { kept: kept.slice(0, MAX_LINKS), elsewhere };
}
