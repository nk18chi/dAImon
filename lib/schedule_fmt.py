"""The one owner of schedule format conversions, shared by the config core and
the TUI.

A schedule is a dict in one of four shapes:
    {"interval": 1200}              every N seconds
    {"minutes": [8, 38],            at these minutes past each hour, on these days
     "days": "mon-fri"}
    {"daily": "09:02", "tz": ...}   once a day at HH:MM
    {"at": ["09:00", "16:00"],      at these times, on these days
     "days": "mon-fri"}

Human string form (TUI input/display):
    "20m" / "1h" / "30s"  <-> {"interval": N}
    ":8,38"               <-> {"minutes": [8, 38]}
    ":8,38 mon-fri"       <-> {"minutes": [8, 38], "days": "mon-fri"}
    "09:02"               <-> {"daily": "09:02"}
    "09:00,16:00 mon-fri" <-> {"at": [...], "days": "mon-fri"}

`days` is omitted entirely when it is "all", so an unfiltered schedule keeps the
shape it has always had and existing configs are untouched.

All clock-time forms fire on the machine's LOCAL time, which is what launchd's
StartCalendarInterval uses. It follows DST, so "09:00" stays 9am through the
switch. The `tz` key on `daily` is descriptive only — it has never reached the
plist, and `at` deliberately does not offer one rather than repeat that.
"""

import re

_INTERVAL = re.compile(r"(\d+)([smh])")
_DAILY = re.compile(r"\d{1,2}:\d{2}")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}

# launchd Weekday: 0 and 7 are Sunday, 1 Monday … 6 Saturday.
DAY_SETS = {"all": None, "mon-fri": [1, 2, 3, 4, 5], "sat-sun": [6, 0]}


def _split_days(text: str) -> tuple[str, str]:
    """Peel a trailing day set off a schedule string, defaulting to "all".

    "8,38 mon-fri" -> ("8,38", "mon-fri");  "8,38" -> ("8,38", "all").
    Raises on an unknown day set so a typo fails loudly instead of silently
    scheduling every day.
    """
    head, _, tail = text.partition(" ")
    days = tail.strip() or "all"
    if days not in DAY_SETS:
        raise ValueError(f"bad schedule: {text!r}")
    return head, days


def _with_days(sched: dict, days: str) -> dict:
    """Attach `days` only when it filters something, so an unfiltered schedule
    keeps the shape it has always had."""
    if days != "all":
        sched["days"] = days
    return sched


def parse(text: str) -> dict:
    text = text.strip()
    if text.startswith(":"):
        head, days = _split_days(text[1:])
        mins = [int(x) for x in head.split(",") if x.strip()]
        return _with_days({"minutes": mins}, days)
    m = _INTERVAL.fullmatch(text)
    if m:
        return {"interval": int(m.group(1)) * _UNIT_SECONDS[m.group(2)]}
    if _DAILY.fullmatch(text):
        return {"daily": text}
    # "09:00,16:00" or "09:00 mon-fri" or "09:00,16:00 mon-fri"
    head, days = _split_days(text)
    times = [t.strip() for t in head.split(",") if t.strip()]
    if times and all(_DAILY.fullmatch(t) for t in times):
        return {"at": times, "days": days}
    raise ValueError(f"bad schedule: {text!r}")


def display(sched: dict) -> str:
    if "interval" in sched:
        return f"{sched['interval']}s"
    if "minutes" in sched:
        mins = ":" + ",".join(str(m) for m in sched["minutes"])
        days = sched.get("days", "all")
        return mins if days == "all" else f"{mins} {days}"
    if "daily" in sched:
        return sched["daily"]
    if "at" in sched:
        days = sched.get("days", "all")
        times = ",".join(sched["at"])
        return times if days == "all" else f"{times} {days}"
    return ""


def descriptor(sched: dict) -> str:
    if "interval" in sched:
        return f"interval {int(sched['interval'])}"
    if "minutes" in sched:
        # The trailing " days X" is emitted only when filtering, so an unfiltered
        # descriptor stays byte-identical to what schedule.sh has always parsed.
        out = "minutes " + " ".join(str(int(m)) for m in sched["minutes"])
        days = sched.get("days", "all")
        return out if days == "all" else f"{out} days {days}"
    if "daily" in sched:
        return f"daily {sched['daily']} {sched.get('tz', 'local')}"
    if "at" in sched:
        return "at " + " ".join(sched["at"]) + " days " + sched.get("days", "all")
    raise ValueError(f"unrecognized schedule: {sched}")


def _calendar_array(slots: list[str], days: str) -> str:
    """A StartCalendarInterval array from pre-rendered key/value fragments.

    launchd has no "weekdays" flag: it takes one dict per (slot, weekday) pair,
    and omitting Weekday entirely means every day.
    """
    weekdays = DAY_SETS[days]
    entries = []
    for slot in slots:
        if weekdays is None:
            entries.append(f"        <dict>{slot}</dict>")
        else:
            entries += [
                f"        <dict>{slot}<key>Weekday</key><integer>{d}</integer></dict>"
                for d in weekdays
            ]
    body = "\n".join(entries)
    return f"    <key>StartCalendarInterval</key>\n    <array>\n{body}\n    </array>"


def to_plist(sched: dict) -> str:
    if "interval" in sched:
        return f"    <key>StartInterval</key>\n    <integer>{int(sched['interval'])}</integer>"
    if "minutes" in sched:
        slots = [f"<key>Minute</key><integer>{int(m)}</integer>" for m in sched["minutes"]]
        return _calendar_array(slots, sched.get("days", "all"))
    if "daily" in sched:
        hh, mm = sched["daily"].split(":")
        return (
            "    <key>StartCalendarInterval</key>\n    <dict>"
            f"<key>Hour</key><integer>{int(hh)}</integer>"
            f"<key>Minute</key><integer>{int(mm)}</integer></dict>"
        )
    if "at" in sched:
        slots = []
        for t in sched["at"]:
            hh, mm = t.split(":")
            slots.append(
                f"<key>Hour</key><integer>{int(hh)}</integer>"
                f"<key>Minute</key><integer>{int(mm)}</integer>"
            )
        return _calendar_array(slots, sched.get("days", "all"))
    raise ValueError(f"unrecognized schedule: {sched}")
