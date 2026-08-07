## Source: Datadog

Observability data is in **Datadog**. **Prefer the Datadog MCP tools when the
session has them** (`mcp__datadog-mcp__*`: `search_datadog_logs`,
`analyze_datadog_logs`, `aggregate_events`, `search_datadog_spans`,
`get_datadog_trace`, …) — no shell, no credential handling, and they support
richer enrichment (occurrence trends, companion events, traces) than a raw log
dump. Fallback: the `pup` CLI, which authenticates from `$HOME` (run
`pup auth login` once) or from `DD_API_KEY`/`DD_APP_KEY`; site comes from
`DD_SITE` (`{{inputs.dd_site}}`). Prefer `--output json` and parse the `data`
array — verify field names against a real response, do not assume them.

### Search logs

```bash
pup logs search --query="{{inputs.log_query}}" --from="{{inputs.lookback}}" --output json
```

The query is Datadog log-search syntax (`status:error service:web env:prod`, with
`-` to negate). Each event carries a timestamp, `status`, `service`, `message`,
and `attributes` (often including an error `type`, `stack`, and a source
location). `--from` takes a relative window (`30m`, `1h`).

### Clustering

Many log events are repeats of the same underlying error. Group them into
**clusters** by a stable signature — normalize the message (strip ids, uuids,
timestamps, numbers) and combine it with `service` and the error `type` / top
stack frame. One cluster = one root cause, however many occurrences it has.
