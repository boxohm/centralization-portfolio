#!/usr/bin/env python3
"""Daily data for the Centralization Portfolio strategy page.

Fetches keyless public sources (FRED CSV, Yahoo chart API, Treasury FiscalData),
computes the regime-dial tells, merges manual event flags, and writes
strategy-data.json next to strategy.html.

No API keys required. Every fetch is independent — partial failures degrade
gracefully and are marked in the output.
"""
import json, csv, io, urllib.request, datetime, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "strategy-data.json"
FLAGS = ROOT / "manual_flags.json"
UA = "Mozilla/5.0"

def get(url, timeout=30):
    """Fetch a URL as text. Tries curl bare, then curl with a browser UA,
    then urllib — some hosts want a UA, some proxies reject one."""
    if shutil.which("curl"):
        for extra in ([], ["-A", UA]):
            p = subprocess.run(["curl", "-sfL", "--http1.1", "-m", str(timeout),
                                *extra, url],
                               capture_output=True, timeout=timeout + 10)
            if p.returncode == 0 and p.stdout:
                return p.stdout.decode("utf-8", "replace")
        raise RuntimeError(f"curl exit {p.returncode} for {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def fred_series(series_id):
    """Return list of (date, float) for a FRED series, skipping missing dots."""
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    rows = []
    for rec in csv.reader(io.StringIO(txt)):
        if len(rec) != 2 or rec[0] in ("DATE", "observation_date"):
            continue
        try:
            rows.append((rec[0], float(rec[1])))
        except ValueError:
            continue
    return rows

def yahoo_closes(symbol, rng="5y"):
    txt = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
              f"?range={rng}&interval=1d")
    j = json.loads(txt)["chart"]["result"][0]
    closes = j["indicators"]["quote"][0]["close"]
    ts = j["timestamp"]
    return [(datetime.date.fromtimestamp(t).isoformat(), c)
            for t, c in zip(ts, closes) if c is not None]

def bills_share():
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
           "/v1/debt/mspd/mspd_table_1?page%5Bsize%5D=40&sort=-record_date")
    j = json.loads(get(url))["data"]
    latest = j[0]["record_date"]
    rows = [r for r in j if r["record_date"] == latest
            and r["security_type_desc"] == "Marketable"]
    bills = sum(float(r["total_mil_amt"]) for r in rows
                if r["security_class_desc"] == "Bills")
    total = sum(float(r["total_mil_amt"]) for r in rows
                if r["security_class_desc"] in
                ("Bills", "Notes", "Bonds",
                 "Treasury Inflation-Protected Securities",
                 "Floating Rate Notes"))
    return {"date": latest, "bills_pct": round(100 * bills / total, 1)} if total else None

def yoy(series):
    """YoY % change of a monthly index, latest observation."""
    if len(series) < 13:
        return None
    d, v = series[-1]
    target = (datetime.date.fromisoformat(d) - datetime.timedelta(days=365)).replace(day=1)
    for dd, vv in reversed(series):
        if dd == target.isoformat():
            return {"date": d, "yoy": round(100 * (v / vv - 1), 2)}
    return None

data, errors = {}, []

def safe(name, fn):
    try:
        data[name] = fn()
    except Exception as e:  # noqa: BLE001 — degrade, don't die
        errors.append(f"{name}: {type(e).__name__} {e}")
        data[name] = None

# --- fetches -----------------------------------------------------------------
safe("fed_funds",   lambda: dict(zip(("date", "value"), fred_series("DFF")[-1])))
safe("core_pce",    lambda: yoy(fred_series("PCEPILFE")))
safe("core_cpi",    lambda: yoy(fred_series("CPILFESL")))
safe("ust10y",      lambda: dict(zip(("date", "value"), fred_series("DGS10")[-1])))
safe("ust30y",      lambda: dict(zip(("date", "value"), fred_series("DGS30")[-1])))
safe("bill3m",      lambda: dict(zip(("date", "value"), fred_series("DTB3")[-1])))
safe("breakeven_5y5y", lambda: dict(zip(("date", "value"), fred_series("T5YIFR")[-1])))
safe("term_premium",   lambda: dict(zip(("date", "value"), fred_series("THREEFYTP10")[-1])))

def oas(series_id):
    s = fred_series(series_id)
    last_date, last = s[-1]
    lo52 = min(v for _, v in s[-252:])
    return {"date": last_date, "value": last, "tight_52w": lo52,
            "widening_bps": round(100 * (last - lo52))}
