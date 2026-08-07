## Source: Shortcut

Work items are Shortcut **stories**. Prefer the Shortcut MCP tools when the
session has them (`mcp__shortcut__stories-search`, `stories-get-by-id`, …) —
no shell or token handling needed. Fallback: the REST API
(`https://api.app.shortcut.com/api/v3`). The API token is in `$SHORTCUT_API_TOKEN`,
else `~/.config/shortcut-cli/config.json` (`token` field); send it as the
`Shortcut-Token` header. Verify exact field names/ids against API responses — do
not assume them.

### Read one story

`GET /api/v3/stories/{id}` returns the full story, including its `name`,
`description`, `labels`, and `workflow_state_id`.

### Linking to code

Stories live in Shortcut; code and pull requests live in your git host. A PR that
implements a story carries the story `app_url` (and id) in its body — that link is
how you tell which story a PR refers to.
