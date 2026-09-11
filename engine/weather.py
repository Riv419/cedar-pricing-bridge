"""National Weather Service forecast for Bay View, OH -> {date: {high, rain_prob, short}} for ~7 days."""
import datetime as dt
import requests


def fetch_forecast(url):
    try:
        r = requests.get(url, headers={"User-Agent": "cedar-pricing-bridge (stayatthecedar.com)",
                                       "Accept": "application/geo+json"}, timeout=30)
        r.raise_for_status()
        periods = r.json()["properties"]["periods"]
    except Exception as e:  # weather is optional; never block pricing on it
        return {"_error": str(e)}
    out = {}
    for p in periods:
        date = p["startTime"][:10]
        day = out.setdefault(date, {"high": None, "rain_prob": 0, "short": ""})
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
        day["rain_prob"] = max(day["rain_prob"], pop)
        if p.get("isDaytime"):
            day["high"] = p.get("temperature")
            day["short"] = p.get("shortForecast", "")
        elif day["high"] is None:
            day["high"] = p.get("temperature")
            day["short"] = day["short"] or p.get("shortForecast", "")
    return out
