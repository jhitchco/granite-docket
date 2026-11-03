import requests, json, re
from bs4 import BeautifulSoup
import time
def gj(url,params):
    for k in range(6):
        r=requests.get(url,params=params,headers=H,timeout=60)
        try: return r.json()
        except Exception: time.sleep(3*(k+1))
    raise SystemExit(r.status_code)
H={"User-Agent": "nh-meetings-research/0.1 (jeremy@ research)"}
html = requests.get("https://en.wikipedia.org/wiki/List_of_municipalities_in_New_Hampshire", headers=H).text
s = BeautifulSoup(html, "lxml")
t = max(s.select("table.wikitable"), key=lambda t: len(t.select("tr")))
hdr=[th.get_text(" ",strip=True) for th in t.select("tr")[0].select("th")]
print(hdr)
out=[]
for tr in t.select("tr")[1:]:
    cells = tr.select("th,td")
    if not cells: continue
    a = cells[0].find("a")
    if not a: continue
    out.append({"name": a.get_text(strip=True), "wiki": a["href"].split("/wiki/")[-1], "cells":[c.get_text(" ",strip=True) for c in cells]})
print(len(out), out[0], out[-1])
# map wiki titles to wikidata P856 in batches
titles=[o["wiki"] for o in out]
qid={}
for i in range(0,len(titles),50):
    r=gj("https://en.wikipedia.org/w/api.php",{"action":"query","prop":"pageprops","ppprop":"wikibase_item","redirects":1,"titles":"|".join(requests.utils.unquote(x) for x in titles[i:i+50]),"format":"json"})
    norm={n["to"]:n["from"] for n in r["query"].get("normalized",[])+r["query"].get("redirects",[])}
    for p in r["query"]["pages"].values():
        t0=p["title"]; 
        while t0 in norm: t0=norm[t0]
        qid[t0]=p.get("pageprops",{}).get("wikibase_item")
ids=[v for v in qid.values() if v]
site={}
for i in range(0,len(ids),50):
    r=gj("https://www.wikidata.org/w/api.php",{"action":"wbgetentities","ids":"|".join(ids[i:i+50]),"props":"claims","format":"json"})
    for k,e in r["entities"].items():
        v=[c["mainsnak"].get("datavalue",{}).get("value") for c in e.get("claims",{}).get("P856",[])]
        site[k]=v[0] if v else None
for o in out:
    k=requests.utils.unquote(o["wiki"]); q=qid.get(k) or qid.get(k.replace("_"," "))
    o["qid"]=q; o["website"]=site.get(q)
print(sum(1 for o in out if o["website"]), "with sites;", [o["name"] for o in out if not o["website"]])
json.dump(out,open("towns_raw.json","w"),indent=1)
