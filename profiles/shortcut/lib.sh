#!/usr/bin/env bash
# Shared helpers for the Shortcut source profile: API token + story search.
# Sourced by a daemon's discover.sh.

shortcut_token() {
  if [ -n "${SHORTCUT_API_TOKEN:-}" ]; then
    echo "$SHORTCUT_API_TOKEN"
    return
  fi
  local f
  for f in "$HOME/.config/short/config.json" "$HOME/.config/shortcut-cli/config.json"; do
    if [ -f "$f" ]; then
      python3 -c "import json;print(json.load(open('$f')).get('token',''))" 2>/dev/null
      return
    fi
  done
}

# _sc_queries "<query>" -> the query, then, when it excludes an objective, one
# variant per $DAIMON_INPUT_INCLUDE_EPICS epic with the objective terms dropped.
# An epic opted back in out of an excluded objective needs its own search: the
# search DSL has no OR. Other exclusions (epics, labels) stay on every variant.
_sc_queries() {
  printf '%s\n' "$1"
  case "$1" in *'!objective:'*) ;; *) return 0 ;; esac
  local base e; base="$(printf '%s' "$1" | sed -E 's/ ?!objective:[0-9]+//g')"
  for e in ${DAIMON_INPUT_INCLUDE_EPICS:-}; do printf '%s epic:%s\n' "$base" "$e"; done
}

# shortcut_count "<search query>" -> number of matching stories (0 on any error),
# opted-in epics included (see _sc_queries).
shortcut_count() {
  local q n total=0
  while IFS= read -r q; do
    n="$(_sc_count_once "$q")"; total=$((total + ${n:-0}))
  done < <(_sc_queries "$1")
  echo "$total"
}

_sc_count_once() {
  local token; token="$(shortcut_token)"
  [ -z "$token" ] && { echo 0; return; }
  curl -s -G "https://api.app.shortcut.com/api/v3/search/stories" \
    --data-urlencode "query=$1" -H "Shortcut-Token: $token" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo 0
}

# shortcut_mention "<member-id>" -> the member's @mention name ("" on any error).
# The search DSL's owner:/requester: operators take a mention name, not the id.
shortcut_mention() {
  local token; token="$(shortcut_token)"
  [ -z "$token" ] && return
  curl -s "https://api.app.shortcut.com/api/v3/members/$1" -H "Shortcut-Token: $token" \
    | python3 -c "import sys,json;m=json.load(sys.stdin);p=m.get('profile') or {};print(p.get('mention_name') or m.get('mention_name') or '')" 2>/dev/null
}

# shortcut_exclusions -> query terms excluding every epic id in
# $DAIMON_INPUT_EXCLUDE_EPICS, every objective id in
# $DAIMON_INPUT_EXCLUDE_OBJECTIVES and every label in
# $DAIMON_INPUT_EXCLUDE_LABELS (space-separated), e.g. " !epic:1234
# !objective:42 !label:\"milestone\"". Empty when all are unset, so a gate can append it
# unconditionally. The search DSL takes the ids directly; `epic_id:` is not an
# operator and matches nothing. `!objective:` covers every epic in the objective,
# including epics added later.
shortcut_exclusions() {
  local id out=""
  for id in ${DAIMON_INPUT_EXCLUDE_EPICS:-}; do out="$out !epic:$id"; done
  for id in ${DAIMON_INPUT_EXCLUDE_OBJECTIVES:-}; do out="$out !objective:$id"; done
  for id in ${DAIMON_INPUT_EXCLUDE_LABELS:-}; do out="$out !label:\"$id\""; done
  printf '%s' "$out"
}

# shortcut_include_requested -> success when the requester role counts toward
# scope ($DAIMON_INPUT_INCLUDE_REQUESTED, default on). Off: only owners count.
shortcut_include_requested() {
  [ "${DAIMON_INPUT_INCLUDE_REQUESTED:-1}" != "0" ]
}

# shortcut_owner_count "<base query>" -> story count scoped to $DAIMON_INPUT_OWNER
# (owner, plus requester unless include_requested is off), or workspace-wide if
# OWNER is unset. When OWNER is set but
# its mention can't be resolved it writes to stderr and returns 1, so run.sh
# surfaces a discover_error rather than letting the gate silently widen to the
# whole workspace and touch others' stories.
shortcut_owner_count() {
  local base="$1"
  if [ -z "${DAIMON_INPUT_OWNER:-}" ]; then shortcut_count "$base"; return; fi
  local mention; mention="$(shortcut_mention "$DAIMON_INPUT_OWNER")"
  if [ -z "$mention" ]; then
    echo "discover: could not resolve owner mention for $DAIMON_INPUT_OWNER" >&2
    return 1
  fi
  local n; n=$(shortcut_count "owner:$mention $base")
  if shortcut_include_requested; then
    n=$(( n + $(shortcut_count "requester:$mention !owner:$mention $base") ))
  fi
  echo "$n"
}

# shortcut_search_ids "<query>" -> one "id updated_at" line per matching story
# (nothing on any error). Gates that must compare stories against a state record
# need ids, not a count. One page of up to 250 results — enough for a gate, which
# only needs to know whether any candidate survives. Opted-in epics included (see
# _sc_queries), deduped in order.
shortcut_search_ids() {
  local q
  while IFS= read -r q; do _sc_search_ids_once "$q"; done < <(_sc_queries "$1") \
    | awk '!seen[$0]++'
}

