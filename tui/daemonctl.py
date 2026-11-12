"""dAImon control panel — a Textual TUI over the daemon pipeline. Config-driven:
the daemon list comes from the framework's auto-discovery, never a hardcoded list."""

import subprocess

import detail
import ops
import state
from _lib import INSTALL_ROOT, config
from rich.text import Text
from screens import (
    ConfigScreen,
    ConfirmScreen,
    DuplicateScreen,
    FilesScreen,
    HelpScreen,
    ManageScreen,
    ProcessScreen,
)
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static

MANAGE_ITEMS = [
    ("run_now", "g   run now (bypass gates)"),
    ("attach", "a   attach to live session"),
    ("configure", "c   configure (schedule / model / inputs)"),
    ("enable", "e   enable (load plist)"),
    ("disable", "d   disable (unload plist)"),
    ("register", "r   register (create plist)"),
    ("unregister", "u   unregister (delete plist)"),
    ("ai_configure", "b   edit with AI"),
    ("duplicate", "y   duplicate (clone for another repo)"),
    ("new_daemon", "n   new daemon (build with AI)"),
    ("view", "v   view files (config + skill)"),
    ("procs", "p   process tree"),
    ("log", "l   tail the log"),
    ("kill", "    kill the running session"),
    ("throttle", "t   cycle throttle"),
    ("bridge", "B   start / stop the Slack bridge"),
    ("pause_all", "P   pause all"),
    ("resume_all", "R   resume all"),
]

HELP_ITEMS = [
    ("↑/↓ j/k", "move selection"),
    ("/", "filter daemons"),
    ("a", "attach to the live session"),
    ("g", "run now (bypass gates)"),
    ("c", "configure (schedule/backend/model/danger)"),
    ("n", "new daemon (build with Claude)"),
    ("b", "edit daemon with Claude"),
    ("y", "duplicate daemon (clone for another repo)"),
    ("v", "view files (daemon.toml + rendered skill)"),
    ("e / d", "enable / disable (load / unload plist)"),
    ("r / u", "register / unregister (create / delete plist)"),
    ("p", "process tree"),
    ("l", "tail the log"),
    ("t", "cycle throttle (off→moderate→severe→halt)"),
    ("P / R", "pause all / resume all"),
    ("B", "start / stop the Slack bridge (env-bridge service)"),
    ("m", "manage menu"),
    ("f", "refresh"),
    ("? / q", "help / quit"),
]

CONFIRM = {
    "kill": "Kill the running session for '{slug}'?",
    "unregister": "Unregister '{slug}' — unload and delete its plist?",
}
STOP_BRIDGE = "Stop the Slack bridge? Mentions get no reply until it's started again."

# Distinct shapes so state reads without relying on colour (legend under the list).
RUN, IDLE = "●", "·"
LOADED, REGISTERED, UNREG = "▶", "◇", "–"
LEGEND = f"[dim]{RUN} running   {IDLE} idle[/dim]\n[dim]{LOADED} loaded  {REGISTERED} registered  {UNREG} off[/dim]"


