#!/usr/bin/env bash
# Hourly launch accounting. Sourced after common.sh.

_budget_file() { echo "$(runtime_dir)/hourly-usage.json"; }

budget_record() {  # slug — count one launch in the current hour
  local slug="$1" f; f="$(_budget_file)"
  mkdir -p "$(dirname "$f")"
  python3 - "$f" "$slug" <<'PY'
import json, sys, datetime
path, slug = sys.argv[1], sys.argv[2]
hour = datetime.datetime.now().strftime("%Y-%m-%dT%H")
try: data = json.load(open(path))
except Exception: data = {}
h = data.setdefault(hour, {"total": 0, "by_daemon": {}})
h["total"] += 1
h["by_daemon"][slug] = h["by_daemon"].get(slug, 0) + 1
json.dump(data, open(path, "w"))
PY
}

_budget_query() {  # [slug] — fleet total this hour, or one daemon's own count
  python3 - "$(_budget_file)" "${1:-}" <<'PY'
import json, sys, datetime
path, slug = sys.argv[1], sys.argv[2]
hour = datetime.datetime.now().strftime("%Y-%m-%dT%H")
try: h = json.load(open(path)).get(hour, {})
except Exception: h = {}
print(h.get("by_daemon", {}).get(slug, 0) if slug else h.get("total", 0))
PY
}

budget_total_this_hour() { _budget_query; }
budget_daemon_this_hour() { _budget_query "$1"; }

_budget_exempt() {  # slug — in budget.exempt? (cheap high-frequency pollers)
  local v="$1" item
  for item in $(cfg get budget.exempt 2>/dev/null); do [ "$item" = "$v" ] && return 0; done
  return 1
}

budget_check() {  # [slug] — sets BUDGET_OVER (0/1) and BUDGET_REASON
  local cap pct total threshold own
  BUDGET_OVER=0
  BUDGET_REASON=""
  if [ -n "${1:-}" ]; then
    if _budget_exempt "$1"; then return; fi
    # A daemon with its own hourly_cap is governed by its own launch count
    # and steps out of the global pool entirely.
    own="$(cfg daemon "$1" hourly_cap 2>/dev/null || true)"
    if [ -n "$own" ]; then
      total="$(budget_daemon_this_hour "$1")"
      if [ "$total" -ge "$own" ]; then
        BUDGET_OVER=1
        BUDGET_REASON="daemon budget: ${total}/${own} launches this hour, deferring"
      fi
      return
    fi
  fi
  cap="$(cfg get budget.hourly_cap)"
  pct="$(cfg get budget.defer_at_pct)"
  total="$(budget_total_this_hour)"
  threshold=$(( cap * pct / 100 ))
  if [ "$total" -ge "$threshold" ]; then
    BUDGET_OVER=1
    BUDGET_REASON="hourly budget: ${total}/${cap} launches (>= ${pct}% cap), deferring"
  else
    BUDGET_OVER=0
    BUDGET_REASON=""
  fi
}
