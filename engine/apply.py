"""Apply APPROVED recommendations to Hostaway. The only script that writes prices.

Env:
  REC_DATE        which recommendations/<date>.json to apply (default: latest)
  APPROVAL_TEXT   e.g. "approve", "approve except rooms 3,5", "approve except Sep 19-20", "approve only 2026-09-19"
  DRY_RUN=1       compute and log, but do not call Hostaway
  MOCK=1          (testing) skip Hostaway entirely
Writes log/<date>-applied.json and appends CHANGELOG.md. Prints a short Markdown result.
"""
import json, os, re, sys, time, datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _parse_dates(text, year_hint):
    """Find dates like 2026-09-19, Sep 19, Sep 19-20, September 19 to 21. Returns set of ISO dates."""
    out = set()
    for m in re.finditer(r"(\d{4}-\d{2}-\d{2})(?:\s*(?:-|to|–)\s*(\d{4}-\d{2}-\d{2}))?", text):
        a = dt.date.fromisoformat(m.group(1)); b = dt.date.fromisoformat(m.group(2)) if m.group(2) else a
        while a <= b:
            out.add(a.isoformat()); a += dt.timedelta(days=1)
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*(?:-|to|–)\s*(?:([A-Za-z]{3,9})\.?\s+)?(\d{1,2}))?", text):
        mon = MONTHS.get(m.group(1)[:3].lower())
        if not mon:
            continue
        a = dt.date(year_hint, mon, int(m.group(2)))
        if a < dt.date.today() - dt.timedelta(days=30):
            a = a.replace(year=year_hint + 1)
        b = a
        if m.group(4):
            mon2 = MONTHS.get(m.group(3)[:3].lower()) if m.group(3) else mon
            b = dt.date(a.year, mon2, int(m.group(4)))
            if b < a:
                b = b.replace(year=a.year + 1)
        while a <= b:
            out.add(a.isoformat()); a += dt.timedelta(days=1)
    return out


def _parse_rooms(text):
    out = set()
    for m in re.finditer(r"rooms?\s+([\d,\s\-and]+)", text, re.I):
        chunk = m.group(1)
        for part in re.split(r"[,\s]+and[,\s]+|,|\s+", chunk.strip()):
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                if a.isdigit() and b.isdigit():
                    out.update(range(int(a), int(b) + 1))
            elif part.isdigit():
                out.add(int(part))
    return out


def parse_approval(text, year_hint):
    """Returns dict(mode='all'|'none', exclude_rooms, exclude_dates, only_dates, only_rooms)."""
    t = (text or "").strip()
    low = t.lower()
    res = {"mode": "none", "exclude_rooms": set(), "exclude_dates": set(), "only_dates": set(), "only_rooms": set()}
    if not low.startswith("approve"):
        return res
    res["mode"] = "all"
    # split into clauses on 'except' / 'only'
    for m in re.finditer(r"(except|only)\s+(.*?)(?=\s+(?:except|only)\s+|$)", low):
        kind, clause = m.group(1), m.group(2)
        rooms = _parse_rooms(clause)
        dates = _parse_dates(clause, year_hint) if not rooms else set()
        if kind == "except":
            res["exclude_rooms"] |= rooms; res["exclude_dates"] |= dates
        else:
            res["only_rooms"] |= rooms; res["only_dates"] |= dates
    return res


