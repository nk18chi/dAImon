"""Per-panel content for the selected daemon, as Textual markup. Status is
conveyed by symbol + text (never colour alone)."""

import json
import re
from pathlib import Path

import state
from _lib import schedule_fmt


def _input_fmt(v) -> str:
    return ("on" if v else "off") if isinstance(v, bool) else str(v)


def render_config(cfg, slug: str) -> str:
    d = cfg.daemon(slug)
    lines = [
        f"[dim]backend [/dim] {d['backend']}",
        f"[dim]fallback[/dim] {d['fallback_backend'] or '—'}",
        f"[dim]model   [/dim] {d['model']}",
        f"[dim]source  [/dim] {d.get('source') or '—'}",
        *([f"[dim]mcp     [/dim] {', '.join(d['mcp'])}"] if d.get("mcp") else []),
        f"[dim]schedule[/dim] {schedule_fmt.display(d['schedule'])}",
        f"[dim]danger  [/dim] {'on' if d['danger'] else 'off'}",
        f"[dim]stuck   [/dim] {d['stuck_after']}s",
        f"[dim]command [/dim] {d['command']}",
        f"[dim]workdir [/dim] {d['working_dir']}",
    ]
    prov = cfg.input_provenance(slug)
    if prov["daemon"]:
        lines.append("[dim]── inputs ──────[/dim]")
        lines += [f"[dim]{k:<12}[/dim] {_input_fmt(v)}" for k, v in prov["daemon"].items()]
    for name, fields in prov["profiles"].items():
        lines.append(f"[dim]── profile: {name} ──[/dim]")
        lines += [f"[dim]{k:<12}[/dim] {_input_fmt(v)}" for k, v in fields.items()]
    # Both are machine-local and set by hand, so they belong on screen — an
    # override you forgot about is a cap that silently is not the one in
    # daemon.toml, and a skip you forgot about looks exactly like a daemon that
    # has stopped noticing a PR.
    caps = _runtime_json(cfg, slug, "round-caps")
    if caps:
        lines.append("[dim]── round caps (local override) ──[/dim]")
        lines += [f"[dim]{k:<12}[/dim] [yellow]{v}[/yellow]" for k, v in sorted(caps.items())]
    skips = _runtime_json(cfg, slug, "skips")
    if skips:
        lines.append("[dim]── skipped (local) ──[/dim]")
        lines += [f"[dim]{k:<12}[/dim] [yellow]excluded[/yellow]" for k in sorted(skips)]
    return "\n".join(lines)


def _runtime_json(cfg, slug: str, name: str) -> dict:
    """A hand-set runtime override file as a dict, or {} if absent or unreadable."""
    path = cfg.state_dir / "runtime" / f"{slug}.{name}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def render_status(cfg, slug: str) -> str:
    def mark(ok):
        return "[green]✓[/green]" if ok else "[dim]·[/dim]"

    reg = mark(state.registered(cfg, slug))
    loaded = mark(state.launchd_loaded(state.label_for(cfg, slug)))
    run = "[green]● running[/green]" if state.running_session(cfg, slug) else "[dim]— idle[/dim]"
    return f"registered {reg}   loaded {loaded}   {run}"


def render_procs(cfg, slug: str) -> str:
    procs = state.session_procs(cfg, slug)
    if not procs:
        return "[dim]— not running[/dim]"
    total = sum(rss for _, rss, _ in procs)
    rows = [
        f"[dim]{pid:>6}[/dim] {label:<7}[dim]{rss:>6.0f} MB[/dim]"
        for pid, rss, label in sorted(procs, key=lambda p: -p[1])[:6]
    ]
    return "\n".join([f"[dim]{len(procs)} procs · {total:.0f} MB total[/dim]"] + rows)


# A daemon's state file is its own shape — the framework never dictates one. These
# are the keys the shipped skills happen to use; anything unrecognised still gets a
# row, just a plainer one, rather than being hidden.
_ID_KEYS = ("number", "story_id", "id", "signature")
# Every shipped skill stamps its records, but no two agree on the key, and some
# carry two at once (review-trigger records both askedAt and lastVerified).
_TIME_KEYS = frozenset(
    ("last_seen", "askedAt", "lastVerified", "filedAt", "seenAt", "at", "date", "updatedAt")
)
# A leading ISO-8601 date, optionally with a time. Anchored and leading-only:
# the value may continue into prose, and everything after the timestamp is a
# note rather than something to sort on.
_STAMP_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})(?:[T ](?P<time>\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?))?"
)
_DONE = {"fixed", "done", "merged", "filed", "promoted"}
_DECLINED = {"wontfix", "declined", "skipped"}
# Wide enough for "(unkeyed)" whole — a clipped marker reads like a clipped id.
_LABEL_W = 9


