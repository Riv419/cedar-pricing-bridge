"""Build the day's price recommendations. NEVER writes to Hostaway.

Env:
  HOSTAWAY_ACCOUNT_ID, HOSTAWAY_API_KEY   (GitHub secrets)
  COMPS_JSON     optional: competitor payload handed over by the morning Chrome pass
  COMPS_FILE     optional: same, as a file path
  SERPAPI_KEY    optional: cloud backup (only used if config.serpapi.enabled)
  RUN_DATE       optional: YYYY-MM-DD (testing)
  MOCK_CALENDAR  optional: path to a JSON {listing_id: [day dicts]} instead of calling Hostaway (testing)
  ONLY_IF_MISSING=1  exit quietly if today's recommendation file already exists (used by the cron fallback)
"""
import json, os, sys, datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import comps as C, pricing as P, weather as W
from engine.summary import render_md


def load_config():
    with open("config.json") as f:
        return json.load(f)


def main():
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    today = os.environ.get("RUN_DATE") or dt.datetime.now(tz).date().isoformat()
    out_json = f"recommendations/{today}.json"
    if os.environ.get("ONLY_IF_MISSING") == "1" and os.path.exists(out_json):
        print(f"{out_json} already exists; nothing to do."); return 0

    horizon = cfg["horizon_days"]
    dates = [(dt.date.fromisoformat(today) + dt.timedelta(days=i)).isoformat() for i in range(horizon)]
    notes = []

    # 1. competitor rates
    store = C.load_store()
    payload = None
    if os.environ.get("COMPS_JSON", "").strip():
        payload = json.loads(os.environ["COMPS_JSON"])
    elif os.environ.get("COMPS_FILE") and os.path.exists(os.environ["COMPS_FILE"]):
        with open(os.environ["COMPS_FILE"]) as f:
            payload = json.load(f)
    if payload:
        done = C.ingest(store, payload, cfg["comps"])
        notes.append(f"Ingested {len(done)} sampled dates from {payload.get('source','?')}.")
    elif cfg["serpapi"]["enabled"] and os.environ.get("SERPAPI_KEY"):
        picks = C.serpapi_pick_dates(today, horizon, store, cfg["serpapi"]["daily_budget"])
        payload = C.serpapi_sample(picks, cfg["serpapi"], os.environ["SERPAPI_KEY"])
        done = C.ingest(store, payload, cfg["comps"])
        notes.append(f"SerpApi backup sampled {len(done)} dates.")
    else:
        notes.append("No new competitor sample today; using stored samples where still fresh.")
    store = C.save_store(store, today)

    # 2. Hostaway calendar + occupancy
    if os.environ.get("MOCK_CALENDAR"):
        with open(os.environ["MOCK_CALENDAR"]) as f:
            raw = json.load(f)
        calendars = {int(k): {d["date"]: d for d in v} for k, v in raw.items()}
    else:
        from engine.hostaway import Hostaway, read_all_calendars
        ha = Hostaway()
        calendars = read_all_calendars(ha, cfg["rooms"], dates[0], dates[-1])
    from engine.hostaway import occupancy_by_date
    occ = occupancy_by_date(calendars, dates)
    os.makedirs("data/calendar", exist_ok=True)
    with open("data/calendar/latest.json", "w") as f:
        json.dump({"as_of": today, "occupancy": occ,
                   "prices": {str(lid): {d: cal[d].get("price") for d in dates if d in cal} for lid, cal in calendars.items()},
                   "status": {str(lid): {d: cal[d].get("status") for d in dates if d in cal} for lid, cal in calendars.items()}},
                  f, indent=1)

    # 3. weather
    wx = W.fetch_forecast(cfg["weather"]["nws_forecast_url"])
    os.makedirs("data/weather", exist_ok=True)
    with open("data/weather/latest.json", "w") as f:
        json.dump({"as_of": today, "forecast": wx}, f, indent=1)

    # 4. price every open night
    recs, skipped_dates, unchanged = [], {}, 0
    booked_status = {"reserved", "pending", "mreserved"}
    blocked_status = {"blocked", "hardBlock", "mblocked"}
    date_info = {}
    for d in dates:
        ref, info = C.reference_for(d, today, store, cfg["comps"])
        date_info[d] = {"ref": ref, "comp": info, "occ": occ.get(d), "wx": wx.get(d) if isinstance(wx, dict) else None}
        if ref is None:
            skipped_dates[d] = info.get("reason", "no comp data"); continue
        for room in cfg["rooms"]:
            day = calendars.get(room["id"], {}).get(d)
            if not day:
                continue
            st = day.get("status")
            if st in booked_status or st in blocked_status or day.get("isAvailable") == 0:
                continue
            cur = day.get("price")
            res = P.price_night(d, today, ref, (occ.get(d) or {}).get("rate"), wx, room, cfg)
            new = res["price"]
            if cfg.get("max_daily_move") and cur:
                new = P.clamp(new, cfg, cur)
            if cur is not None and abs(new - cur) < cfg["min_change"]:
                unchanged += 1; continue
            recs.append({"date": d, "listing_id": room["id"], "room": room["room"], "name": room["name"],
                         "current": cur, "recommended": new, "delta": (new - cur) if cur is not None else None,
                         "reason": res["reason"], "comp_ref": ref, "comp_kind": info["kind"],
                         "comp_sample_date": info.get("sample_date"), "occupancy": (occ.get(d) or {}).get("rate"),
                         "days_out": res["days_out"]})

    result = {
        "generated_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "run_date": today, "horizon_days": horizon,
        "floor": cfg["floor"], "ceiling": cfg["ceiling"], "comp_position": cfg["comp_position"],
        "notes": notes,
        "counts": {"changes": len(recs), "unchanged_open_nights": unchanged, "dates_skipped_no_comps": len(skipped_dates)},
        "skipped_dates": skipped_dates,
        "date_info": {d: v for d, v in date_info.items() if v["ref"] is not None or d in skipped_dates},
        "recommendations": recs,
        "status": "recommendations" if recs else ("skipped" if not date_info or all(v["ref"] is None for v in date_info.values()) else "no_changes"),
    }
    os.makedirs("recommendations", exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(result, f, indent=1)
    md = render_md(result, cfg)
    with open(f"recommendations/{today}.md", "w") as f:
        f.write(md)
    with open("recommendations/latest.json", "w") as f:
        json.dump(result, f, indent=1)
    with open("recommendations/latest.md", "w") as f:
        f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