def main():
    with open("config.json") as f:
        cfg = json.load(f)
    if not cfg.get("enabled", True):
        print("config.enabled is false — apply refused."); return 2
    rec_date = os.environ.get("REC_DATE", "").strip() or "latest"
    path = f"recommendations/{rec_date}.json"
    if not os.path.exists(path):
        print(f"No recommendation file {path}"); return 2
    with open(path) as f:
        rec = json.load(f)
    rec_date = rec["run_date"]
    age = (dt.date.today() - dt.date.fromisoformat(rec_date)).days
    if age > 2:
        print(f"Recommendations from {rec_date} are {age} days old — refusing to apply stale prices."); return 2
    if os.path.exists(f"log/{rec_date}-applied.json"):
        print(f"Recommendations for {rec_date} were already applied (log/{rec_date}-applied.json exists). Refusing to re-apply."); return 2

    ap = parse_approval(os.environ.get("APPROVAL_TEXT", "approve"), int(rec_date[:4]))
    if ap["mode"] != "all":
        print("Approval text does not start with 'approve' — nothing applied."); return 2

    chosen, excluded = [], []
    for r in rec["recommendations"]:
        keep = True
        if r["room"] in ap["exclude_rooms"] or r["date"] in ap["exclude_dates"]:
            keep = False
        if ap["only_rooms"] and r["room"] not in ap["only_rooms"]:
            keep = False
        if ap["only_dates"] and r["date"] not in ap["only_dates"]:
            keep = False
        # final safety clamp
        r["recommended"] = max(cfg["floor"], min(cfg["ceiling"], int(r["recommended"])))
        (chosen if keep else excluded).append(r)

    by_listing = defaultdict(dict)
    for r in chosen:
        by_listing[r["listing_id"]][r["date"]] = r["recommended"]

    dry = os.environ.get("DRY_RUN") == "1" or os.environ.get("MOCK") == "1"
    verify = {}
    errors = []
    if not dry and chosen:
        from engine.hostaway import Hostaway
        ha = Hostaway()
        for lid, dp in by_listing.items():
            try:
                ha.set_prices(lid, dp)
            except Exception as e:
                errors.append(f"listing {lid}: {e}")
            time.sleep(0.5)
        if not errors:
            time.sleep(45)  # Hostaway needs a moment before reads reflect writes
            for lid, dp in by_listing.items():
                days = ha.calendar(lid, min(dp), max(dp))
                got = {d["date"]: d.get("price") for d in days}
                for d, p in dp.items():
                    ok = got.get(d) is not None and abs(float(got[d]) - float(p)) < 0.01
                    verify[f"{lid}:{d}"] = {"expected": p, "got": got.get(d), "ok": ok}
                time.sleep(0.3)

    n_bad = sum(1 for v in verify.values() if not v["ok"])
    log = {
        "applied_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "rec_date": rec_date, "approval_text": os.environ.get("APPROVAL_TEXT", "approve"),
        "dry_run": dry, "applied": chosen, "excluded": excluded, "errors": errors,
        "verify_failures": n_bad, "verify": verify,
    }
    os.makedirs("log", exist_ok=True)
    suffix = "-dryrun" if dry else "-applied"
    with open(f"log/{rec_date}{suffix}.json", "w") as f:
        json.dump(log, f, indent=1)

    # human-readable changelog line + result text
    ups = sum(1 for r in chosen if r["delta"] and r["delta"] > 0)
    downs = sum(1 for r in chosen if r["delta"] and r["delta"] < 0)
    head = "DRY RUN — nothing sent to Hostaway" if dry else ("Applied to Hostaway" if not errors else "Applied WITH ERRORS")
    md = [f"## {head} — {rec_date}",
          f"{len(chosen)} nights changed ({ups} up, {downs} down), {len(excluded)} excluded by your reply."]
    if errors:
        md.append("Errors: " + "; ".join(errors))
    if verify:
        md.append(f"Verified in Hostaway: {len(verify) - n_bad}/{len(verify)} correct" + (" ⚠️ check the log" if n_bad else " ✅"))
    md.append(f"Undo: run the **Revert prices** workflow with date `{rec_date}` (restores every old price from the log).")
    md_text = "\n".join(md) + "\n"
    with open("CHANGELOG.md", "a") as f:
        f.write(f"\n### {log['applied_at_utc']} — {head} ({rec_date}): {len(chosen)} nights\n")
        for r in sorted(chosen, key=lambda r: (r['date'], r['room'])):
            f.write(f"- {r['date']} room {r['room']}: ${r['current']} → ${r['recommended']} — {r['reason']}\n")
    with open("log/last_result.md", "w") as f:
        f.write(md_text)
    print(md_text)
    return 0 if not errors and n_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
