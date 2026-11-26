"""Occasional backfill: parse archived DRAMeXchange homepage snapshots (web.archive.org)
into data/wayback.json = {"done": [...], "data": {sec: {name: {date: [avg, hi, lo, chg]}}}}.
Resumable and polite (one request every ~3 seconds)."""
import datetime as dt
import html
import json
import os
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Memory-Price-Desk personal research backfill)"}
OUT = "data/wayback.json"
SPACING = int(os.environ.get("SPACING_DAYS", "5"))
BUDGET = int(os.environ.get("MAX_FETCH", "900"))
MON = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
SECMAP = {"DRAM Spot": "dram_spot", "Module Spot": "module_spot", "GDDR Spot": "gddr_spot",
          "Flash Spot": "flash_spot", "NAND Flash Spot": "flash_spot", "Wafer Spot": "wafer_spot",
          "Memory Card Spot": "memCard_spot", "Memory Card": "memCard_spot", "DRAM Contract": "dram_contract",
          "NAND Flash Contract": "flash_contract", "Flash Contract": "flash_contract"}
HEAD = re.compile(r"(DRAM Spot|Module Spot|GDDR Spot|NAND Flash Spot|Flash Spot|Wafer Spot|Memory Card Spot|Memory Card|DRAM Contract|NAND Flash Contract|Flash Contract) Price Last Update ?: ?([A-Z][a-z]{2})\.? ?(\d{1,2}),? (\d{4})")
VER = 2
NUM = re.compile(r"^-?[\d,]+\.\d+$")  # prices always carry decimals; "3200" speed grades do not
SKIP = re.compile(r"^(Item|Average Change|Low Change|Session Change|History|Avg Change)\s*")


def text(page):
    page = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", page)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def parse(t):
    out = {}
    heads = list(HEAD.finditer(t))
    for i, h in enumerate(heads):
        sec = SECMAP.get(h.group(1).strip())
        if not sec or h.group(2) not in MON:
            continue
        d = dt.date(int(h.group(4)), MON[h.group(2)], int(h.group(3))).isoformat()
        end = heads[i + 1].start() if i + 1 < len(heads) else h.end() + 4000
        body = t[h.end(): end]
        if "History" in body[:600]:
            body = body.split("History", 1)[1]
        for chunk in body.split("%"):
            toks = chunk.strip().split(" ")
            k = 0
            while k < len(toks) and not NUM.match(toks[k]):
                k += 1
            name = SKIP.sub("", " ".join(toks[:k]).strip()).strip()
            nums = []
            for x in toks[k:]:
                if NUM.match(x):
                    nums.append(float(x.replace(",", "")))
                else:
                    break
            if not name or len(name) > 60 or not re.search(r"\d", name):
                continue
            if len(nums) == 6:      # high, low, session high, session low, avg, chg
                row = [nums[4], nums[2], nums[3], nums[5]]
            elif len(nums) == 4:    # contract: high, low, avg, chg
                row = [nums[2], nums[0], nums[1], nums[3]]
            else:
                continue
            if row[1] and row[2] and not (row[2] <= row[0] <= row[1]):
                continue
            out.setdefault(sec, {}).setdefault(name, {})[d] = row
    return out


def main():
    db = json.load(open(OUT)) if os.path.exists(OUT) else {"done": [], "data": {}}
    if db.get("ver") != VER:      # parser changed -> re-read every snapshot
        db = {"ver": VER, "done": [], "data": {}}
    done = set(db["done"])
    cdx = requests.get("https://web.archive.org/cdx/search/cdx", headers=UA, timeout=180, params={
        "url": "dramexchange.com/", "from": os.environ.get("FROM", "2016"), "to": "2026", "output": "json",
        "collapse": "timestamp:8", "filter": "statuscode:200"}).json()[1:]
    picks, last = [], None
    for row in cdx:
        d = dt.datetime.strptime(row[1][:8], "%Y%m%d").date()
        if last is None or (d - last).days >= SPACING:
            picks.append(row[1])
            last = d
    todo = [p for p in picks if p not in done]
    print(f"cdx {len(cdx)} picks {len(picks)} todo {len(todo)}", flush=True)
    n = 0
    for ts in todo[:BUDGET]:
        try:
            r = requests.get(f"https://web.archive.org/web/{ts}id_/https://www.dramexchange.com/",
                             headers=UA, timeout=60)
            if r.status_code == 429:
                print("429, sleeping", flush=True)
                time.sleep(60)
                continue
            for sec, items in parse(text(r.text)).items():
                for name, rows in items.items():
                    db["data"].setdefault(sec, {}).setdefault(name, {}).update(rows)
            db["done"].append(ts)
            n += 1
            if n % 25 == 0:
                json.dump(db, open(OUT, "w"), separators=(",", ":"))
                print(ts, n, flush=True)
        except Exception as e:  # noqa
            print("fail", ts, e, flush=True)
            time.sleep(45)
        time.sleep(4)
    db["done"] = sorted(set(db["done"]))
    json.dump(db, open(OUT, "w"), separators=(",", ":"))
    for sec, items in db["data"].items():
        for nm, v in items.items():
            print(f"{sec} | {nm} | {len(v)} | {min(v)} ~ {max(v)}")


if __name__ == "__main__":
    main()
