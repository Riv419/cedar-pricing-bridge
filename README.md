# cedar-pricing-bridge

Daily price **recommendations** for The Cedar (12 rooms, Hostaway account 173862). Nothing is ever written to Hostaway
until Ryan approves.

## How a day works

1. **~6:30 AM ET — Claude on the Mac mini** opens Expedia in Chrome for ~30 upcoming nights (every night for the next
   10 days, then every Fri + Sat out to 90 days), pulls the nightly rates for the named competitor set
   (Breakers Express, the Route 250 strip, renovated motels, Port Clinton, plus a vacation-rental median), and hands
   that list to this repo by pressing **Run workflow** on *1 - Build pricing recommendations*.
2. **The GitHub Action** reads The Cedar's calendar from Hostaway (occupancy + current prices), pulls the NWS 7-day
   forecast, runs the pricing rules in `config.json`, and commits:
   - `recommendations/<date>.json` (every recommended change with its reason) and `.md` (the readable summary)
   - `data/comps/store.json` (competitor samples), `data/calendar/latest.json`, `data/weather/latest.json`
   - a GitHub **issue** titled `Pricing recommendations <date>` containing the summary.
3. **Claude reads the summary** (via WebFetch) and messages Ryan.
4. **Ryan replies** `approve`, `approve except rooms 3,5`, `approve except Sep 19-20`, `approve only Sep 19`, or `skip`.
   Claude posts that exact text as a comment on the day's issue (or Ryan can comment on the issue himself from the
   GitHub app). Only comments from **Riv419** count.
5. **Workflow 2 applies** the approved prices to Hostaway (price only — never availability or minimum stay), waits 45 s,
   re-reads the calendar to verify, commits `log/<date>-applied.json` + `CHANGELOG.md`, and comments the result on the issue.
6. **Undo:** run *3 - Revert prices* with that date; it restores every old price from the log.

If the Chrome pass didn't happen (mini off, Expedia changed its page), the 7:15 AM fallback run still produces a summary
using stored samples that are still fresh — and skips any night without usable competitor data rather than guessing.

## The pricing rules (all numbers live in `config.json`)

```
target = comp median × comp_position (0.90)
       × occupancy factor   (<25% booked: 0.85 · <50%: 0.93 · <75%: 1.00 · <90%: 1.08 · else 1.15)
       × lead-time factor   (≤29 days: 1.00 · 30–59: 0.95 · 60+: 0.90;
                             0–2 days out: 0.90 if house <50% full, 1.05 if >75% full)
       × weather factor     (next 7 days only: rain ≥60% → 0.95; Fri/Sat ≥75°F → 1.05)
rounded to a price ending in 9, + $10 for rooms 7–10, clamped to floor $109 / ceiling $249.
```
Only open (unbooked, unblocked) nights are priced. Changes under `min_change` ($5) are ignored.
"comp median" = median of the named competitors sampled for that night; if a night wasn't sampled, the nearest
sampled night of the same type (weekend/weekday) within 10 days is used and the summary marks it *(est.)*.

## Safety rails

- `config.json` → `"enabled": false` stops workflow 2 from applying anything (kill switch). Disabling the workflow in
  the Actions tab does the same.
- Workflow 2 refuses recommendations older than 2 days and refuses to apply the same day twice.
- Every price is clamped to floor/ceiling again at apply time.
- Only `Riv419` can approve via issue comment; `workflow_dispatch` requires repo write access.
- Secrets (`HOSTAWAY_ACCOUNT_ID`, `HOSTAWAY_API_KEY`, optional `SERPAPI_KEY`) live only in GitHub Actions secrets.

## Files

| Path | What |
|---|---|
| `config.json` | Every tunable: floor, ceiling, positioning, factors, room list, competitor names |
| `engine/recommend.py` | Builds the day's recommendations (read-only against Hostaway) |
| `engine/apply.py` | Applies approved prices, verifies, logs |
| `engine/revert.py` | Restores old prices from a log |
| `engine/pricing.py` | The math, with a written reason for every price |
| `engine/comps.py` | Competitor store, freshness rules, optional SerpApi backup |
| `chrome/expedia_extract.js` | The script Claude runs on each Expedia results page |
| `recommendations/` | One JSON + MD per day; `latest.*` always points at the newest |
| `log/`, `CHANGELOG.md` | The audit trail of everything applied or reverted |
| `tests/make_mock.py` | Fake calendar + comps for an offline test run |

Offline test: `python tests/make_mock.py && MOCK_CALENDAR=tests/mock_calendar.json COMPS_FILE=tests/mock_comps.json python engine/recommend.py`
