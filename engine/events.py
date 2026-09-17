"""Event calendar -> per-night demand factor.

Where events come from: Claude's morning web search (Cedar Point open days / HalloWeekends / closures, Sandusky and
Port Clinton festivals, concerts, holidays) handed over as the workflow input `events_json`, or the last saved
data/events/latest.json if nothing new was handed over today.

Input format:
{
  "as_of": "2026-09-17",
  "source": "claude web search",
  "events": [
    {"date": "2026-10-10", "name": "Cedar Point HalloWeekends", "impact": "high"},
    {"start": "2026-11-27", "end": "2026-11-28", "name": "Thanksgiving weekend", "impact": "medium", "note": "..."},
    {"date": "2026-11-10", "name": "Cedar Point closed (weekday)", "impact": "soft"}
  ]
}
impact: low | medium | high | soft (soft = expected dead night, small discount). Multipliers live in config.json.
If several events land on one night the strongest positive one wins; "soft" only applies when nothing positive is on.
"""
import json, os, datetime as dt

VALID = ("low", "medium", "high", "soft")


def _expand(ev):
    a = ev.get("start") or ev.get("date")
    b = ev.get("end") or ev.get("date") or a
    if not a:
        return []
    a, b = dt.date.fromisoformat(a[:10]), dt.date.fromisoformat(b[:10])
    if b < a:
        a, b = b, a
    if (b - a).days > 31:  # a "season" is not an event; ignore rather than price 90 nights off one line
        return []
    out = []
    while a <= b:
        out.append(a.isoformat()); a += dt.timedelta(days=1)
    return out


def load(cfg, today):
    """Returns (by_date, notes). by_date = {date: {"name", "impact", "factor"}}. Never raises."""
    ecfg = cfg.get("events") or {}
    path = ecfg.get("file", "data/events/latest.json")
    notes = []
    payload = None
    raw = os.environ.get("EVENTS_JSON", "").strip()
    try:
        if raw:
            payload = json.loads(raw)
            payload.setdefault("as_of", today)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(payload, f, indent=1)
            notes.append(f"Events: {len(payload.get('events') or [])} from today's search.")
        elif os.environ.get("EVENTS_FILE") and os.path.exists(os.environ["EVENTS_FILE"]):
            with open(os.environ["EVENTS_FILE"]) as f:
                payload = json.load(f)
        elif os.path.exists(path):
            with open(path) as f:
                payload = json.load(f)
            age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(str(payload.get("as_of", "2000-01-01"))[:10])).days
            if age > ecfg.get("max_age_days", 3):
                notes.append(f"Events list is {age} days old — ignored until a fresh search lands.")
                payload = None
            else:
                notes.append(f"Events: using the list from {payload.get('as_of')} (no new search today).")
        else:
            notes.append("No events list — pricing without events.")
    except Exception as e:  # events are optional; never block pricing on them
        notes.append(f"Events list unreadable ({e}) — pricing without events.")
        payload = None

    factors = ecfg.get("factors") or {}
    by_date = {}
    for ev in (payload or {}).get("events") or []:
        impact = str(ev.get("impact", "")).lower()
        if impact not in VALID or impact not in factors:
            continue
        for d in _expand(ev):
            cur = by_date.get(d)
            f = factors[impact]
            if cur is None or (f > 1.0 and f > cur["factor"]) or (cur["factor"] < 1.0 and f > 1.0):
                by_date[d] = {"name": str(ev.get("name", "event"))[:60], "impact": impact, "factor": f}
    return by_date, notes
