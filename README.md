# cedar-pricing-bridge

Daily pricing for The Cedar (12 rooms, Hostaway account 173862).

**Auto mode (since Sep 17, 2026):** each morning's prices go to Hostaway automatically — floor **$109**, ceiling **$289**,
and no night moves more than **$20 per day**. Automatic apply happens *only* when that morning's Chrome pass delivered a
fresh competitor sample (≥ 5 nights); otherwise the day is skipped, prices stay put, and Ryan gets told why. Events
(Cedar Point days, festivals, holidays) come from Claude's morning web search. Kill switch: `"auto_apply": {"enabled": false}`
in `config.json` puts it back in reply-**approve** mode; `"enabled": false` at the top stops all writes.

## How a day works

1. **~6:15 AM ET — the scheduled Cowork task** searches the web for upcoming events (Cedar Point open/closed days and
   HalloWeekends, Sandusky + Port Clinton festivals, concerts, holidays) and builds the `events_json` list; then, in
   Chrome on the Mac mini, opens Expedia for ~30 upcoming nights (every night for the next 10 days, then every Fri + Sat
   out to 90 days) and pulls the nightly rates for the named competitor set (Breakers Express, the Route 250 strip,
   renovated motels, Port Clinton, plus a vacation-rental median). It hands both lists to this repo by pressing
   **Run workflow** on *1 - Build pricing recommendations* (inputs `comps_json` and `events_json`).
2. **The GitHub Action** reads The Cedar's calendar from Hostaway (occupancy + current prices), pulls the NWS 7-day
   forecast, applies the event factors, runs the pricing rules in `config.json`, **applies the prices to Hostaway if the
   competitor sample is fresh** (writes `log/<date>-applied.json` + `CHANGELOG.md`), and commits:
   - `recommendations/<date>.json` (every recommended change with its reason) and `.md` (the readable summary)
   - `data/comps/store.json` (competitor samples), `data/calendar/latest.json`, `data/weather/latest.json`
   - a GitHub **issue** titled `Pricing recommendations <date>` containing the summary.
3. **Claude reads the result** (`git clone`, then `recommendations/latest.md` + `log/last_result.md`) and sends Ryan a
   push notification: what moved, what didn't, and anything that failed.
4. **Manual override still works:** commenting `approve`, `approve except rooms 3,5`, `approve except Sep 19-20`,
   `approve only Sep 19` on the day's issue (only from **Riv419**) runs workflow 2 — useful on a day that was skipped.
   Workflow 2 refuses to apply a day that was already applied.
5. **Undo:** run *3 - Revert prices* with that date; it restores every old price from the log.

If the Chrome pass didn't happen (mini off, Expedia changed its page), the 7:15 AM fallback run still produces a summary
using stored samples that are still fresh — but **does not apply anything**, and skips any night without usable
competitor data rather than guessing.

## The pricing rules (all numbers live in `config.json`)

```
target = comp median × comp_position (0.90)
       × occupancy factor   (<25% booked: 0.85 · <50%: 0.93 · <75%: 1.00 · <90%: 1.08 · else 1.15)
       × lead-time factor   (≤29 days: 1.00 · 30–59: 0.95 · 60+: 0.90;
                             0–2 days out: 0.90 if house <50% full, 1.05 if >75% full)
       × weather factor     (next 7 days only: rain ≥60% → 0.95; Fri/Sat ≥75°F → 1.05)
       × event factor       (from the morning search: low 1.05 · medium 1.12 · high 1.25 · soft 0.95)
rounded to a price ending in 9, + $10 for rooms 7–10, clamped to floor $109 / ceiling $289,
then capped to ±$20 from the price that was live that morning (max_daily_move).
```
Only open (unbooked, unblocked) nights are priced. Changes under `min_change` ($5) are ignored.
"comp median" = median of the named competitors sampled for that night; if a night wasn't sampled, the nearest
sampled night of the same type (weekend/weekday) within 10 days is used and the summary marks it *(est.)*.

## Safety rails

- `config.json` → `"enabled": false` stops anything from being applied (kill switch); `"auto_apply": {"enabled": false}`
  goes back to reply-approve mode. Disabling workflow 1 in the Actions tab stops the morning run entirely.
- Automatic apply needs a fresh competitor sample that morning (≥ `auto_apply.min_fresh_dates` nights); the fallback
  cron run never applies.
- `max_daily_move` ($20): no night moves more than that per day, enforced at recommend time and again at apply time.
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
| `engine/events.py` | Event list → per-night factor (format documented in the file) |
| `data/events/latest.json` | The last events list handed over by the morning search |
| `engine/comps.py` | Competitor store, freshness rules, optional SerpApi backup |
| `chrome/expedia_extract.js` | The script Claude runs on each Expedia results page |
| `recommendations/` | One JSON + MD per day; `latest.*` always points at the newest |
| `log/`, `CHANGELOG.md` | The audit trail of everything applied or reverted |
| `tests/make_mock.py` | Fake calendar + comps for an offline test run |

Offline test: `python tests/make_mock.py && MOCK_CALENDAR=tests/mock_calendar.json COMPS_FILE=tests/mock_comps.json python engine/recommend.py`

## Lodging numbers (added Sep 14, 2026)

`engine/lodging.py` (workflow **4 - Pull lodging numbers**) reads Hostaway and
commits `data/lodging/latest.json`: tonight's occupancy and revenue by channel,
today's arrivals, tomorrow's departures, a 7-night outlook and month-to-date.
Revenue is on an occupancy basis (guest total ÷ nights). No guest names are
written — this repo is public. Started on time by the Mac mini trigger
(see `bar-sales-bridge/mac/install.sh`); GitHub's schedule is only a backup.

Claude tasks read it with the shell, not WebFetch:
`git clone --depth 1 https://github.com/Riv419/cedar-pricing-bridge.git /tmp/cpb && cat /tmp/cpb/data/lodging/latest.json`
