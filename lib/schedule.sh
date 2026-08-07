#!/usr/bin/env bash
# Human "next run" display derived from a daemon's configured schedule.

next_run_display() {  # slug -> e.g. "next run ~14:38"
  local slug="$1" desc
  desc="$(cfg schedule "$slug" 2>/dev/null)" || { echo "next run unknown"; return; }
  python3 - "$desc" <<'PY'
import sys, datetime
parts = sys.argv[1].split()
kind = parts[0]
now = datetime.datetime.now()
def fmt(dt): return dt.strftime("%H:%M")
if kind == "interval":
    nxt = now + datetime.timedelta(seconds=int(parts[1]))
    print(f"next run ~{fmt(nxt)} (every {parts[1]}s)")
elif kind == "minutes":
    # "minutes 11 26 41 56" or "minutes 11 26 41 56 days mon-fri"
    if "days" in parts:
        sep = parts.index("days")
        mins, days = sorted(int(m) for m in parts[1:sep]), parts[sep + 1]
    else:
        mins, days = sorted(int(m) for m in parts[1:]), "all"
    if days == "all":
        cands = [now.replace(minute=m, second=0, microsecond=0) for m in mins]
        cands = [c if c > now else c + datetime.timedelta(hours=1) for c in cands]
        print(f"next run ~{fmt(min(cands))}")
    else:
        allowed = {"mon-fri": range(5), "sat-sun": {5, 6}}[days]
        base = now.replace(second=0, microsecond=0)
        nxt = None
        for h in range(8 * 24):              # today plus a full week of lookahead
            slot = base + datetime.timedelta(hours=h)
            if slot.weekday() not in allowed:   # Python: Monday==0 … Sunday==6
                continue
            for m in mins:
                c = slot.replace(minute=m)
                if c > now and (nxt is None or c < nxt):
                    nxt = c
            if nxt:
                break
        if nxt:
            when = fmt(nxt) if nxt.date() == now.date() else nxt.strftime("%a %H:%M")
            print(f"next run ~{when} ({days})")
        else:
            print("next run unknown")
elif kind == "daily":
    hh, mm = parts[1].split(":")
    nxt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if nxt <= now: nxt += datetime.timedelta(days=1)
    print(f"next run ~{fmt(nxt)} daily")
elif kind == "at":
    # "at 09:00 16:00 days mon-fri"
    sep = parts.index("days")
    times, days = parts[1:sep], parts[sep + 1]
    allowed = {"all": range(7), "mon-fri": range(5), "sat-sun": {5, 6}}[days]
    cands = []
    for d in range(8):                       # today plus a full week of lookahead
        day = now.date() + datetime.timedelta(days=d)
        if day.weekday() not in allowed:     # Python: Monday==0 … Sunday==6
            continue
        for t in times:
            hh, mm = t.split(":")
            c = datetime.datetime.combine(day, datetime.time(int(hh), int(mm)))
            if c > now:
                cands.append(c)
    if cands:
        nxt = min(cands)
        when = fmt(nxt) if nxt.date() == now.date() else nxt.strftime("%a %H:%M")
        print(f"next run ~{when} ({days})")
    else:
        print("next run unknown")
else:
    print("next run unknown")
PY
}