_sc_search_ids_once() {
  local token; token="$(shortcut_token)"
  [ -z "$token" ] && return
  curl -s -G "https://api.app.shortcut.com/api/v3/search/stories" \
    --data-urlencode "query=$1" --data-urlencode page_size=250 --data-urlencode detail=slim \
    -H "Shortcut-Token: $token" \
    | python3 -c "$_SC_PRINT_IDS" 2>/dev/null
}

# With SC_STATUS_KEEP set (even to ""), shortcut_search_ids keeps only stories
# whose status field (id in SC_STATUS_FIELD_ID) holds one of its "|"-separated
# values; an empty entry stands for "field unset". Search can't filter a custom
# field by value, so gates in marker-field mode filter the results here.
# shellcheck disable=SC2016
_SC_PRINT_IDS='
import json, os, sys
keep = os.environ.get("SC_STATUS_KEEP")
fid = os.environ.get("SC_STATUS_FIELD_ID", "")
allowed = None if keep is None else set(keep.split("|"))
for s in json.load(sys.stdin).get("data", []):
    if allowed is not None:
        vals = [c.get("value", "") for c in s.get("custom_fields") or [] if c.get("field_id") == fid]
        if (vals[0] if vals else "") not in allowed:
            continue
    print(s["id"], s["updated_at"])
'

# shortcut_marker_mode -> success when the status field, not labels, carries
# the assessment markers (status_is_source on and status_field named).
shortcut_marker_mode() {
  [ "${DAIMON_INPUT_STATUS_IS_SOURCE:-0}" = "1" ] && [ -n "${DAIMON_INPUT_STATUS_FIELD:-}" ]
}

# shortcut_field_id "<field name>" -> the custom field's id ("" on any error).
shortcut_field_id() {
  local token; token="$(shortcut_token)"
  [ -z "$token" ] && return
  curl -s "https://api.app.shortcut.com/api/v3/custom-fields" -H "Shortcut-Token: $token" \
    | python3 -c "import sys,json;n=sys.argv[1];print(next((f['id'] for f in json.load(sys.stdin) if f.get('name')==n),''))" "$1" 2>/dev/null
}

# shortcut_marked_ids "<values>" "<base query>" -> shortcut_owner_ids filtered to
# stories whose status field holds one of <values> ("|"-separated, "" = unset).
# Fails closed (stderr, return 1) when the field can't be resolved, so a typo'd
# field name surfaces as a discover_error instead of an empty queue.
shortcut_marked_ids() {
  local fid; fid="$(shortcut_field_id "$DAIMON_INPUT_STATUS_FIELD")"
  if [ -z "$fid" ]; then
    echo "discover: custom field '$DAIMON_INPUT_STATUS_FIELD' not found" >&2
    return 1
  fi
  SC_STATUS_FIELD_ID="$fid" SC_STATUS_KEEP="$1" shortcut_owner_ids "$2"
}


# shortcut_owner_ids "<base query>" -> shortcut_search_ids scoped to
# $DAIMON_INPUT_OWNER (owner, plus requester unless include_requested is off;
# deduped), or workspace-wide if OWNER is unset. Fails closed like shortcut_owner_count when the mention can't resolve.
shortcut_owner_ids() {
  local base="$1"
  if [ -z "${DAIMON_INPUT_OWNER:-}" ]; then shortcut_search_ids "$base"; return; fi
  local mention; mention="$(shortcut_mention "$DAIMON_INPUT_OWNER")"
  if [ -z "$mention" ]; then
    echo "discover: could not resolve owner mention for $DAIMON_INPUT_OWNER" >&2
    return 1
  fi
  {
    shortcut_search_ids "owner:$mention $base"
    if shortcut_include_requested; then shortcut_search_ids "requester:$mention $base"; fi
  } | sort -u
}

# shortcut_labelled_epics "<label>" -> ids of open epics carrying that label, one
# per line (nothing on any error). Stories don't inherit epic labels and the
# story search's label: only matches story labels, so an epic-level opt-in has to
# be resolved to epic ids first.
shortcut_labelled_epics() {
  local token; token="$(shortcut_token)"
  [ -z "$token" ] && return
  curl -s -G "https://api.app.shortcut.com/api/v3/search/epics" \
    --data-urlencode "query=label:\"$1\" !is:done !is:archived" \
    --data-urlencode page_size=250 --data-urlencode detail=slim \
    -H "Shortcut-Token: $token" \
    | python3 -c "import sys,json;[print(e['id']) for e in json.load(sys.stdin).get('data',[])]" 2>/dev/null
}

# shortcut_unseen "<state-file>" -> reads "id updated_at" lines on stdin, prints
# the ids of stories NOT already handled: no record in the state file, or the
# story changed since (updated_at newer than the recorded one). Fractional
# seconds are dropped before comparing so "…28.5Z" vs "…28Z" can't misorder.
shortcut_unseen() {
  local seen="{}"
  if [ -f "$1" ] && jq -e 'type == "object"' "$1" >/dev/null 2>&1; then seen="$(cat "$1")"; fi
  jq -R -r --argjson seen "$seen" '
    def ts: sub("\\.[0-9]+"; "");
    select(length > 0) | split(" ") | .[0] as $id | (.[1] // "" | ts) as $at
    | ($seen[$id].updated_at // "" | ts) as $rec
    | select($rec == "" or $at > $rec) | $id'
}
