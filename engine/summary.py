"""Render the mobile-friendly Markdown summary that Ryan reads each morning."""
import datetime as dt
from collections import defaultdict

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _fmt_date(d):
    x = dt.date.fromisoformat(d)
    return f"{DOW[x.weekday()]} {x.strftime('%b')} {x.day}"


def _room_groups(items):
    """Collapse rooms with identical current->new into 'Rooms 1-6: $129 -> $149'."""
    groups = defaultdict(list)
    for r in items:
        groups[(r["current"], r["recommended"])].append(r["room"])
    lines = []
    for (cur, new), rooms in sorted(groups.items(), key=lambda kv: min(kv[1])):
        rooms = sorted(rooms)
        # compress consecutive runs
        runs, start, prev = [], rooms[0], rooms[0]
        for n in rooms[1:]:
            if n == prev + 1:
                prev = n; continue
            runs.append(f"{start}-{prev}" if start != prev else f"{start}"); start = prev = n
        runs.append(f"{start}-{prev}" if start != prev else f"{start}")
        label = "Room" if len(rooms) == 1 else "Rooms"
        cur_s = f"${cur:.0f}" if cur is not None else "—"
        arrow = "▲" if (cur is not None and new > cur) else "▼"
        lines.append(f"{label} {', '.join(runs)}: {cur_s} → **${new}** {arrow}")
    return lines


def render_md(res, cfg):
    d = res["run_date"]
    L = [f"# Cedar pricing — {_fmt_date(d)}, {d[:4]}", ""]
    for n in res["notes"]:
        L.append(f"_{n}_")
    c = res["counts"]
    di = res["date_info"]
    # occupancy pacing
    def pacing(n):
        rates = [v["occ"]["rate"] for k, v in di.items() if v.get("occ") and v["occ"]["rate"] is not None
                 and 0 <= (dt.date.fromisoformat(k) - dt.date.fromisoformat(d)).days < n]
        return f"{sum(rates)/len(rates):.0%}" if rates else "n/a"
    cap = f" · max move ${cfg['max_daily_move']}/day" if cfg.get("max_daily_move") else ""
    L.append(f"Occupancy: next 7 nights **{pacing(7)}** · next 30 **{pacing(30)}** · floor ${cfg['floor']} / ceiling ${cfg['ceiling']}{cap} · target {cfg['comp_position']:.0%} of comp median")
    L.append("")
    if res["status"] == "skipped":
        L.append("**SKIPPED — no usable competitor data today.** Nothing to approve.")
        return "\n".join(L) + "\n"
    if not res["recommendations"]:
        L.append("**No changes recommended today** — current prices already match the rules.")
        L.append("")
    else:
        L.append(f"## {c['changes']} price changes across {len({r['date'] for r in res['recommendations']})} nights")
        L.append("")
        by_date = defaultdict(list)
        for r in res["recommendations"]:
            by_date[r["date"]].append(r)
        for date in sorted(by_date):
            info = di.get(date, {})
            comp = info.get("comp") or {}
            occ = info.get("occ") or {}
            wx = info.get("wx") or {}
            bits = [f"comp ${info.get('ref', 0):.0f}" + (" (est.)" if comp.get("kind") == "interpolated" else "")]
            if occ.get("rate") is not None:
                bits.append(f"occ {occ['rate']:.0%} ({occ['booked']}/{occ['capacity']})")
            if wx and wx.get("high"):
                bits.append(f"{wx.get('short','')} {wx['high']}°" + (f", rain {wx['rain_prob']}%" if wx.get("rain_prob") else ""))
            segs = comp.get("segments") or {}
            if "cedar_point" in segs:
                bits.append(f"Breakers Express ${segs['cedar_point']:.0f}")
            if comp.get("vr_median"):
                bits.append(f"VR median ${comp['vr_median']:.0f}")
            if info.get("event"):
                bits.append(f"🎟 {info['event']['name']} ({info['event']['impact']})")
            L.append(f"**{_fmt_date(date)}** — " + " · ".join(bits))
            for line in _room_groups(by_date[date]):
                L.append(f"- {line}")
            L.append("")
    if res["skipped_dates"]:
        ds = sorted(res["skipped_dates"])
        L.append(f"_Skipped {len(ds)} nights with no competitor data: {_fmt_date(ds[0])} … {_fmt_date(ds[-1])}_")
        L.append("")
    L.append("---")
    gate = res.get("auto_apply") or {}
    if gate.get("eligible"):
        L.append(f"**Applying automatically** ({gate.get('reason','')}). Undo a day: run *3 - Revert prices* with date {d}.")
    elif (cfg.get("auto_apply") or {}).get("enabled"):
        L.append(f"**Not applied — {gate.get('reason','')}.** To push them anyway, reply **approve** (or **approve except rooms 3,5**, **approve except {_fmt_date(d)}**).")
    else:
        L.append("Reply **approve** · **approve except rooms 3,5** · **approve except " + _fmt_date(d) + "** · **approve only " + _fmt_date(d) + "** · **skip**")
    return "\n".join(L) + "\n"
