#!/usr/bin/env python3
"""Configure authenticated MCP servers used by daemon backends."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from config import Config

SLACK_MCP_URL = "https://mcp.slack.com/mcp"
SLACK_API_URL = "https://slack.com/api/apps.manifest.create"
SLACK_CALLBACK_PORT = 3118
SLACK_SCOPES = [
    "search:read.public",
    "search:read.private",
    "search:read.mpim",
    "search:read.im",
    "search:read.files",
    "search:read.users",
    "chat:write",
    "channels:history",
    "groups:history",
    "mpim:history",
    "im:history",
    "canvases:read",
    "canvases:write",
    "users:read",
    "users:read.email",
    "reactions:write",
    "reactions:read",
    "emoji:read",
    "files:read",
    "files:write",
    "channels:write",
    "groups:write",
    "im:write",
    "mpim:write",
    "channels:read",
    "groups:read",
    "mpim:read",
    "lists:read",
    "lists:write",
]


def codex_bin() -> str:
    return os.environ.get("DAIMON_CODEX_BIN", "codex")


def callback_id(url: str = SLACK_MCP_URL) -> str:
    digest = hashlib.sha256(url.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:12]


def callback_url() -> str:
    return f"http://127.0.0.1:{SLACK_CALLBACK_PORT}/callback/{callback_id()}"


def state_path() -> Path:
    override = os.environ.get("DAIMON_SLACK_MCP_STATE")
    if override:
        return Path(override).expanduser()
    return Config.load().state_dir / "mcp" / "slack.json"


def load_state() -> dict[str, str] | None:
    try:
        data = json.loads(state_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if data.get("client_id") and data.get("callback_url") == callback_url():
        return data
    return None


def save_state(data: dict[str, str]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".slack-", text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise


def slack_credentials() -> tuple[str, str]:
    path = Path(
        os.environ.get("DAIMON_SLACK_CREDENTIALS", "~/.slack/credentials.json")
    ).expanduser()
    try:
        credentials = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("Slack CLI is not authenticated; run: slack auth login") from exc
    team_id = os.environ.get("DAIMON_SLACK_TEAM_ID")
    if team_id:
        selected = credentials.get(team_id)
        if not selected:
            raise RuntimeError(f"Slack CLI has no credentials for team {team_id}")
    elif len(credentials) == 1:
        team_id, selected = next(iter(credentials.items()))
    else:
        teams = ", ".join(sorted(credentials))
        raise RuntimeError(
            f"Slack CLI has multiple workspaces; set DAIMON_SLACK_TEAM_ID to one of: {teams}"
        )
    token = selected.get("token")
    if not token:
        raise RuntimeError(f"Slack CLI credentials for {team_id} have no token")
    return team_id, token


def slack_manifest() -> dict:
    return {
        "_metadata": {"major_version": 1, "minor_version": 1},
        "display_information": {
            "name": "dAImon Codex",
            "description": "Let dAImon Codex fallback agents work with Slack",
            "background_color": "#1a1d21",
        },
        "oauth_config": {
            "redirect_urls": [callback_url()],
            "scopes": {"user": SLACK_SCOPES},
            "pkce_enabled": True,
        },
        "settings": {
            "is_mcp_enabled": True,
            "org_deploy_enabled": False,
            "socket_mode_enabled": False,
            "token_rotation_enabled": False,
        },
    }


def create_slack_app(token: str) -> dict:
    body = json.dumps({"manifest": slack_manifest()}).encode()
    request = urllib.request.Request(
        SLACK_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not create Slack MCP app: {exc}") from exc
    if not result.get("ok"):
        detail = result.get("error", "unknown Slack API error")
        errors = result.get("errors", [])
        if errors:
            detail += ": " + "; ".join(item.get("message", str(item)) for item in errors)
        raise RuntimeError(f"could not create Slack MCP app: {detail}")
    credentials = result.get("credentials", {})
    client_id = credentials.get("client_id")
    app_id = result.get("app_id")
    if not client_id or not app_id:
        raise RuntimeError("Slack created the app but did not return its app/client ID")
    return {"app_id": app_id, "client_id": client_id}


def get_or_create_slack_app(client_id: str | None = None) -> dict[str, str]:
    if client_id:
        state = {"client_id": client_id, "callback_url": callback_url()}
        save_state(state)
        return state
    existing = load_state()
    if existing:
        return existing
    team_id, token = slack_credentials()
    print(f"Creating a dedicated internal Slack MCP app in workspace {team_id}...")
    created = create_slack_app(token)
    state = {
        "app_id": created["app_id"],
        "client_id": created["client_id"],
        "team_id": team_id,
        "callback_url": callback_url(),
    }
    save_state(state)
    print(f"Created Slack app {state['app_id']} with callback {state['callback_url']}")
    return state


def codex_slack_configured(binary: str | None = None) -> bool:
    command = binary or codex_bin()
    try:
        result = subprocess.run(
            [command, "mcp", "get", "slack", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        return data.get("transport", {}).get("url") == SLACK_MCP_URL
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def codex_slack_authenticated(binary: str | None = None) -> bool:
    command = binary or codex_bin()
    try:
        result = subprocess.run(
            [command, "mcp", "list"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    return any(
        line.split()[0] == "slack" and line.rstrip().endswith("OAuth")
        for line in result.stdout.splitlines()
        if line.split()
    )


def setup_codex_slack(binary: str | None = None, client_id: str | None = None) -> int:
    command = binary or codex_bin()
    if shutil.which(command) is None:
        print(f"codex not found: {command}", file=sys.stderr)
        return 1
    try:
        app = get_or_create_slack_app(client_id)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    if codex_slack_configured(command):
        removed = subprocess.run([command, "mcp", "remove", "slack"], check=False)
        if removed.returncode != 0:
            return removed.returncode

    print("Authorize the dAImon Codex app in the Slack browser window that opens.")
    return subprocess.run(
        [
            command,
            "mcp",
            "add",
            "-c",
            f"mcp_oauth_callback_port={SLACK_CALLBACK_PORT}",
            "slack",
            "--url",
            SLACK_MCP_URL,
            "--oauth-client-id",
            app["client_id"],
        ],
        check=False,
    ).returncode


def main(argv: list[str]) -> int:
    if len(argv) in (2, 3) and argv[:2] == ["setup", "slack"]:
        return setup_codex_slack(client_id=argv[2] if len(argv) == 3 else None)
    if argv == ["status", "slack"]:
        if codex_slack_configured() and codex_slack_authenticated():
            print("codex Slack MCP configured and authenticated")
            return 0
        print("codex Slack MCP not authenticated", file=sys.stderr)
        return 1
    if argv == ["share", "slack"]:
        state = load_state()
        if not state:
            print("Slack MCP app not set up; run: daimon mcp setup slack", file=sys.stderr)
            return 1
        print(f"daimon mcp setup slack {state['client_id']}")
        return 0
    print(
        "usage: daimon mcp <setup|status|share> slack [client-id]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
