"""Pure pricing math. No network. Every step is recorded so the reason can be shown to Ryan."""
import datetime as dt

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def occupancy_factor(rate, cfg):
    if rate is None:
        return 1.0, "occ n/a"
    for step in cfg["occupancy_factors"]["steps"]:
        if rate < step["below"]:
            return step["factor"], f"occ {rate:.0%} x{step['factor']}"
    return 1.0, f"occ {rate:.0%} x1.00"


def lead_factor(days_out, occ_rate, cfg):
    lt = cfg["lead_time_factors"]
    lm = lt["last_minute"]
    if days_out <= lm["days_out"]:
        if occ_rate is not None and occ_rate < lm["low_occ_below"]:
            return lm["low_occ_factor"], f"{days_out}d out, house empty x{lm['low_occ_factor']}"
        if occ_rate is not None and occ_rate > lm["high_occ_above"]:
            return lm["high_occ_factor"], f"{days_out}d out, house full x{lm['high_occ_factor']}"
        return 1.0, f"{days_out}d out x1.00"
    for step in lt["steps"]:
        if days_out <= step["days_out"]:
            return step["factor"], f"{days_out}d out x{step['factor']}"
    return 1.0, f"{days_out}d out x1.00"


def weather_factor(date, days_out, wx, cfg):
    w = cfg["weather"]
    if days_out > w["apply_within_days"] or not wx or "_error" in wx:
        return 1.0, ""
    day = wx.get(date)
    if not day:
        return 1.0, ""
    dow = DOW[dt.date.fromisoformat(date).weekday()]
    if (day.get("rain_prob") or 0) >= w["rain_prob_threshold"]:
        return w["rain_factor"], f"rain {day['rain_prob']}% x{w['rain_factor']}"
    if day.get("high") and day["high"] >= w["nice_temp_min"] and dow in w["nice_days"]:
        return w["nice_factor"], f"nice {dow} {day['high']}° x{w['nice_factor']}"
    return 1.0, ""


def event_factor(date, ev):
    e = (ev or {}).get(date)
    if not e:
        return 1.0, ""
    return e["factor"], f"{e['name']} x{e['factor']}"


def round_price(x, cfg):
    if cfg.get("round_to_nine", True):
        return int(round(x / 10.0) * 10) - 1
    return int(round(x))


def clamp(x, cfg, current=None):
    x = max(cfg["floor"], min(cfg["ceiling"], x))
    mdm = cfg.get("max_daily_move")
    if mdm and current:
        x = max(current - mdm, min(current + mdm, x))
    return x


def price_night(date, today, ref, occ_rate, wx, room, cfg, ev=None):
    """Return dict with recommended price and the reasoning chain."""
    days_out = (dt.date.fromisoformat(date) - dt.date.fromisoformat(today)).days
    steps = []
    base = ref * cfg["comp_position"]
    steps.append(f"comp median ${ref:.0f} x{cfg['comp_position']} = ${base:.0f}")
    f_occ, s = occupancy_factor(occ_rate, cfg); steps.append(s)
    f_lead, s = lead_factor(days_out, occ_rate, cfg); steps.append(s)
    f_wx, s = weather_factor(date, days_out, wx, cfg)
    if s:
        steps.append(s)
    f_ev, s = event_factor(date, ev)
    if s:
        steps.append(s)
    raw = base * f_occ * f_lead * f_wx * f_ev
    price = round_price(raw, cfg) + room.get("offset", 0)
    if room.get("offset"):
        steps.append(f"room {room['room']} +${room['offset']}")
    price = clamp(price, cfg)
    steps.append(f"= ${price}")
    return {"price": price, "raw": round(raw, 2), "days_out": days_out, "reason": " · ".join(steps)}
