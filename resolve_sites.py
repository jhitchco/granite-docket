import requests, json, re, concurrent.futures as cf
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
T=json.load(open("towns.json"))
def ok(t,r):
    if r.status_code>=400: return False
    txt=r.text[:200000]
    nm=t["name"].replace("'", "")
    return bool(re.search(re.escape(nm),txt.replace("'", ""),re.I)) and bool(re.search(r"New Hampshire|\bNH\b",txt))
def cands(t):
    n=re.sub(r"[^a-z]","",t["name"].lower()); d=re.sub(r"[^a-z]+","-",t["name"].lower()).strip("-")
    c=[]
    for base in {n,d}:
        for p in ["{b}nh.gov","{b}-nh.gov","townof{b}nh.gov","{b}.nh.gov","townof{b}.nh.gov","{b}nh.org","{b}-nh.org","townof{b}nh.org","townof{b}.org","{b}nh.us","{b}-nh.us","{b}nh.com","{b}-nh.com","townof{b}nh.com","townof{b}.com","{b}nh.net","townof{b}.net","{b}.nh.us","town.{b}.nh.us","www.{b}nh.gov","www.{b}-nh.gov","www.{b}nh.org","www.townof{b}nh.gov"]:
            c.append("https://"+p.format(b=base))
    return list(dict.fromkeys(c))
def bad(t):
    if not t.get("website") or t.get("error") or (t.get("status") or 200)>=400: return True
    return False
def fix(t):
    # first check current site validity
    if not bad(t):
        try:
            r=requests.get(t["final_url"],headers=H,timeout=20)
            if ok(t,r): return t
        except Exception: pass
    if t.get("website"):
        try:
            r=requests.get(t["website"].replace("http://","https://"),headers=H,timeout=20)
            if ok(t,r): t.update(final_url=r.url,status=r.status_code,error=None,resolved="https"); return t
        except Exception: pass
    for u in cands(t):
        try:
            r=requests.get(u,headers=H,timeout=12)
            if ok(t,r): t.update(final_url=r.url,status=r.status_code,error=None,resolved="guess"); return t
        except Exception: pass
    t["resolved"]="FAILED"; return t
with cf.ThreadPoolExecutor(32) as ex: T=list(ex.map(fix,T))
json.dump(T,open("towns.json","w"),indent=1)
print("fixed:",[(t["name"],t["final_url"]) for t in T if t.get("resolved") in("https","guess")])
print("failed:",[t["name"] for t in T if t.get("resolved")=="FAILED"])
