"""Build the public data payload for the Pain-Point Radar SaaS.

Assembles every real pain point we have discovered (holdout + wave DBs) and
every product others are building (radar DB) into one browsable JSON:
exports/site/data.js  -> window.PAIN_DB = {...}

The SaaS front-end (exports/site/index.html) searches/filters this client-side
— static, EUR0, deployable anywhere.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import TypedDict

ROOT = Path("/home/zunnun/projects/SaasPainPonit")
SITE = ROOT / "exports/site"
HOLDOUT = ROOT / "data/reddit/automated_holdout.db"
WAVE = ROOT / "data/reddit/wave_n1.db"
RADAR = ROOT / "data/radar/radar.db"

SUB_PATTERNS = {
    "sweatystartup": "Kleingewerbe / Solo-Selbständige",
    "smallbusiness": "Kleingewerbe / Solo-Selbständige",
    "entrepreneur": "Gründer allgemein",
    "msp": "IT-Dienstleister (MSP)",
    "sysadmin": "IT-Administration",
    "propertymanagement": "Immobilienverwaltung",
    "commercialev": "Gewerbe-Immobilien",
    "logistics": "Logistik & Spedition",
    "freightbrokers": "Frachtenvermittlung / Logistik",
    "bookkeeping": "Buchhaltung",
    "quickbooks": "Buchhaltung",
    "accounting": "Buchhaltung / Steuer",
    "restaurants": "Gastronomie",
    "restaurantowners": "Gastronomie",
    "sales": "Vertrieb / Sales",
    "plumbing": "Handwerk (Sanitär)",
    "hvac": "Handwerk (HLK)",
    "construction": "Bau / Handwerk",
    "agency": "Agenturen",
    "pos": "Kassensysteme",
}


def sub_of(url: str) -> str:
    m = re.search(r"/r/(\w+)", url or "")
    return m.group(1) if m else "unbekannt"


def niche_of(url: str) -> str:
    s = sub_of(url)
    return SUB_PATTERNS.get(s.lower(), f"Community {s}")


class Pain(TypedDict):
    related: list[str]
    id: str
    pain: str
    family: str
    type: str
    actor: str
    job: str
    context: str
    workaround: str
    searching: bool
    quote: str
    url: str
    title: str
    sub: str
    niche: str
    date: str
    wave: bool


def load_obs(path: Path, wave: bool) -> list[Pain]:
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    out: list[Pain] = []
    try:
        rows = c.execute("""
            SELECT o.problem, o.problem_family, o.problem_type,
                   o.actor, o.job_to_be_done, o.context,
                   o.current_workaround, o.time_impact, o.financial_impact,
                   o.active_solution_search, si.url, si.title, si.published_at,
                   o.id
            FROM problem_observations o
            JOIN source_items si ON si.id = o.source_item_id
        """).fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        ev = c.execute(
            """SELECT excerpt FROM evidence_spans
               WHERE observation_id=? ORDER BY id LIMIT 1""",
            (r["id"],)).fetchone()
        out.append({
            "id": f"{'w' if wave else 'h'}{r['id']}",
            "pain": r["problem"],
            "family": r["problem_family"],
            "type": r["problem_type"],
            "actor": r["actor"] or "",
            "job": r["job_to_be_done"] or "",
            "context": r["context"] or "",
            "workaround": r["current_workaround"] or "",
            "searching": bool(r["active_solution_search"]),
            "quote": (ev["excerpt"] if ev else "")[:400],
            "url": r["url"] or "",
            "title": (r["title"] or "")[:140],
            "sub": sub_of(r["url"] or ""),
            "niche": niche_of(r["url"] or ""),
            "date": (r["published_at"] or "")[:10],
            "wave": wave,
            "related": [],
        })
    c.close()
    return out


class Product(TypedDict):
    name: str
    tagline: str
    url: str
    source: str
    date: str
    buckets: list[str]
    hits: list[str]


def load_products() -> list[Product]:
    c = sqlite3.connect(RADAR)
    c.row_factory = sqlite3.Row
    out: list[Product] = []
    try:
        rows = c.execute(
            "SELECT name, tagline, url, source, seen_date, buckets, pain_hits"
            " FROM products").fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        out.append({
            "name": r["name"],
            "tagline": (r["tagline"] or "").strip()[:240],
            "url": r["url"] or "",
            "source": r["source"],
            "date": r["seen_date"] or "",
            "buckets": json.loads(r["buckets"] or "[]"),
            "hits": json.loads(r["pain_hits"] or "[]"),
        })
    c.close()
    return out


def main() -> int:
    SITE.mkdir(parents=True, exist_ok=True)
    obs = load_obs(HOLDOUT, wave=False) + load_obs(WAVE, wave=True)
    # dedup by (url, pain prefix)
    seen: set[tuple[str, str]] = set()
    uniq: list[Pain] = []
    for o in obs:
        k = (o["url"], o["pain"][:60])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    products = load_products()
    # cross-link: for each pain, the buckets of products that address its niche
    by_bucket: dict[str, list[Product]] = {}
    for pr in products:
        for b in pr["buckets"]:
            by_bucket.setdefault(b, []).append(pr)
    niche_buckets = {
        "Gastronomie": ["restaurant-pos"],
        "Buchhaltung / Steuer": ["bookkeeping-finance"],
        "Immobilienverwaltung": ["property/ho-admin"],
        "Frachtenvermittlung / Logistik": ["logistics-freight"],
        "Handwerk (HLK)": ["field-service", "construction"],
        "Handwerk (Sanitär)": ["field-service", "construction"],
        "Bau / Handwerk": ["field-service", "construction"],
        "Kleingewerbe / Solo-Selbständige": ["field-service", "sales-crm",
                                              "marketing-ads", "phone-ai"],
        "Vertrieb / Sales": ["sales-crm"],
        "Agenturen": ["marketing-ads", "sales-crm"],
        "Buchhaltung": ["bookkeeping-finance"],
    }
    for o in uniq:
        scored: dict[str, int] = {}
        for b in niche_buckets.get(o["niche"], []):
            for pr in by_bucket.get(b, []):
                scored[pr["name"]] = scored.get(pr["name"], 0) + 1 + len(pr["hits"])
        ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
        o["related"] = [name for name, _ in ranked[:10]]
    niches = len({o["niche"] for o in uniq})
    payload: dict[str, object] = {
        "updated": "2026-09-23",
        "pains": uniq,
        "products": products,
        "stats": {
            "pains": len(uniq),
            "products": len(products),
            "niches": niches,
            "quotes": sum(1 for o in uniq if o["quote"]),
        },
    }
    js = "window.PAIN_DB = " + json.dumps(payload, ensure_ascii=False) + ";"
    (SITE / "data.js").write_text(js, encoding="utf-8")
    print(f"site/data.js: {len(uniq)} pains, {len(products)} products, "
          f"{niches} niches")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
