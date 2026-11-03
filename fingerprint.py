import requests, json, re, concurrent.futures as cf
from urllib.parse import urljoin
from collections import Counter
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
towns=json.load(open("towns_raw.json"))
SIGS=[("civicplus",r"civicplus|/AgendaCenter|CivicEngage"),("vts",r"virtualtownhall|Virtual Towns|vt-site|/sites/g/files/vyhlif"),
("revize",r"revize"),("granicus",r"granicus"),("municode",r"municodemeetings|municode"),("boarddocs",r"boarddocs"),
("civicclerk",r"civicclerk"),("wordpress",r"wp-content"),("squarespace",r"squarespace"),("wix",r"wix\.com|wixstatic"),
("googlesites",r"sites\.google"),("drupal",r"Drupal"),("govoffice",r"govoffice"),("townweb",r"townweb"),("schoolblocks",r"schoolblocks")]
def go(t):
    u=t.get("website")
    if not u: return t
    try:
        r=requests.get(u,headers=H,timeout=30,allow_redirects=True)
        t["final_url"]=r.url; t["status"]=r.status_code
        h=r.text
        t["platform"]=[n for n,p in SIGS if re.search(p,h,re.I)]
        links=set()
        for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a',h,re.I|re.S):
            txt=re.sub("<[^>]+>","",m.group(2)).strip()
            if re.search(r"agenda|minute|meeting|planning|zoning|select|council|boards?\b|committee",txt+m.group(1),re.I):
                links.add((urljoin(r.url,m.group(1)),txt[:80]))
        t["meeting_links"]=sorted(links)[:80]
    except Exception as e:
        t["error"]=str(e)[:200]
    return t
with cf.ThreadPoolExecutor(24) as ex: out=list(ex.map(go,towns))
json.dump(out,open("towns.json","w"),indent=1)
print(Counter(p for t in out for p in (t.get("platform") or ["none"])))
print("errors:",[(t["name"],t.get("error","")[:60]) for t in out if t.get("error")])
