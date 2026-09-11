# Setup — the parts Ryan does himself (about 10 minutes)

## 1. Create the repo (public, empty)
1. Go to https://github.com/new
2. Repository name: `cedar-pricing-bridge` · **Public** · leave "Add a README" **unchecked** · Create repository.
3. Tell Claude "repo created" — Claude pushes all the files. (If that push is blocked, Claude will hand you a zip and
   you use **Add file → Upload files** on the repo page, dragging the whole folder in.)

## 2. Add the two Hostaway secrets
Repo page → **Settings** (top tab) → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value (from your Drive file `api-credentials.txt`, HOSTAWAY section) |
|---|---|
| `HOSTAWAY_ACCOUNT_ID` | `173862` |
| `HOSTAWAY_API_KEY` | the long key |

Optional later: `SERPAPI_KEY` (only if you ever switch on the cloud backup in `config.json`).

## 3. Finish turning off Hostaway Dynamic Pricing
Hostaway → **Dynamic Pricing** → page 1 & 2 → rooms **10, 11, 12** still say *SUBSCRIBED – PRICES SYNCED*.
Flip the **Subscribed** toggle off for each. (Rooms 1–9 are already unsubscribed.)
Why: Hostaway warns against two pricing tools on one listing, and its engine silently overwrites manual prices.

## 4. Chrome on the Mac mini (already mostly done)
- Claude Chrome extension connected ✅ (device "Browser 1")
- Signed in to github.com as Riv419 ✅
- If the extension ever asks for site permission for `expedia.com`, `google.com` or `github.com`, allow it.

## 5. First run = DRY RUN (nothing touches Hostaway)
1. Repo → **Actions** tab → **1 - Build pricing recommendations** → **Run workflow** → leave the box empty → **Run workflow**.
   (Claude will do this for you from the Mac mini's Chrome with real Expedia data the first time.)
2. Read the issue it opens: `Pricing recommendations <date>`.
3. To test the apply path safely: **Actions → 2 - Apply approved prices** → Run workflow → `rec_date` = latest,
   `approval_text` = approve, **`dry_run` = true**. It writes `log/<date>-dryrun.json` and changes nothing.
4. When you're happy with the logic, say so in chat. From then on your `approve` reply goes live.

## 6. Daily use
- Every morning Claude messages you the summary. Reply **approve**, **approve except rooms 3,5**,
  **approve except Sep 19-20**, **approve only Sep 19**, or **skip**.
- Or comment the same words on the GitHub issue from the GitHub app — same result.
- Undo a day: **Actions → 3 - Revert prices** → Run workflow → enter the date.
- Pause everything: **Actions → 2 - Apply approved prices → ⋯ → Disable workflow** (or set `"enabled": false` in `config.json`).

## 7. Tuning (edit `config.json` on GitHub → pencil icon → Commit)
- `comp_position` 0.90 = 10% under the competitor median. 1.0 = match them.
- `floor` / `ceiling` — hard limits.
- `occupancy_factors`, `lead_time_factors`, `weather` — the multipliers, with comments inline.
- `rooms[].offset` — per-room dollar bump (rooms 7–10 = +$10).
- `comps.comp_set` — the competitor names. Add or remove hotels here (match is a case-insensitive "contains").
