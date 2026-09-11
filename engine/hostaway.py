"""Thin Hostaway API client. Reads the calendar; writes nightly prices ONLY (never availability or min-stay)."""
import os, time, json, datetime as dt
import requests

BASE = "https://api.hostaway.com/v1"


class Hostaway:
    def __init__(self, account_id=None, api_key=None):
        # Tolerate the usual copy/paste slips in the GitHub secret boxes: stray spaces,
        # newlines, quotes, or a pasted "HOSTAWAY_API_KEY=..." line.
        clean = lambda v: (v or "").strip().strip("\"'").split("=")[-1].strip().strip("\"'")
        self.account_id = clean(account_id or os.environ.get("HOSTAWAY_ACCOUNT_ID"))
        self.api_key = clean(api_key or os.environ.get("HOSTAWAY_API_KEY"))
        if not self.account_id or not self.api_key:
            raise RuntimeError("HOSTAWAY_ACCOUNT_ID / HOSTAWAY_API_KEY are not set (GitHub secrets).")
        self.token = self._get_token()
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {self.token}", "Cache-control": "no-cache"})

    def _get_token(self):
        r = requests.post(
            f"{BASE}/accessTokens",
            headers={"Content-type": "application/x-www-form-urlencoded", "Cache-control": "no-cache"},
            data={"grant_type": "client_credentials", "client_id": self.account_id,
                  "client_secret": self.api_key, "scope": "general"},
            timeout=30,
        )
        r.raise_for_status()
        tok = r.json()["access_token"]
        time.sleep(1.5)  # Hostaway: token valid 1s after issue
        return tok

    def _get(self, path, params=None):
        for attempt in range(4):
            r = self.s.get(f"{BASE}{path}", params=params, timeout=60)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1)); continue
            r.raise_for_status()
            j = r.json()
            if j.get("status") != "success":
                raise RuntimeError(f"Hostaway error on {path}: {j}")
            return j["result"]
        raise RuntimeError(f"Hostaway rate-limited repeatedly on {path}")

    def listings(self):
        return self._get("/listings", {"limit": 100})

    def calendar(self, listing_id, start, end):
        """Returns list of day dicts: date, status, price, isAvailable, minimumStay ..."""
        return self._get(f"/listings/{listing_id}/calendar",
                         {"startDate": start, "endDate": end, "includeResources": 0})

    def set_prices(self, listing_id, date_prices):
        """date_prices: {'YYYY-MM-DD': price}. Sends ONLY price per single-day interval (max 200 per call)."""
        items = [{"startDate": d, "endDate": d, "price": float(p)} for d, p in sorted(date_prices.items())]
        results = []
        for i in range(0, len(items), 200):
            chunk = items[i:i + 200]
            for attempt in range(4):
                r = self.s.put(f"{BASE}/listings/{listing_id}/calendarIntervals",
                               headers={"Content-type": "application/json"},
                               data=json.dumps(chunk), timeout=120)
                if r.status_code == 429:
                    time.sleep(3 * (attempt + 1)); continue
                break
            r.raise_for_status()
            j = r.json()
            if j.get("status") != "success":
                raise RuntimeError(f"Hostaway price write failed for {listing_id}: {j}")
            results.append(j)
        return results


def read_all_calendars(ha, rooms, start, end):
    """-> {listing_id: {date: day_dict}}"""
    out = {}
    for room in rooms:
        days = ha.calendar(room["id"], start, end)
        out[room["id"]] = {d["date"]: d for d in days}
        time.sleep(0.3)
    return out


def occupancy_by_date(calendars, dates):
    """occupancy = booked / open rooms (owner-blocked rooms don't count as capacity)."""
    booked_status = {"reserved", "pending", "mreserved"}
    blocked_status = {"blocked", "hardBlock", "mblocked"}
    occ = {}
    for d in dates:
        booked = capacity = 0
        for lid, cal in calendars.items():
            day = cal.get(d)
            if not day:
                continue
            st = day.get("status")
            if st in blocked_status:
                continue
            capacity += 1
            if st in booked_status or (day.get("isAvailable") == 0):
                booked += 1
        occ[d] = {"booked": booked, "capacity": capacity,
                  "rate": (booked / capacity) if capacity else None}
    return occ