safe("ig_oas", lambda: oas("BAMLC0A0CM"))
safe("hy_oas", lambda: oas("BAMLH0A0HYM2"))

def qqq_stats():
    s = yahoo_closes("QQQ", "5y")
    closes = [c for _, c in s]
    last_d, last = s[-1]
    ath = max(closes)
    sma200 = sum(closes[-200:]) / min(200, len(closes))
    return {"date": last_d, "close": round(last, 2), "ath": round(ath, 2),
            "drawdown_pct": round(100 * (last / ath - 1), 1),
            "above_200dma": last >= sma200}
safe("qqq", qqq_stats)

def smh_stats():
    s = yahoo_closes("SMH", "2y")
    closes = [c for _, c in s]
    last_d, last = s[-1]
    sma252 = sum(closes[-252:]) / min(252, len(closes))
    return {"date": last_d, "close": round(last, 2), "above_252dma": last >= sma252}
safe("smh", smh_stats)
safe("bills_share", bills_share)

# --- manual event flags ------------------------------------------------------
flags = {}
if FLAGS.exists():
    try:
        flags = {k: v for k, v in json.loads(FLAGS.read_text()).items()
                 if not k.startswith("_")}
    except Exception as e:  # noqa: BLE001
        errors.append(f"manual_flags: {e}")

# --- tell evaluation ---------------------------------------------------------
amber, red = [], []
ff = (data.get("fed_funds") or {}).get("value")
pce = (data.get("core_pce") or {}).get("yoy")
real_rate = round(ff - pce, 2) if ff is not None and pce is not None else None

ig = data.get("ig_oas")
if ig and ig["widening_bps"] >= 100:
    amber.append(f"IG OAS +{ig['widening_bps']}bps off 52w tights")
t10 = (data.get("ust10y") or {}).get("value")
if t10 is not None and t10 >= 5.5:
    amber.append(f"10y at {t10}%")
b55 = (data.get("breakeven_5y5y") or {}).get("value")
if pce is not None and pce >= 4.5:
    amber.append(f"core PCE {pce}% (>=4.5)")
elif b55 is not None and b55 >= 2.8:
    amber.append(f"5y5y breakeven {b55}% (unanchoring)")
qqq, smh = data.get("qqq"), data.get("smh")
tiebreak = bool(qqq and smh and not qqq["above_200dma"] and not smh["above_252dma"])
if flags.get("capex_growth_halved"):
    amber.append("capex growth halved (manual)")
if flags.get("rev_per_mw_rolling_over"):
    amber.append("revenue/MW rolling over (manual)")
if tiebreak and len(amber) == 1:
    amber.append("technical tiebreaker: QQQ<200dma & SMH<252dma")

if pce is not None and real_rate is not None and pce >= 5.0 and real_rate >= 1.5:
    red.append(f"repression break: core PCE {pce}%, real rate +{real_rate}")
for key, label in [("capex_guide_cut", "hyperscaler capex guide cut"),
                   ("lab_contract_out", "lab exercised 90-day out / rent renegotiated"),
                   ("neocloud_default", "neocloud default / financing cancellation"),
                   ("federal_moratorium", "federal training pause / datacenter moratorium"),
                   ("depreciation_reversal", "depreciation-life reversal / GPU write-down")]:
    if flags.get(key):
        red.append(f"{label} (manual)")

regime = "RED" if red else ("AMBER" if len(amber) >= 2 else "GREEN")

data.update({
    "as_of": datetime.datetime.now(datetime.timezone.utc)
             .strftime("%Y-%m-%d %H:%M UTC"),
    "real_policy_rate": real_rate,
    "repression_on": bool(real_rate is not None and pce is not None
                          and real_rate <= 0.5 and 3.0 <= pce <= 4.5),
    "amber_tells": amber, "red_flags": red,
    "manual_flags": flags, "regime": regime, "errors": errors,
})
OUT.write_text(json.dumps(data, indent=1))
print(f"wrote {OUT.name}: regime={regime}, amber={len(amber)}, red={len(red)}, "
      f"errors={len(errors)}", file=sys.stderr)
print(json.dumps({k: data[k] for k in
                  ("as_of", "real_policy_rate", "regime", "errors")}, indent=1))