def _read_state(cfg, slug: str) -> list | None:
    """The daemon's durable work record as a list, or None when unreadable.

    Skills write either a bare array or a single-key object wrapping one; accept
    both rather than making every skill agree on an envelope.
    """
    path = cfg.state_dir / "state" / f"{slug}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return next((v for v in data.values() if isinstance(v, list)), None)
    return None


def _item_id(rec: dict):
    for key in _ID_KEYS:
        if rec.get(key) is not None:
            return rec[key]
    return None


def _stamp(rec: dict) -> str:
    """When this record last happened, as a sortable string ("" if undated).

    The largest of whatever time keys it carries, rather than the first one
    found: a record with both askedAt and lastVerified is as recent as its
    verification, and picking by key order would make that depend on which
    daemon wrote it. ISO-8601 sorts lexicographically, and a date-only stamp
    sorts before any datetime on the same day, so mixed granularity across
    daemons still compares correctly.

    Only the leading timestamp counts. review-trigger writes lastVerified as a
    date followed by a sentence — "2026-08-21 run 55 - static; ask still
    pending" — and comparing those whole sorts on the English after the date,
    which put a static PR above the one whose head had just moved. A value with
    no leading timestamp is a note, not a time, and is ignored.
    """
    stamps = []
    for key, val in rec.items():
        if key not in _TIME_KEYS or not isinstance(val, str):
            continue
        if m := _STAMP_RE.match(val):
            stamps.append(f"{m['date']}T{m['time']}" if m["time"] else m["date"])
    return max(stamps, default="")


def _col(text: str, width: int) -> str:
    """`text` fitted to exactly `width` cells — padded if short, clipped if long.

    Padding alone is not enough. A filer daemon that could not resolve a story
    id keys its record on the cluster signature, which is a sentence, and an
    unclipped one ran straight into the title and pushed every later column off
    the panel.
    """
    return f"{text:<{width}}" if len(text) <= width else text[: width - 1] + "…"


def _id_rank(item) -> int:
    """An item id as an int for tie-breaking, 0 when it isn't numeric.

    Always an int, so the sort key stays a comparable tuple even on a
    signature-keyed record whose id is a string.
    """
    try:
        return int(item)
    except (TypeError, ValueError):
        return 0


def _latest_by_reviewer(records: list[dict]) -> dict:
    """Each reviewer's most recent record. render_work hands every group over
    newest-first, so the first sighting of a login wins."""
    latest: dict = {}
    for rec in records:
        who = rec.get("reviewer")
        if who and who not in latest:
            latest[who] = rec
    return latest


def _verdicts(records: list[dict]) -> str:
    """Where the PR stands *now*: how many reviewers approve its current commit,
    how many do not, and how many have not weighed in on it yet.

    A verdict is only current if it was given against the newest commit this
    daemon has seen for the PR. An older one has been superseded by a push and
    says nothing about the code as it stands — counting it is how a PR that is
    actually approved reads as still blocked.

    Derived from the state file rather than GitHub, deliberately: the panel
    redraws every few seconds, and GitHub's review state would not show your own
    ACR instance at all, since it can only post COMMENT on your own PR.
    """
    head = (records[0] or {}).get("headSha")
    approve = blocked = pending = 0
    for rec in _latest_by_reviewer(records).values():
        if rec.get("headSha") != head:
            pending += 1  # last spoke on an older commit; silent on this one
        elif rec.get("verdict") == "approve":
            approve += 1
        else:
            blocked += 1  # request_changes, comment, or a prose review
    parts = []
    if approve:
        parts.append(f"[green]+{approve}[/green]")
    if blocked:
        parts.append(f"[red]!{blocked}[/red]")
    if pending:
        parts.append(f"[dim]?{pending}[/dim]")
    return " ".join(parts)


def _tally(records: list[dict]) -> str:
    """Findings across a group, as done/declined counts. Empty when a daemon
    doesn't track findings — most don't."""
    done = declined = 0
    for rec in records:
        for verdict in (rec.get("findings") or {}).values():
            if verdict in _DONE:
                done += 1
            elif verdict in _DECLINED:
                declined += 1
    parts = []
    if done:
        parts.append(f"[green]{done}✓[/green]")
    if declined:
        parts.append(f"[yellow]{declined}✗[/yellow]")
    return " ".join(parts)


