"""Builds a fake Hostaway calendar + competitor payload so the engine can be exercised without any API."""
import json, random, datetime as dt, os, sys
random.seed(7)
today = dt.date.today()
cfg = json.load(open("config.json"))
dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(cfg["horizon_days"])]

cal = {}
for room in cfg["rooms"]:
    days = []
    for i, d in enumerate(dates):
        wd = dt.date.fromisoformat(d).weekday()
        booked_p = 0.55 if wd in (4, 5) else 0.2
        booked_p *= max(0.2, 1 - i / 60)
        status = "reserved" if random.random() < booked_p else "available"
        if room["room"] >= 7 and dt.date.fromisoformat(d).month in (11, 12, 1, 2, 3, 4):
            status = "blocked"
        base = 129 if wd in (4, 5) else 109
        if room["room"] >= 7: base += 10
        days.append({"date": d, "status": status, "isAvailable": 0 if status != "available" else 1,
                     "price": base, "minimumStay": 1})
    cal[str(room["id"])] = days
os.makedirs("tests", exist_ok=True)
json.dump(cal, open("tests/mock_calendar.json", "w"))

comps = {"source": "expedia-mock", "sampled_at": dt.datetime.utcnow().isoformat() + "Z", "dates": {}}
sample_dates = dates[:10] + [d for d in dates[10:] if dt.date.fromisoformat(d).weekday() in (4, 5)]
names = [c["match"] for c in cfg["comps"]["comp_set"]]
for d in sample_dates:
    wd = dt.date.fromisoformat(d).weekday()
    mult = 1.5 if wd in (4, 5) else 1.0
    items = [{"n": n, "p": int(random.gauss(125, 30) * mult), "t": "hotel"} for n in names[:18]]
    items += [{"n": "Cozy lakefront cottage", "p": int(random.gauss(180, 40)), "t": "vr"} for _ in range(6)]
    items.append({"n": "The Stargazer`s Retreat at The Cedar", "p": 171, "t": "hotel"})
    comps["dates"][d] = items
json.dump(comps, open("tests/mock_comps.json", "w"))
print("mock written:", len(dates), "dates,", len(sample_dates), "comp samples")
