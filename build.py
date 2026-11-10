#!/usr/bin/env python3
"""Pokémon Yellow checklist generator.

Pulls Gen 1 data from PokeAPI (cached in .cache/) and writes a static,
GitHub Pages-ready site to docs/index.html.

    python build.py             # all 151 Pokémon
    python build.py --limit 20  # quick test run
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = "https://pokeapi.co/api/v2"
ROOT = Path(__file__).parent
CACHE = ROOT / ".cache"
OUT = ROOT / "docs"
GENS = ["generation-i", "generation-ii", "generation-iii", "generation-iv",
        "generation-v", "generation-vi", "generation-vii", "generation-viii"]
SPRITE = ("https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/"
          "pokemon/versions/generation-i/yellow/{}.png")
FALLBACK = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{}.png"
STATS = {"hp": "HP", "attack": "Atk", "defense": "Def",
         "special-attack": "SpA", "special-defense": "SpD", "speed": "Spe"}
NAMES = {"nidoran-f": "Nidoran♀", "nidoran-m": "Nidoran♂",
         "mr-mime": "Mr. Mime", "farfetchd": "Farfetch'd"}

# Hand-written notes for gifts / one-offs (edit freely).
SPECIAL = {
    25: "Your starter. Receive it from Professor Oak in Pallet Town.",
    1: "Gift in Cerulean City (needs a happy Pikachu).",
    4: "Gift on Route 24 (needs a happy Pikachu).",
    7: "Gift in Vermilion City (needs a happy Pikachu).",
    133: "Gift in the Celadon Mansion.",
    106: "Fighting Dojo, Saffron City. Choose Hitmonlee OR Hitmonchan.",
    107: "Fighting Dojo, Saffron City. Choose Hitmonlee OR Hitmonchan.",
    131: "Gift from an employee in Silph Co.",
    129: "Buy from the Route 4 Pokémon Center salesman.",
    138: "Revive the Helix Fossil at Cinnabar Lab (Mt. Moon fossil, pick one).",
    140: "Revive the Dome Fossil at Cinnabar Lab (Mt. Moon fossil, pick one).",
    142: "Revive the Old Amber from the Pewter Museum at Cinnabar Lab.",
    143: "Static encounter (Route 12 / 16). Wake it with the Poké Flute.",
    144: "Legendary bird, Seafoam Islands.",
    145: "Legendary bird, Power Plant.",
    146: "Legendary bird, Victory Road.",
    150: "Legendary, Cerulean Cave (post-game).",
    151: "Event-only in Yellow. Not obtainable in normal play.",
}


def get(path):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / (path.strip("/").replace("/", "_") + ".json")
    if f.exists():
        return json.loads(f.read_text())
    for attempt in range(4):
        try:
            r = requests.get(f"{API}/{path}", timeout=30)
            r.raise_for_status()
            data = r.json()
            f.write_text(json.dumps(data))
            return data
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    sys.exit(f"Failed to fetch {path}")


def pretty(slug):
    s = re.sub(r"^kanto-", "", slug)
    s = re.sub(r"-area$", "", s).replace("-", " ").title()
    return s.replace("Mt ", "Mt. ")


def last_id(url):
    return int(url.rstrip("/").split("/")[-1])


def yellow_encounters(pid):
    found = {}
    for e in get(f"pokemon/{pid}/encounters"):
        for vd in e["version_details"]:
            if vd["version"]["name"] != "yellow":
                continue
            loc = pretty(e["location_area"]["name"])
            for d in vd["encounter_details"]:
                o = found.setdefault((loc, d["method"]["name"]),
                                     {"lo": d["min_level"], "hi": d["max_level"], "chance": 0})
                o["lo"] = min(o["lo"], d["min_level"])
                o["hi"] = max(o["hi"], d["max_level"])
                o["chance"] = max(o["chance"], d["chance"])
    return [{"loc": k[0], "method": k[1], **v} for k, v in sorted(found.items())]


def describe(d):
    if not d:
        return "Special"
    if d.get("item"):
        return "Use " + d["item"]["name"].replace("-", " ").title()
    if d["trigger"]["name"] == "trade":
        return "Trade"
    if d.get("min_level"):
        return f"Level {d['min_level']}"
    return d["trigger"]["name"].replace("-", " ").title()


def walk(node, edges):
    frm = last_id(node["species"]["url"])
    for ev in node["evolves_to"]:
        to = last_id(ev["species"]["url"])
        d = ev["evolution_details"][0] if ev["evolution_details"] else {}
        edges.append((frm, to, describe(d)))
        walk(ev, edges)


def build_one(pid):
    p, s = get(f"pokemon/{pid}"), get(f"pokemon-species/{pid}")
    types = [t["type"]["name"] for t in p["types"]]
    past = sorted(p.get("past_types", []), key=lambda x: GENS.index(x["generation"]["name"]))
    if past:  # Gen 1 typings (e.g. Magnemite was pure Electric)
        types = [t["type"]["name"] for t in past[0]["types"]]
    entry = next((f["flavor_text"] for f in s["flavor_text_entries"]
                  if f["language"]["name"] == "en" and f["version"]["name"] == "yellow"), "")
    entry = re.sub(r"\s+", " ", entry.replace("\u00ad", "")).strip()
    return {
        "id": pid,
        "name": NAMES.get(p["name"], p["name"].replace("-", " ").title()),
        "genus": next((g["genus"] for g in s["genera"] if g["language"]["name"] == "en"), ""),
        "types": types,
        "stats": {STATS[x["stat"]["name"]]: x["base_stat"] for x in p["stats"]},
        "height": p["height"] / 10,
        "weight": p["weight"] / 10,
        "catch_rate": s["capture_rate"],
        "entry": entry,
        "sprite": SPRITE.format(pid),
        "fallback": FALLBACK.format(pid),
        "encounters": yellow_encounters(pid),
        "note": SPECIAL.get(pid, ""),
        "_chain": last_id(s["evolution_chain"]["url"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=151)
    n = ap.parse_args().limit
    print(f"Fetching {n} Pokémon (cached after first run)...")
    with ThreadPoolExecutor(8) as ex:
        mons = list(ex.map(build_one, range(1, n + 1)))

    edges = []
    for cid in sorted({m["_chain"] for m in mons}):
        walk(get(f"evolution-chain/{cid}")["chain"], edges)
    by_id = {m["id"]: m for m in mons}
    for m in mons:
        del m["_chain"]
        m["evolves_from"] = next(({"id": f, "how": h} for f, t, h in edges
                                  if t == m["id"] and f in by_id), None)
        m["evolves_to"] = [{"id": t, "how": h} for f, t, h in edges
                           if f == m["id"] and t in by_id]

    payload = json.dumps(mons, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = (ROOT / "template.html").read_text(encoding="utf-8").replace("__DATA__", payload)
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"Done -> {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
