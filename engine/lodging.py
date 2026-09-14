"""Pull The Cedar's lodging numbers from Hostaway and write data/lodging/latest.json.

READ-ONLY: never writes to Hostaway.

What it produces (for Ryan's nightly wrap and on-demand "how's the Cedar" asks):
  tonight        rooms occupied / capacity, revenue for tonight's stays by channel
  arrivals       who is checking in today   (room, channel, nights, guests — no names)
  departures     who is leaving tomorrow    (same)
  next_7_nights  occupancy + booked revenue per night, and totals
  month_to_date  room-nights sold and revenue so far this month (occupancy basis)

"Tonight" follows the bars' 4 AM Eastern rollover: a run at 12:50 AM still
reports the night that's in progress.

Revenue is on an OCCUPANCY basis: a reservation's total guest price is spread
evenly across its nights (total ÷ nights). "total" is what the guest pays,
including cleaning fees and taxes, because that's the number Hostaway makes
reliable across every channel. Owner stays count as occupied but $0.

Guest names are deliberately NOT written — this repo is public.

Env: HOSTAWAY_ACCOUNT_ID, HOSTAWAY_API_KEY (GitHub secrets)
     RUN_AT  optional ISO datetime in Eastern for testing, e.g. 2026-09-14T00:50
     MOCK_RESERVATIONS optional path to a JSON list of reservation dicts (testing)
"""
import json, os, sys, time, datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.hostaway import Hostaway

ET = ZoneInfo("America/New_York")
OUT = "data/lodging/latest.json"

# Hostaway statuses that mean "this room is taken that night".
OCCUPYING = {"new", "modified", "ownerStay"}
# Pretty names for Hostaway channel identifiers.
# (keys are lowercase; lookup is case-insensitive)
CHANNEL_NAMES = {
    "airbnb": "Airbnb", "airbnbofficial": "Airbnb", "bookingcom": "Booking.com",
    "expedia": "Expedia", "vrbo": "Vrbo", "homeaway": "Vrbo",
    "bookingengine": "Direct (website)", "direct": "Direct (manual)", "manual": "Direct (manual)",
    "ownerstay": "Owner stay",
}


def channel_label(r):
    name = (r.get("channelName") or "").strip()
    if r.get("status") == "ownerStay":
        return "Owner stay"
    return CHANNEL_NAMES.get(name.lower(), name.title() if name else "Direct (manual)")


def night_date(now_et):
    """The night in progress: before 4 AM ET it's still 'last night'."""
    d = now_et.date()
    return d - dt.timedelta(days=1) if now_et.time() < dt.time(4, 0) else d


def fetch_reservations(ha, dep_from, arr_to):
    """All reservations departing on/after dep_from and arriving on/before arr_to."""
    out, offset = [], 0
    while True:
        page = ha._get("/reservations", {
            "limit": 100, "offset": offset,
            "departureStartDate": dep_from.isoformat(),
            "arrivalEndDate": arr_to.isoformat(),
            "sortOrder": "arrivalDate",
        })
        out.extend(page or [])
        if not page or len(page) < 100:
            break
        offset += 100
        time.sleep(0.3)
    return out


def per_night(r):
    nights = r.get("nights") or 0
    if not nights:
        a, d = dt.date.fromisoformat(r["arrivalDate"]), dt.date.fromisoformat(r["departureDate"])
        nights = max((d - a).days, 1)
    if r.get("status") == "ownerStay":
        return 0.0, nights
    return round(float(r.get("totalPrice") or 0) / nights, 2), nights


def stays_on(reservations, night):
    n = night.isoformat()
    return [r for r in reservations
            if r.get("status") in OCCUPYING and r.get("arrivalDate") <= n < r.get("departureDate")]


def brief(r, rooms_by_id):
    room = rooms_by_id.get(r.get("listingMapId"), {})
    rev, nights = per_night(r)
    return {
        "room": room.get("room"), "room_name": room.get("name"),
        "channel": channel_label(r), "nights": nights,
        "guests": r.get("numberOfGuests") or r.get("adults"),
        "arrival": r.get("arrivalDate"), "departure": r.get("departureDate"),
        "total": round(float(r.get("totalPrice") or 0), 2), "per_night": rev,
    }


