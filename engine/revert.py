"""Undo: restore the OLD prices recorded in log/<date>-applied.json. Env: REC_DATE (required)."""
import json, os, sys, time, datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    d = os.environ.get("REC_DATE", "").strip()
    path = f"log/{d}-applied.json"
    if not d or not os.path.exists(path):
        print(f"No applied log at {path}"); return 2
    with open(path) as f:
        log = json.load(f)
    if log.get("dry_run"):
        print("That log was a dry run; nothing to revert."); return 2
    by_listing = defaultdict(dict)
    for r in log["applied"]:
        if r.get("current") is not None:
            by_listing[r["listing_id"]][r["date"]] = r["current"]
    from engine.hostaway import Hostaway
    ha = Hostaway()
    n = 0
    for lid, dp in by_listing.items():
        ha.set_prices(lid, dp); n += len(dp); time.sleep(0.5)
    with open(f"log/{d}-reverted.json", "w") as f:
        json.dump({"reverted_at_utc": dt.datetime.utcnow().isoformat() + "Z", "restored": by_listing}, f, indent=1)
    with open("CHANGELOG.md", "a") as f:
        f.write(f"\n### {dt.datetime.utcnow().isoformat()}Z — REVERTED {d}: {n} nights restored to previous prices\n")
    print(f"Reverted {n} nights to their previous prices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
