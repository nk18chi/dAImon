/** One Slack message as slack-ask sees it. Apps (the issue-report form,
 * Shortcut, this bot) are named, because what an app posted matters: a
 * Shortcut post means a story exists. Link cards keep only their title, link
 * and source — a Shortcut card's text is in its card, not in `text`. A card's
 * "Requested by <person>" line is left out: the bot never names people. */
export function threadEntry(m) {
  const entry = { user: m.user, bot: Boolean(m.bot_id), text: m.text };
  if (m.bot_id) entry.app = m.bot_profile?.name ?? m.username;
  const cards = (m.attachments ?? [])
    .map((a) => ({ title: a.title, link: a.title_link ?? a.from_url, source: a.footer ?? a.service_name }))
    .filter((c) => c.title || c.link);
  if (cards.length) entry.cards = cards;
  return entry;
}
