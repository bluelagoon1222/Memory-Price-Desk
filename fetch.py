"""Memory-Price-Desk data collector.

- TrendForce public price tables (DRAM / NAND spot & contract) -> data/prices.json
  One snapshot per "Last Update" date per section; history accumulates from the first run.
- Memory stocks (Yahoo Finance daily close) -> data/stocks.json
- data/hbm.json, data/outlook.json are hand-curated (not touched here).
One failing source never stops the others. Status goes to data/status.json.
"""
import datetime as dt
import html
import json
import os
import re
import time
import traceback

import requests

OUT = "data"
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
UA = {"User-Agent": "Mozilla/5.0 (Memory-Price-Desk personal bot; 1 request/day; github.com/bluelagoon1222)"}
STATUS = []

PAGES = {
    "dram": "https://www.trendforce.com/price/dram/dram_spot",
    "flash": "https://www.trendforce.com/price/flash/flash_spot",
}
# section id -> (Korean group label, kind)
SECTIONS = {
    "dram_spot": ("DRAM 현물(칩)", "spot"),
    "dram_contract": ("DRAM 계약(PC)", "contract"),
    "module_spot": ("모듈 현물", "spot"),
    "gddr_spot": ("그래픽 DRAM 현물", "spot"),
    "flash_spot": ("NAND 칩 현물", "spot"),
    "wafer_spot": ("NAND 웨이퍼 현물", "spot"),
    "flash_contract": ("NAND 계약(카드/USB)", "contract"),
    "memCard_spot": ("메모리카드 현물", "spot"),
    "pcc_oem_ssd_contract": ("PC OEM SSD 계약", "contract"),
}
STOCKS = [
    ("000660.KS", "SK하이닉스", "KRW"),
    ("005930.KS", "삼성전자", "KRW"),
    ("MU", "마이크론", "USD"),
    ("SNDK", "샌디스크", "USD"),
    ("2408.TW", "난야테크(대만 DRAM)", "TWD"),
    ("2344.TW", "윈본드(대만 DRAM)", "TWD"),
    ("285A.T", "키옥시아(NAND)", "JPY"),
    ("^SOX", "필라델피아 반도체지수", "pt"),
]


def log(name, ok, note=""):
    STATUS.append({"src": name, "ok": ok, "note": str(note)[:300]})
    print(("OK  " if ok else "ERR ") + name + " " + str(note)[:200])


