#!/usr/bin/env python3
"""Scrape both players' Solo/Duo rank from op.gg and rewrite the data block in index.html."""
import datetime, html, json, os, pathlib, re, urllib.request

ROOT = pathlib.Path(__file__).parent
PAGE = ROOT / "index.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
TIERS = ["Iron", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Master", "Grandmaster", "Challenger"]
DIVS = {"4": 0, "3": 1, "2": 2, "1": 3}
DATA_RE = re.compile(r'(<script id="race-data" type="application/json">)(.*?)(</script>)', re.S)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read()


def score_of(tier, div, lp):
    ti = TIERS.index(tier.capitalize())
    return 2800 + lp if ti >= 7 else ti * 400 + (DIVS[div] * 100 if div else 0) + lp


def utc(ts):
    return datetime.datetime.fromisoformat(ts).astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def scrape(slug):
    page = get(f"https://op.gg/lol/summoners/oce/{slug}").decode("utf-8", "replace")
    desc = html.unescape(re.search(r'<meta name="description" content="([^"]*)', page).group(1))
    # "AD Curry#OC / Platinum 2 28 LP / 280Win 269Lose Win rate 51% / Lissandra - 184Win 137Lose Win rate 57%, ..."
    m = re.search(r"/ (\w+)(?: ([1-4]))? (\d+) LP / (\d+)Win (\d+)Lose", desc)
    champs = [{"name": c.strip(), "wins": int(w), "losses": int(l)}
              for c, w, l in re.findall(r"(?:% / |, )([^,/]+?) - (\d+)Win (\d+)Lose", desc)]
    # op.gg's own daily LP snapshots, embedded in the page payload
    hist = []
    lh = re.search(r'\\"lpHistories\\":(\[.*?\])', page)
    if lh:
        for h in json.loads(lh.group(1).replace('\\"', '"')):
            t = h["tier_info"]
            label = (t.get("label") or "").split()
            div = label[1] if len(label) == 2 and label[1] in DIVS else None
            hist.append({"t": utc(h["created_at"]), "s": score_of(t["tier"], div, t["lp"])})
    if not m:
        return {"tier": "Unranked", "div": None, "lp": 0, "wins": 0, "losses": 0, "score": 0, "main": None,
                "champs": champs}, hist
    tier, div, lp, w, l = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5))
    return {"tier": tier, "div": div, "lp": lp, "wins": w, "losses": l, "score": score_of(tier, div, lp),
            "main": champs[0]["name"] if champs else None, "champs": champs}, hist


def champ_icon(name):
    key = re.sub(r"[^A-Za-z]", "", name or "")
    if not key:
        return None
    path = ROOT / "img" / f"{key}.png"
    if not path.exists():
        try:
            ver = json.loads(get("https://ddragon.leagueoflegends.com/api/versions.json"))[0]
            path.write_bytes(get(f"https://ddragon.leagueoflegends.com/cdn/{ver}/img/champion/{key}.png"))
        except Exception:
            return None
    return f"img/{key}.png"


def main():
    text = PAGE.read_text()
    m = DATA_RE.search(text)
    data = json.loads(m.group(2))
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    # one-time migration from the old combined history format
    old = data.pop("history", [])
    for i, p in enumerate(data["players"]):
        p.setdefault("hist", [{"t": h["t"], "s": h["s"][i]} for h in old])
    changed = False
    for p in data["players"]:
        r, ophist = scrape(p["slug"])
        r["icon"] = champ_icon(r["main"]) or p.get("icon")
        moved = (r["score"], r["wins"], r["losses"]) != (p.get("score"), p.get("wins"), p.get("losses"))
        p.update(r)
        hist = {h["t"]: h["s"] for h in p["hist"]}
        before = len(hist)
        for h in ophist:
            hist.setdefault(h["t"], h["s"])
        if moved or not p["hist"] or p["hist"][-1]["s"] != p["score"]:
            hist[now] = p["score"]
        changed = changed or moved or len(hist) != before
        p["hist"] = [{"t": t, "s": s} for t, s in sorted(hist.items())][-300:]
    data["updated"] = now
    blob = json.dumps(data, separators=(",", ":"))
    PAGE.write_text(text[:m.start(2)] + blob + text[m.end(2):])
    for p in data["players"]:
        print(f'{p["name"]}: {p["tier"]} {p["div"] or ""} {p["lp"]} LP ({p["wins"]}W {p["losses"]}L) score={p["score"]} points={len(p["hist"])}')
    print("changed" if changed else "no change")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"changed={str(changed).lower()}\n")


if __name__ == "__main__":
    main()
