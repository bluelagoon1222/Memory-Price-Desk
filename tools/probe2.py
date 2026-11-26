import sys,requests
sys.path.insert(0,'tools'); import wayback
UA=wayback.UA
for ts in ["20170315000000","20220601000000","20261101134057"]:
    t=wayback.text(requests.get(f"https://web.archive.org/web/{ts}id_/https://www.dramexchange.com/",headers=UA,timeout=60).text)
    i=t.find("DRAM Spot")
    print("=====",ts,"idx",i); print(t[i:i+1500])
    print("HEADS",[m.group(0) for m in wayback.HEAD.finditer(t)][:12])