def night_summary(reservations, night, rooms_by_id, capacity):
    stays = stays_on(reservations, night)
    by_channel = defaultdict(lambda: {"rooms": 0, "revenue": 0.0})
    revenue = 0.0
    for r in stays:
        rev, _ = per_night(r)
        ch = channel_label(r)
        by_channel[ch]["rooms"] += 1
        by_channel[ch]["revenue"] = round(by_channel[ch]["revenue"] + rev, 2)
        revenue += rev
    paying = [r for r in stays if r.get("status") != "ownerStay"]
    return {
        "date": night.isoformat(),
        "dow": night.strftime("%a"),
        "occupied": len(stays), "capacity": capacity,
        "occupancy_pct": round(100 * len(stays) / capacity) if capacity else None,
        "revenue": round(revenue, 2),
        "adr": round(revenue / len(paying), 2) if paying else 0.0,
        "by_channel": dict(sorted(by_channel.items())),
    }


def build(reservations, now_et, rooms):
    rooms_by_id = {r["id"]: r for r in rooms}
    capacity = len(rooms)
    tonight = night_date(now_et)
    tomorrow = tonight + dt.timedelta(days=1)
    month_start = tonight.replace(day=1)

    arrivals = [brief(r, rooms_by_id) for r in reservations
                if r.get("status") in OCCUPYING and r.get("arrivalDate") == tonight.isoformat()]
    departures = [brief(r, rooms_by_id) for r in reservations
                  if r.get("status") in OCCUPYING and r.get("departureDate") == tomorrow.isoformat()]
    week = [night_summary(reservations, tonight + dt.timedelta(days=i), rooms_by_id, capacity) for i in range(7)]

    mtd_nights = mtd_rev = 0.0
    mtd_channels = defaultdict(lambda: {"room_nights": 0, "revenue": 0.0})
    d = month_start
    while d <= tonight:
        for r in stays_on(reservations, d):
            rev, _ = per_night(r)
            ch = channel_label(r)
            mtd_nights += 1; mtd_rev += rev
            mtd_channels[ch]["room_nights"] += 1
            mtd_channels[ch]["revenue"] = round(mtd_channels[ch]["revenue"] + rev, 2)
        d += dt.timedelta(days=1)
    days_so_far = (tonight - month_start).days + 1

    return {
        "generated_at_et": now_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "property": "The Cedar (Bay View Lodging)",
        "night": tonight.isoformat(),
        "capacity": capacity,
        "revenue_basis": "occupancy basis: guest total (incl. fees & tax) ÷ nights; owner stays = $0",
        "tonight": week[0],
        "arrivals_today": sorted(arrivals, key=lambda x: (x["room"] or 99)),
        "departures_tomorrow": sorted(departures, key=lambda x: (x["room"] or 99)),
        "next_7_nights": week,
        "next_7_totals": {
            "room_nights": sum(n["occupied"] for n in week),
            "capacity": capacity * 7,
            "occupancy_pct": round(100 * sum(n["occupied"] for n in week) / (capacity * 7)) if capacity else None,
            "revenue": round(sum(n["revenue"] for n in week), 2),
        },
        "month_to_date": {
            "month": month_start.strftime("%Y-%m"),
            "through": tonight.isoformat(),
            "room_nights": int(mtd_nights),
            "capacity": capacity * days_so_far,
            "occupancy_pct": round(100 * mtd_nights / (capacity * days_so_far)) if capacity else None,
            "revenue": round(mtd_rev, 2),
            "by_channel": dict(sorted(mtd_channels.items())),
        },
        "errors": [],
    }


def main():
    with open("config.json") as f:
        cfg = json.load(f)
    rooms = cfg["rooms"]
    now_et = (dt.datetime.fromisoformat(os.environ["RUN_AT"]).replace(tzinfo=ET)
              if os.environ.get("RUN_AT") else dt.datetime.now(ET))
    tonight = night_date(now_et)
    dep_from = tonight.replace(day=1)              # covers month-to-date
    arr_to = tonight + dt.timedelta(days=8)        # covers the 7-night outlook + departures

    try:
        if os.environ.get("MOCK_RESERVATIONS"):
            with open(os.environ["MOCK_RESERVATIONS"]) as f:
                reservations = json.load(f)
        else:
            ha = Hostaway()
            reservations = fetch_reservations(ha, dep_from, arr_to)
        result = build(reservations, now_et, rooms)
    except Exception as e:
        result = {
            "generated_at_et": now_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "property": "The Cedar (Bay View Lodging)", "night": tonight.isoformat(),
            "errors": [f"{type(e).__name__}: {e}"],
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)
    t = result.get("tonight") or {}
    print(f"night {result['night']}: occupied {t.get('occupied')}/{t.get('capacity')} "
          f"revenue ${t.get('revenue')} errors={result['errors']}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