class DaemonCtl(App):
    TITLE = "dAImon"
    CSS = """
    #main { height: 1fr; }
    #sidebar { width: 38; border: round $surface-lighten-2; padding: 0 1; }
    #sidebar:focus-within { border: round $accent; }
    #detail-col { width: 1fr; }
    #panel-config { height: auto; max-height: 45%; border: round $surface-lighten-2; padding: 0 1; }
    #panel-status { height: auto; border: round $surface-lighten-2; padding: 0 1; }
    #panel-procs { height: auto; border: round $surface-lighten-2; padding: 0 1; }
    #panel-log { height: 1fr; border: round $surface-lighten-2; padding: 0 1; }
    #list { height: 1fr; background: transparent; }
    #legend { height: auto; padding: 0; margin: 0; }
    #bridge { height: auto; padding: 0; margin: 0 0 1 0; }
    DataTable > .datatable--cursor { background: $accent 40%; text-style: bold; }
    #filter { display: none; border: none; height: 1; padding: 0; margin: 0; }
    .filtering #filter { display: block; }
    .narrow #detail-col { display: none; }
    .narrow #sidebar { width: 1fr; }
    """
    BINDINGS = [
        Binding("a", "attach", "attach"),
        Binding("g", "run_now", "run now"),
        Binding("c", "configure", "config"),
        Binding("n", "new_daemon", "new (AI)"),
        Binding("slash", "filter", "filter"),
        Binding("m", "manage", "manage"),
        Binding("question_mark", "help", "help"),
        Binding("q", "quit", "quit"),
        Binding("y", "duplicate", "duplicate", show=False),
        Binding("v", "view", "view files", show=False),
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("escape", "clear_filter", "clear filter", show=False),
        Binding("f", "refresh", "refresh", show=False),
        Binding("e", "enable", "enable", show=False),
        Binding("d", "disable", "disable", show=False),
        Binding("r", "register", "register", show=False),
        Binding("u", "unregister", "unregister", show=False),
        Binding("b", "ai_configure", "edit (AI)", show=False),
        Binding("p", "procs", "procs", show=False),
        Binding("t", "throttle", "throttle", show=False),
        Binding("l", "log", "log", show=False),
        Binding("P", "pause_all", "pause all", show=False),
        Binding("R", "resume_all", "resume all", show=False),
        Binding("B", "bridge", "bridge", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield DataTable(id="list")
                yield Static(id="bridge")
                yield Static(LEGEND, id="legend")
                yield Input(placeholder="filter…", id="filter")
            with Vertical(id="detail-col"):
                with VerticalScroll(id="panel-config"):
                    yield Static(id="config-body")
                yield Static(id="panel-status")
                yield Static(id="panel-procs")
                with VerticalScroll(id="panel-log"):
                    yield Static(id="log-body")
        yield Footer()

    def on_mount(self) -> None:
        self.table = self.query_one(DataTable)
        self.table.cursor_type = "row"
        self.table.show_header = False
        self.table.add_columns("st", "daemon", "be")
        self.query_one("#panel-status").border_title = "launchd"
        self.query_one("#panel-procs").border_title = "processes"
        self.query_one("#panel-log").border_title = "log · newest first"
        self.slugs: list[str] = []
        self.filter_text = ""
        self.refresh_table()
        self.set_interval(4, self.refresh_table)

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 90, "narrow")

    def _dot(self, running: bool) -> str:
        return f"[green]{RUN}[/green]" if running else f"[dim]{IDLE}[/dim]"

    def _name_markup(self, slug: str, loaded: bool, registered: bool) -> str:
        glyph, colour = (
            (LOADED, "green")
            if loaded
            else (REGISTERED, "yellow")
            if registered
            else (UNREG, "red")
        )
        return f"[{colour}]{glyph} {slug}[/{colour}]"

    def _bridge_markup(self, cfg, listing: str) -> str:
        status, pid = state.bridge_state(cfg, listing)
        if status == "running":
            return f"[green]{RUN} slack bridge[/green] [dim]pid {pid} · B stop[/dim]"
        if status == "loaded":
            return f"[yellow]{REGISTERED} slack bridge[/yellow] [dim]restarting · B stop[/dim]"
        return f"[dim]{UNREG} slack bridge off · B start[/dim]"

    def action_bridge(self) -> None:
        cfg = config.Config.load()
        if state.bridge_state(cfg)[0] == "off":
            self._bridge_op("install")
            return

        def done(ok: bool | None) -> None:
            if ok:
                self._bridge_op("uninstall")

        self.push_screen(ConfirmScreen(STOP_BRIDGE), done)

    def _bridge_op(self, action: str) -> None:
        ok, out = ops.bridge(action)
        self.notify(out or action, severity="information" if ok else "error", timeout=8)
        self.refresh_table()

    def _be(self, backend: str) -> str:
        return {"claude": "cld", "codex": "cdx"}.get(backend, backend)

    def refresh_table(self) -> None:
        cfg = config.Config.load()
        row = self.table.cursor_row
        self.table.clear()
        allslugs = list(cfg.discover())
        flt = self.filter_text.lower()
        self.slugs = [s for s in allslugs if flt in s.lower()]
        sessions = state.live_sessions()  # one tmux/launchctl query per refresh, not per row
        loaded = state.loaded_labels_text()
        for slug in self.slugs:
            d = cfg.daemon(slug)
            running = state.running_session(cfg, slug, sessions) is not None
            is_loaded = state.launchd_loaded(state.label_for(cfg, slug), loaded)
            self.table.add_row(
                Text.from_markup(self._dot(running)),
                Text.from_markup(self._name_markup(slug, is_loaded, state.registered(cfg, slug))),
                self._be(d["backend"]),
                key=slug,
            )
        count = f"{len(self.slugs)}/{len(allslugs)}" if flt else str(len(allslugs))
        self.query_one("#sidebar").border_title = f"daemons ({count})"
        self.sub_title = f"throttle={state.throttle_level(cfg)}  ·  {len(allslugs)} daemons"
        self.query_one("#bridge", Static).update(self._bridge_markup(cfg, loaded))
        if self.slugs:
            self.table.move_cursor(row=min(row, len(self.slugs) - 1))
        self._update_detail(allslugs, cfg)

    def _render_panels(self, cfg, slug: str) -> None:
        self.query_one("#config-body", Static).update(detail.render_config(cfg, slug))
        self.query_one("#panel-status", Static).update(detail.render_status(cfg, slug))
        self.query_one("#panel-procs", Static).update(detail.render_procs(cfg, slug))
        self.query_one("#log-body", Static).update(detail.render_log(cfg, slug))

    def _clear_panels(self, allslugs: list[str] | None) -> None:
        for wid in ("#panel-status", "#panel-procs", "#log-body"):
            self.query_one(wid, Static).update("")
        if allslugs is not None and not allslugs:
            msg = "[dim]No daemons yet.[/dim]\n\nPress [bold]n[/bold] to build one with Claude."
        else:
            msg = f"[dim]No daemon matches '{self.filter_text}'.[/dim]"
        self.query_one("#config-body", Static).update(msg)

    def _update_detail(self, allslugs: list[str] | None = None, cfg=None) -> None:
        slug = self._slug()
        self.query_one("#panel-config").border_title = f"config · {slug}" if slug else "config"
        if slug:
            self._render_panels(cfg or config.Config.load(), slug)
        else:
            self._clear_panels(allslugs)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def _slug(self) -> str | None:
        return self.slugs[self.table.cursor_row] if self.slugs else None

    def _load_and_slug(self):
        slug = self._slug()
        return (slug, config.Config.load()) if slug else None

    def _suspend_run(self, *cmd: str, cwd: str | None = None) -> None:
        with self.suspend():
            subprocess.run(cmd, cwd=cwd, check=False)

    def action_new_daemon(self) -> None:
        self._suspend_run(*ops.builder_argv(), cwd=str(INSTALL_ROOT))
        self.refresh_table()

    def action_ai_configure(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, _ = sel
        self._suspend_run(*ops.configure_argv(slug), cwd=str(INSTALL_ROOT))
        self.refresh_table()

    def action_attach(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel
        sess = state.running_session(cfg, slug)
        if sess:
            self._suspend_run("tmux", "attach", "-t", sess)

    def _op(self, fn) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel
        fn(cfg, slug)
        self.refresh_table()

    def action_run_now(self) -> None:
        self._op(ops.run_now)

    def action_enable(self) -> None:
        self._op(ops.enable)

    def action_disable(self) -> None:
        self._op(ops.disable)

    def action_register(self) -> None:
        self._op(ops.register)

    def action_unregister(self) -> None:
        self._confirm_op("unregister", ops.unregister)

    def _confirm_op(self, key: str, fn) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel

        def done(ok: bool | None) -> None:
            if ok:
                fn(cfg, slug)
                self.refresh_table()

        self.push_screen(ConfirmScreen(CONFIRM[key].format(slug=slug)), done)

    def action_kill(self) -> None:
        self._confirm_op("kill", ops.kill_run)

    def action_configure(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel
        self.push_screen(ConfigScreen(cfg, slug))

    def action_procs(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, _ = sel
        self.push_screen(ProcessScreen(INSTALL_ROOT, slug))

    def action_view(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel
        self.push_screen(FilesScreen(cfg, slug))

    def action_duplicate(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel

        def done(new: str | None) -> None:
            if not new:
                return
            if (cfg.daemons_dir() / new).exists():
                self.notify(f"'{new}' already exists", severity="error")
                return
            ops.duplicate(cfg, slug, new)
            self.refresh_table()
            self.push_screen(ConfigScreen(config.Config.load(), new))

        self.push_screen(DuplicateScreen(slug), done)

    def action_log(self) -> None:
        sel = self._load_and_slug()
        if not sel:
            return
        slug, cfg = sel
        self._suspend_run("less", "+G", str(cfg.state_dir / "logs" / f"{slug}.log"))

    def action_manage(self) -> None:
        self.push_screen(ManageScreen(MANAGE_ITEMS), self._run_manage)

    def _run_manage(self, action: str | None) -> None:
        if action:
            getattr(self, f"action_{action}")()

    def action_refresh(self) -> None:
        self.refresh_table()

    def action_help(self) -> None:
        self.push_screen(HelpScreen(HELP_ITEMS))

    def action_cursor_down(self) -> None:
        if self.slugs:
            self.table.move_cursor(row=min(self.table.cursor_row + 1, len(self.slugs) - 1))

    def action_cursor_up(self) -> None:
        if self.slugs:
            self.table.move_cursor(row=max(self.table.cursor_row - 1, 0))

    def action_filter(self) -> None:
        self.add_class("filtering")
        self.query_one("#filter", Input).focus()

    def action_clear_filter(self) -> None:
        if not self.has_class("filtering"):
            return
        self.filter_text = ""
        self.query_one("#filter", Input).value = ""
        self.remove_class("filtering")
        self.table.focus()
        self.refresh_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self.refresh_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.table.focus()

    def action_throttle(self) -> None:
        ops.cycle_throttle(config.Config.load())
        self.refresh_table()

    def action_pause_all(self) -> None:
        cfg = config.Config.load()
        for slug in self.slugs:
            ops.disable(cfg, slug)
        self.refresh_table()

    def action_resume_all(self) -> None:
        cfg = config.Config.load()
        for slug in self.slugs:
            ops.enable(cfg, slug)
        self.refresh_table()


if __name__ == "__main__":
    DaemonCtl().run()
