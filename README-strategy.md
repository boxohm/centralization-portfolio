# Centralization Portfolio — live strategy page

A self-updating version of the strategy note: `strategy.html` renders the full
plan and, when hosted next to `strategy-data.json`, shows a **Live tells** strip
with the regime dial evaluated from fresh data (Green / Amber / Red).

## Files

| File | Purpose |
|---|---|
| `strategy.html` | The full strategy page + live-tells strip (strip hides itself if no data file is present) |
| `scripts/fetch_strategy_data.py` | Daily fetcher — FRED, Yahoo chart API, Treasury FiscalData; no API keys; computes the tells and the suggested regime |
| `strategy-data.json` | Output — committed daily by the workflow |
| `manual_flags.json` | Event tells that can't be automated (capex guide cut, lab contract out, default, moratorium, write-down). Flip to `true` when one happens — from the GitHub editor or a Claude Code session |
| `.github/workflows/strategy-daily.yml` | Runs the fetcher 22:45 UTC weekdays and commits the result |

## Setup — new repo, entirely from a phone

1. **Create the repo**: github.com → **+** → New repository → e.g. `centralization-portfolio`.
   ⚠️ GitHub Pages on a free plan requires a **public** repo — the strategy will be
   readable by anyone with the URL. Use a private repo + Cloudflare Pages if that matters.
2. **Add these files** (see hand-off options below).
3. **Let Actions write**: repo → Settings → Actions → General → Workflow
   permissions → **Read and write permissions** → Save.
4. **First data run**: Actions tab → `strategy-daily-data` → **Run workflow**.
   It commits `strategy-data.json`; after that it runs every weekday evening.
5. **Host it**: Settings → Pages → Deploy from a branch → `main` / root.
   Page appears at `https://<user>.github.io/<repo>/strategy.html`.

## Alternative — drop into an existing dashboard repo

Copy all files into the repo root (merge `.github/workflows/`). A git-connected
Cloudflare Pages deploy picks the page up automatically at `/strategy.html`;
the daily Action's commit triggers each redeploy.

## How the regime is computed

Auto tells from data: IG OAS ≥ +100 bps off 52-week tights, 10y ≥ 5.5%,
core PCE ≥ 4.5% or 5y5y breakeven ≥ 2.8% (Amber, any two, technicals as
tiebreaker); core PCE ≥ 5% with real policy rate ≥ +1.5% = the repression
break (Red on its own). Event tells come from `manual_flags.json`.
The page shows the suggestion; the human turns the dial.

Data sources are keyless public endpoints (FRED CSV, Yahoo v8 chart,
fiscaldata.treasury.gov). Each fetch fails independently — stale feeds are
counted in the strip rather than breaking the page.
