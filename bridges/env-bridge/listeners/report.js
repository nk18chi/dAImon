import { investigateReport, isNewReport } from '../lib/reports.js';

/** A message posted in a channel the bot is in. Only a new report from the
 * issue-report form starts anything; every other message is ignored. */
export async function reportMessage({ event, client, logger }) {
  if (!isNewReport(event, event.channel)) return;
  await investigateReport(client, event.channel, event.ts, logger);
}
