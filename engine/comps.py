"""Competitor rate store.

Input format (what the morning Chrome pass hands over, via the workflow's comps_json input):
{
  "source": "expedia",
  "sampled_at": "2026-09-12T10:31:00Z",
  "dates": {
    "2026-09-19": [ {"n": "Cedar Point's Express Hotel", "p": 186, "t": "hotel"}, ... ],
    ...
  }
}
"p" = nightly price before taxes; "t" = "hotel" | "vr" (vacation rental) | omitted.

The store (data/comps/store.json) keeps, per date, the matched named comps + a vacation-rental summary.
"""
import json, os, re, statistics, datetime as dt

STORE_PATH = "data/comps/store.json"


def load_store():
    if os.path.exists(STORE_PATH):
        with open(STORE_PATH) as f:
            return json.load(f)
    return {}


def save_store(store, today):
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=3)).isoformat()
    store = {d: v for d, v in store.items() if d >= cutoff}
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(store, f, indent=1, sort_keys=True)
    return store


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def match_comp(name, cfg):
    n = _norm(name)
    for pat in cfg["exclude_name_patterns"]:
        if _norm(pat) in n:
            return None
    for c in cfg["comp_set"]:
        if _norm(c["match"]) in n:
            return c
    return None


def ingest(store, payload, cfg):
    """Merge a comps payload into the store. Returns list of dates ingested."""
    sampled_at = payload.get("sampled_at") or dt.datetime.utcnow().isoformat() + "Z"
    source = payload.get("source", "unknown")
    done = []
    for date, props in (payload.get("dates") or {}).items():
        matched, vr = [], []
        seen = set()
        for p in props:
            name, price = p.get("n"), p.get("p")
            if not name or not isinstance(price, (int, float)) or price <= 0:
                continue
            c = match_comp(name, cfg)
            if c:
                key = _norm(c["match"])
                if key in seen:
                    continue  # first (usually cheapest displayed) wins
                seen.add(key)
                matched.append({"name": c["match"], "segment": c["segment"], "price": round(float(price))})
            elif p.get("t") == "vr":
                lo, hi = cfg["vacation_rental_range"]
                if lo <= price <= hi:
                    vr.append(round(float(price)))
        store[date] = {
            "sampled_at": sampled_at, "source": source,
            "comps": matched,
            "vr_median": statistics.median(vr) if vr else None,
            "vr_count": len(vr),
            "total_listed": len(props),
        }
        done.append(date)
    return done


def _median_of(comps):
    prices = [c["price"] for c in comps]
    return statistics.median(prices) if prices else None


def _segment_medians(comps):
    segs = {}
    for c in comps:
        segs.setdefault(c["segment"], []).append(c["price"])
    return {k: statistics.median(v) for k, v in segs.items()}


def _is_weekend(date):
    return dt.date.fromisoformat(date).weekday() in (4, 5)  # Fri, Sat nights


def reference_for(date, today, store, cfg):
    """Return (ref_price, info) for a night, or (None, reason). Uses a direct sample if fresh,
    otherwise interpolates from the nearest fresh sample of the same day-type (weekend vs weekday)."""
    t = dt.date.fromisoformat(today)
    d = dt.date.fromisoformat(date)
    days_out = (d - t).days
    max_age = cfg["max_sample_age_days_near"] if days_out <= cfg["near_means_within_days"] else cfg["max_sample_age_days_far"]
    lo, hi = cfg["sane_median_range"]

    def usable(entry):
        if not entry or len(entry.get("comps", [])) < cfg["min_comps_for_valid_median"]:
            return False
        age = (dt.datetime.utcnow() - dt.datetime.fromisoformat(entry["sampled_at"].replace("Z", ""))).days
        if age > max_age:
            return False
        m = _median_of(entry["comps"])
        return m is not None and lo <= m <= hi

    direct = store.get(date)
    if usable(direct):
        m = _median_of(direct["comps"])
        return m, {"kind": "direct", "sample_date": date, "n": len(direct["comps"]),
                   "segments": _segment_medians(direct["comps"]), "vr_median": direct.get("vr_median"),
                   "sampled_at": direct["sampled_at"], "source": direct.get("source")}

    # interpolate: nearest usable sample with same day-type within window
    best = None
    for k in range(1, cfg["interpolate_window_days"] + 1):
        for cand in (d - dt.timedelta(days=k), d + dt.timedelta(days=k)):
            cs = cand.isoformat()
            if cs < today or _is_weekend(cs) != _is_weekend(date):
                continue
            e = store.get(cs)
            if usable(e):
                best = (cs, e); break
        if best:
            break
    if best:
        cs, e = best
        m = _median_of(e["comps"])
        return m, {"kind": "interpolated", "sample_date": cs, "n": len(e["comps"]),
                   "segments": _segment_medians(e["comps"]), "vr_median": e.get("vr_median"),
                   "sampled_at": e["sampled_at"], "source": e.get("source")}
    return None, {"kind": "none", "reason": "no fresh competitor sample within window"}


# ---------- optional cloud backup: SerpApi Google Hotels ----------
def serpapi_sample(dates, cfg, api_key):
    """Fetch Google Hotels results for each date; returns a payload in the standard input format."""
    import requests
    out = {"source": "serpapi_google_hotels", "sampled_at": dt.datetime.utcnow().isoformat() + "Z", "dates": {}}
    for date in dates:
        nxt = (dt.date.fromisoformat(date) + dt.timedelta(days=1)).isoformat()
        try:
            r = requests.get("https://serpapi.com/search.json", params={
                "engine": "google_hotels", "q": cfg["query"], "check_in_date": date, "check_out_date": nxt,
                "adults": 2, "currency": "USD", "gl": "us", "hl": "en", "api_key": api_key}, timeout=60)
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            print(f"serpapi failed for {date}: {e}")
            continue
        props = []
        for p in j.get("properties", []) + j.get("ads", []):
            price = (p.get("rate_per_night") or {}).get("extracted_lowest") or p.get("extracted_price")
            if price:
                props.append({"n": p.get("name"), "p": price,
                              "t": "vr" if p.get("type") == "vacation rental" else "hotel"})
        out["dates"][date] = props
    return out


def serpapi_pick_dates(today, horizon, store, budget):
    """Tonight, tomorrow, next two Fri+Sat, then the stalest remaining dates."""
    t = dt.date.fromisoformat(today)
    picks = [t, t + dt.timedelta(days=1)]
    d = t + dt.timedelta(days=1)
    while len([p for p in picks if p.weekday() in (4, 5)]) < 4 and (d - t).days < horizon:
        if d.weekday() in (4, 5) and d not in picks:
            picks.append(d)
        d += dt.timedelta(days=1)
    rest = [t + dt.timedelta(days=i) for i in range(horizon)]
    rest = [x for x in rest if x not in picks]
    rest.sort(key=lambda x: store.get(x.isoformat(), {}).get("sampled_at", ""))
    picks += rest
    return [p.isoformat() for p in picks[:budget]]