def http(url, tries=3):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa
            last = e
            time.sleep(4 * (i + 1))
    raise last


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def txt(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def num(s):
    s = s.replace(",", "").replace("%", "").replace("▲", "").replace("▼", "").replace("—", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- TrendForce parser
SEC_RE = re.compile(r'<div id="([A-Za-z_]+)" class="price-content"', re.S)


def parse_sections(page_html):
    """Return {sec_id: {"date": "YYYY-MM-DD", "stamp": str, "heads": [...], "rows": [[cell,...],...]}}"""
    out = {}
    starts = [(m.start(), m.group(1)) for m in SEC_RE.finditer(page_html)]
    for i, (pos, sid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(page_html)
        block = page_html[pos:end]
        m = re.search(r"Last Update\s*(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})?", block)
        if not m:
            continue
        heads = [txt(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", block, re.S)]
        body = re.search(r"<tbody>(.*?)</tbody>", block, re.S)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S):
            cells = [txt(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if cells and cells[0]:
                rows.append(cells)
        out[sid] = {"date": m.group(1), "stamp": f"{m.group(1)} {m.group(2) or ''}".strip(), "heads": heads, "rows": rows}
    return out


def col(heads, *names):
    for n in names:
        if n in heads:
            return heads.index(n)
    return None


def rows_to_points(sid, sec):
    heads = sec["heads"]
    i_avg = col(heads, "Session Average", "Average")
    i_hi = col(heads, "Session High", "High")
    i_lo = col(heads, "Session Low", "Low")
    i_chg = col(heads, "Session Change", "Average Change")
    i_dh = col(heads, "Daily High", "Weekly High")
    i_dl = col(heads, "Daily Low", "Weekly Low")
    pts = []
    if i_avg is None:
        return pts
    for c in sec["rows"]:
        if len(c) <= i_avg:
            continue
        name = re.sub(r"\s+", " ", c[0]).strip()
        avg = num(c[i_avg])
        if avg is None:
            continue
        g = lambda i: num(c[i]) if i is not None and i < len(c) else None  # noqa
        pts.append({"name": name, "avg": avg, "hi": g(i_hi), "lo": g(i_lo), "chg": g(i_chg),
                    "dh": g(i_dh), "dl": g(i_dl)})
    return pts


def trendforce():
    db = load(f"{OUT}/prices.json", {"items": {}})
    items = db.setdefault("items", {})
    stamps = db.setdefault("stamps", {})
    added = 0
    for page, url in PAGES.items():
        try:
            secs = parse_sections(http(url).text)
            if not secs:
                raise RuntimeError("no price sections found (layout changed?)")
        except Exception as e:
            log(f"trendforce:{page}", False, e)
            continue
        got = []
        for sid, sec in secs.items():
            if sid not in SECTIONS:
                continue
            grp, kind = SECTIONS[sid]
            pts = rows_to_points(sid, sec)
            if not pts:
                continue
            stamps[sid] = sec["stamp"]
            got.append(f"{sid}={sec['date']}({len(pts)})")
            for p in pts:
                iid = slug(f"{sid}_{p['name']}")
                it = items.setdefault(iid, {"name": p["name"], "sec": sid, "grp": grp, "kind": kind,
                                            "t": [], "avg": [], "hi": [], "lo": [], "chg": [], "dh": [], "dl": []})
                for k in ("dh", "dl"):
                    it.setdefault(k, [None] * len(it["t"]))
                d = sec["date"]
                row = {k: p[k] for k in ("avg", "hi", "lo", "chg", "dh", "dl")}
                if it["t"] and it["t"][-1] == d:
                    for k, v in row.items():
                        it[k][-1] = v          # same session date -> overwrite (intraday refresh)
                elif not it["t"] or it["t"][-1] < d:
                    it["t"].append(d)
                    for k, v in row.items():
                        it[k].append(v)
                    added += 1
        log(f"trendforce:{page}", bool(got), " ".join(got))
    db["updated"] = NOW.strftime("%Y-%m-%d %H:%M KST")
    db["source"] = "TrendForce (trendforce.com/price) public price tables"
    save(f"{OUT}/prices.json", db)
    return added


# ---------------------------------------------------------------- backfill (memorypricechart.com)
# Terms allow viewing/exporting public chart data for personal/analytical use with attribution.
MPC = "https://memorypricechart.com/data/"


def _merge(it, rows, src):
    """rows: {date: {avg,hi,lo,chg,dh,dl}}; adds only dates we don't already have."""
    have = {t: i for i, t in enumerate(it["t"])}
    keys = ("avg", "hi", "lo", "chg", "dh", "dl")
    table = {t: {k: (it.get(k) or [None] * len(it["t"]))[i] for k in keys} for t, i in have.items()}
    added = 0
    for d, r in rows.items():
        if d not in table:
            table[d] = {k: r.get(k) for k in keys}
            added += 1
    if added:
        ts = sorted(table)
        it["t"] = ts
        for k in keys:
            it[k] = [table[t][k] for t in ts]
        it.setdefault("backfill", src)
    return added


def backfill():
    db = load(f"{OUT}/prices.json", {"items": {}})
    items = db.setdefault("items", {})
    notes = []
    # DRAM chip spot (TrendForce numbers re-published by memorypricechart, from 2026-08-14)
    try:
        j = http(MPC + "dram-spot-prices.json").json()
        for s in j["series"].values():
            rows = {}
            for p in s.get("points", []):
                d = p.get("source_date")
                if d and p.get("session_average_usd") is not None:
                    rows[d] = {"avg": p["session_average_usd"], "hi": p.get("session_high_usd"),
                               "lo": p.get("session_low_usd"), "chg": p.get("source_session_change_pct")}
            iid = slug("dram_spot_" + s["label"])
            it = items.setdefault(iid, {"name": s["label"], "sec": "dram_spot", "grp": SECTIONS["dram_spot"][0],
                                        "kind": "spot", "t": [], "avg": [], "hi": [], "lo": [], "chg": [], "dh": [], "dl": []})
            notes.append(f"{s['label']}+{_merge(it, rows, 'memorypricechart.com (TrendForce)')}")
        log("backfill:dram", True, " ".join(notes))
    except Exception as e:
        log("backfill:dram", False, e)
    # NAND 1Tb TLC/QLC spot (ChinaFlashMarket via memorypricechart, from 2026-05)
    notes = []
    try:
        j = http(MPC + "nand-spot-prices.json").json()
        for s in j["series"].values():
            rows = {p["date"]: {"avg": p.get("close_usd"), "lo": p.get("low_usd")}
                    for p in s.get("points", []) if p.get("date") and p.get("close_usd") is not None}
            prev = None
            for d in sorted(rows):
                v = rows[d]["avg"]
                rows[d]["chg"] = round((v / prev - 1) * 100, 2) if prev else None
                prev = v
            iid = slug("cfm_" + s["label"])
            it = items.setdefault(iid, {"name": s["label"], "sec": "cfm_nand", "grp": "NAND 1Tb 현물(중국 CFM)",
                                        "kind": "spot", "t": [], "avg": [], "hi": [], "lo": [], "chg": [], "dh": [], "dl": []})
            # CFM is only available via this source -> refresh all points (latest wins)
            it["t"], it["avg"], it["lo"], it["chg"] = [], [], [], []
            it["hi"], it["dh"], it["dl"] = [], [], []
            _merge(it, rows, "memorypricechart.com (ChinaFlashMarket)")
            notes.append(f"{s['label']}={len(it['t'])}")
        db.setdefault("stamps", {})["cfm_nand"] = (j.get("generated_at") or "")[:16].replace("T", " ") + " UTC"
        log("backfill:nand1tb", True, " ".join(notes))
    except Exception as e:
        log("backfill:nand1tb", False, e)
    save(f"{OUT}/prices.json", db)


# ---------------------------------------------------------------- wayback (archived DRAMeXchange homepage)
# Older names that are the same product line as a current TrendForce row (filled by tools/wayback.py output).
ALIAS = {
    ("module_spot", "DDR5 UDIMM 16GB"): "DDR5 UDIMM 16GB 4800/5600",
    ("module_spot", "DDR5 RDIMM 32GB"): "DDR5 RDIMM 32GB 4800/5600",
    ("module_spot", "DDR4 UDIMM 16GB"): "DDR4 UDIMM 16GB 3200",
}


def wayback_merge():
    wb = load(f"{OUT}/wayback.json", None)
    if not wb:
        log("wayback", True, "no archive file yet")
        return
    db = load(f"{OUT}/prices.json", {"items": {}})
    items = db.setdefault("items", {})
    notes = []
    for sec, names in wb.get("data", {}).items():
        for name, rows in names.items():
            target = ALIAS.get((sec, name), name)
            iid = slug(f"{sec}_{target}")
            if iid not in items:      # only extend products that TrendForce still lists
                continue
            conv = {d: {"avg": r[0], "hi": r[1], "lo": r[2], "chg": r[3]} for d, r in rows.items()}
            n = _merge(items[iid], conv, "web.archive.org (DRAMeXchange)")
            if n:
                notes.append(f"{iid}+{n}")
    save(f"{OUT}/prices.json", db)
    log("wayback", True, " ".join(notes)[:280] or "nothing new")


# ---------------------------------------------------------------- stocks
def _yahoo_chart(host, sym, query):
    r = http(f"https://{host}.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}?{query}")
    res = r.json()["chart"]["result"][0]
    off = res.get("meta", {}).get("gmtoffset", 0) or 0
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or []
    out = {}
    for i, t in enumerate(ts):
        c = q["close"][i] if i < len(q["close"]) else None
        if c is None and i < len(adj):
            c = adj[i]
        if c is not None:
            out[dt.datetime.utcfromtimestamp(t + off).date().isoformat()] = round(c, 4)
    m = res.get("meta", {})
    if m.get("regularMarketPrice") and m.get("regularMarketTime"):
        out.setdefault(dt.datetime.utcfromtimestamp(m["regularMarketTime"] + off).date().isoformat(),
                       round(m["regularMarketPrice"], 4))
    return out


def nasdaq(sym):
    """Fallback for US tickers: Nasdaq.com historical quotes (last ~3 months)."""
    frm = (NOW.date() - dt.timedelta(days=95)).isoformat()
    r = requests.get(f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=stocks&fromdate={frm}"
                     f"&todate={NOW.date().isoformat()}&limit=200",
                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=40)
    r.raise_for_status()
    rows = ((r.json().get("data") or {}).get("tradesTable") or {}).get("rows") or []
    out = {}
    for x in rows:
        m, d, y = x["date"].split("/")
        out[f"{y}-{m}-{d}"] = round(float(x["close"].replace("$", "").replace(",", "")), 4)
    return out


def yahoo(sym, years=5):
    """Daily closes, split-adjusted. If the long history stops early (e.g. after a stock split
    Yahoo sometimes returns null closes), patch the tail from a short-range query and Nasdaq.com."""
    p1 = int(time.time()) - years * 366 * 86400
    out = _yahoo_chart("query2", sym, f"period1={p1}&period2={int(time.time())}&interval=1d&events=history")
    def gap(d):  # stale tail, or a hole of >4 days in the last 30 days
        ks = sorted(d)[-25:]
        if not ks or (NOW.date() - dt.date.fromisoformat(ks[-1])).days > 4:
            return True
        return any((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days > 4 for a, b in zip(ks, ks[1:]))
    if gap(out):
        us = "." not in sym and not sym.startswith("^")
        for name, fn in (("yahoo-3mo", lambda: _yahoo_chart("query1", sym, "range=3mo&interval=1d")),
                         ("nasdaq", lambda: nasdaq(sym) if us else {})):
            try:
                extra = fn()
                add = {k: v for k, v in extra.items() if k not in out}
                out.update(add)
                print(f"fallback {name} {sym}: +{len(add)} rows")
            except Exception as e:  # noqa
                print(f"fallback {name} {sym} failed: {e}")
            if not gap(out):
                break
    return sorted(out.items())


def stocks():
    db = load(f"{OUT}/stocks.json", {"items": {}})
    for sym, name, cur in STOCKS:
        try:
            pairs = yahoo(sym)
            if len(pairs) < 20:
                raise RuntimeError(f"too few rows {len(pairs)}")
            db["items"][slug(sym)] = {"sym": sym, "name": name, "cur": cur,
                                      "t": [a for a, _ in pairs], "c": [b for _, b in pairs]}
            log(f"stock:{sym}", True, f"{len(pairs)} rows, last {pairs[-1][0]}")
        except Exception as e:
            log(f"stock:{sym}", False, e)
    db["updated"] = NOW.strftime("%Y-%m-%d %H:%M KST")
    save(f"{OUT}/stocks.json", db)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (("trendforce", trendforce), ("backfill", backfill), ("wayback", wayback_merge), ("stocks", stocks)):
        try:
            fn()
        except Exception:
            log(name, False, traceback.format_exc()[-300:])
    save(f"{OUT}/status.json", {"run": NOW.strftime("%Y-%m-%d %H:%M KST"), "items": STATUS})


if __name__ == "__main__":
    main()