def _work_row(item, recs: list[dict]) -> str:
    """One item's line: outcome of its most recent record, plus what it spans.

    `recs` arrives newest-first from render_work.
    """
    latest = recs[0]
    outcome = latest.get("outcome") or latest.get("verdict") or ""
    if outcome in _DONE:
        mark = "[green]✓[/green]"
    elif outcome == "parked":
        mark = "[yellow]‖[/yellow]"
    else:
        mark = "[dim]·[/dim]"
    # Fixer daemons record an outcome per item; the filer daemons (datadog,
    # mongo, hubspot) record a filed story instead, where the title is the
    # only thing worth a row.
    descr = outcome or (latest.get("title") or "").strip()[:44] or "—"
    label = f"#{item}" if item is not None else "(unkeyed)"
    bits = [f"{mark} [b]{_col(label, _LABEL_W)}[/b][dim]{descr:<10}[/dim]"]
    if verdicts := _verdicts(recs):
        bits.append(verdicts)
    elif who := {r.get("reviewer") for r in recs if r.get("reviewer")}:
        bits.append(f"[dim]{len(who)} rev[/dim]")
    if latest.get("round"):
        bits.append(f"[dim]r{latest['round']}[/dim]")
    if tally := _tally(recs):
        bits.append(tally)
    return "  ".join(bits)


def render_work(cfg, slug: str, limit: int = 10) -> str:
    """One row per item the daemon has acted on, newest first.

    Collapses the raw record list — acr-fixer writes one per (reviewer, round),
    so a single PR can span several — into a line per PR, which is the unit a
    human actually tracks.

    The order is imposed here, not inherited. A state file's own order means
    nothing: hubspot-reconciliation appends (so an item first seen on the 6th
    sits above one filed on the 18th), review-trigger writes sorted by PR
    number, mongo-slow-query interleaves re-sightings with new filings. Reading
    any of those top-down under a "newest first" heading tells you the opposite
    of what happened.
    """
    records = _read_state(cfg, slug)
    if records is None:
        return "[dim](no state yet)[/dim]"
    if not records:
        return "[dim](empty)[/dim]"

    groups: dict = {}
    for rec in records:
        if isinstance(rec, dict):
            groups.setdefault(_item_id(rec), []).append(rec)
    if not groups:
        return f"[dim]{len(records)} record(s), no recognisable items[/dim]"

    # Newest record first within each item, then items by their newest record —
    # an item is as recent as the last thing that happened to it, so adopting a
    # months-old story today belongs at the top. Ties fall back to the id, which
    # matters more than it sounds: mongo-slow-query stamps a whole day's filings
    # with one date, so without it a third of that panel would be arbitrary.
    ordered = sorted(
        ((item, sorted(recs, key=_stamp, reverse=True)) for item, recs in groups.items()),
        key=lambda kv: (_stamp(kv[1][0]), _id_rank(kv[0])),
        reverse=True,
    )

    # Only the review daemons carry reviewers and findings; the filer daemons
    # would just get a key to columns their rows never have.
    key = ""
    if any(r.get("reviewer") or r.get("findings") for r in records if isinstance(r, dict)):
        key = (
            "  ·  at current commit [green]+[/green]approve [red]![/red]not"
            " [dim]?[/dim]pending  ·  findings [green]✓[/green]done"
            " [yellow]✗[/yellow]declined"
        )
    rows = [f"[dim]{len(groups)} item(s) · {len(records)} record(s){key}[/dim]"]
    rows += [_work_row(item, recs) for item, recs in ordered[:limit]]
    if len(groups) > limit:
        rows.append(f"[dim]… {len(groups) - limit} more[/dim]")
    return "\n".join(rows)


def _tail(path: Path, n: int, blocksize: int = 65536) -> list[str]:
    """Read only the tail of the file (last ~blocksize bytes), then the last n lines —
    avoids re-reading a multi-MB log on every refresh."""
    size = path.stat().st_size
    with path.open("rb") as f:
        f.seek(max(0, size - blocksize))
        data = f.read()
    return data.decode("utf-8", errors="replace").splitlines()[-n:]


def render_log(cfg, slug: str, n: int = 40) -> str:
    path = cfg.state_dir / "logs" / f"{slug}.log"
    if not path.exists():
        return "[dim](no log yet)[/dim]"
    lines = _tail(path, n)
    if not lines:
        return "[dim](empty)[/dim]"
    return "\n".join(f"[dim]{ln[:240]}[/dim]" for ln in reversed(lines))
