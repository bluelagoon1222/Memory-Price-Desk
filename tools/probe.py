import requests, re, html, sys
UA={"User-Agent":"Mozilla/5.0 (Memory-Price-Desk backfill; personal research)"}
cdx=requests.get("https://web.archive.org/cdx/search/cdx",params={"url":"dramexchange.com/","from":"2016","to":"2026","output":"json","collapse":"timestamp:6","filter":"statuscode:200"},headers=UA,timeout=60).json()
print("monthly snapshots:",len(cdx)-1, cdx[1][1] if len(cdx)>1 else None, cdx[-1][1])
for row in [cdx[1],cdx[len(cdx)//2],cdx[-1]]:
    ts=row[1]
    t=requests.get(f"https://web.archive.org/web/{ts}id_/https://www.dramexchange.com/",headers=UA,timeout=60).text
    x=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",re.sub(r"(?s)<script.*?</script>|<style.*?</style>","",t))))
    print("=====",ts,len(t))
    for k in ["Last Update","DDR4 8Gb","DDR5 16Gb","512Gb TLC","DDR4 16Gb"]:
        for m in list(re.finditer(re.escape(k),x))[:2]:
            print(k,"::",x[m.start():m.start()+160])
