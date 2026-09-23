"""Opportunity Radar: list what OTHERS are building (ProductHunt + HackerNews).

Philosophy pivot (owner decision 2026-09-23): stop slow from-scratch problem
archaeology; instead continuously ingest launches/competitors and match them
against our validated pain seeds. EUR0, no LLM needed for ingestion.

Sources (all public, no keys):
  - ProductHunt Atom feed  https://www.producthunt.com/feed
  - HackerNews via Algolia API (Show HN / Ask HN launch queries)

Stores every product seen into data/radar/radar.db (dedup by URL),
classifies by naive keyword buckets, cross-matches against the pain-seed
lexicon, and renders exports/radar.md as the standing opportunity board.
"""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path("/home/zunnun/projects/SaasPainPonit")
DB = ROOT / "data/radar/radar.db"
OUT = ROOT / "exports/radar.md"
UA = "Mozilla/5.0 (compatible; OpportunityRadar/0.1; research)"

ATOM = {"a": "http://www.w3.org/2005/Atom"}

BUCKETS = {
    "property/ho-admin": r"propert|landlord|tenant|rent|lease|inventar"
                         r"|immobil|housing|maintenance ticket",
    "restaurant-pos": r"restaurant|pos\b|point of sale|menu"
                      r"|table reservation|food service|kds\b|hospitality",
    "field-service": r"field service|plumber|trade|schedule|dispatch"
                     r"|invoice|job site|craftsman|contractor",
    "logistics-freight": r"freight|truck|broker|dispatch|load|carrier|logistic|tms\b",
    "bookkeeping-finance": r"bookkeep|accounting|invoic|financ|expense|tax|quickbooks|xero",
    "sales-crm": r"\bcrm\b|sales|lead|outreach|pipeline|prospect|deal",
    "phone-ai": r"answering|phone|call|ivr|voice agent|receptionist|missed call",
    "marketing-ads": r"marketing|ads\b|advertis|campaign|targeting|seo|social media",
    "construction": r"construct|builder|estimate|bid|blueprint|concrete|roof",
}

# pain seeds -> regex used to flag "someone is building FOR our validated pain"
PAIN_SEEDS = {
    "asset_inventory_small_pm": r"propert|landlord|tenant|inventar|asset track",
    "pos_ads_blocking": r"restaurant|pos\b|point of sale|kds\b",
    "vendor_lockin_exit": r"cancel|subscription manage|contract|lock-?in|offboarding",
    "phone_order_ai": r"answering|phone agent|voice ai|missed call|receptionist",
    "freight_broker_trust": r"freight|broker|carrier|load board|tms\b",
    "qb_migration": r"quickbooks|migrat|accounting",
    "pdf_to_data": r"\bocr\b|document extract|pdf to|data extract",
    "lead_followup_broken": r"lead|follow-?up|\bcrm\b|outreach",
    "menu_builder": r"menu|digital menu|qr code|restaurant website",
    "sales_forecast_why": r"sales|forecast|revenue|pipeline|deal analy",
    "impersonation_fraud": r"fraud|impersonat|phish|verify|authenticat",
    "gmb_phone_spam": r"google business|review|reputation|local seo",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as resp:  # noqa: S310
        return resp.read()


def init(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS products (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tagline TEXT,
        url TEXT,
        source TEXT NOT NULL,
        seen_date TEXT,
        buckets TEXT,
        pain_hits TEXT
    )""")
    conn.commit()


def classify(text: str) -> tuple[str, str]:
    low = text.lower()
    buckets = [k for k, rx in BUCKETS.items() if re.search(rx, low)]
    hits = [k for k, rx in PAIN_SEEDS.items() if re.search(rx, low)]
    return json.dumps(buckets), json.dumps(hits)


def upsert(conn: sqlite3.Connection, key: str, name: str, tagline: str,
           url: str, source: str, day: str) -> int:
    """Insert a product; returns 1 if it is new, 0 if already known."""
    exists = conn.execute(
        "SELECT 1 FROM products WHERE key=?", (key,)).fetchone()
    buckets, hits = classify(f"{name} {tagline or ''}")
    conn.execute(
        """INSERT INTO products (key,name,tagline,url,source,seen_date,
           buckets,pain_hits) VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET
             tagline=COALESCE(excluded.tagline, products.tagline),
             pain_hits=excluded.pain_hits""",
        (key, name, tagline, url, source, day, buckets, hits))
    return 0 if exists else 1


def ingest_producthunt(conn: sqlite3.Connection) -> int:
    raw = fetch("https://www.producthunt.com/feed")
    root = ElementTree.fromstring(raw)
    added = 0
    for e in root.findall("a:entry", ATOM):
        title = (e.findtext("a:title", default="", namespaces=ATOM) or "").strip()
        link_el = e.find("a:link", ATOM)
        href = (link_el.get("href") if link_el is not None else "") or ""
        content = e.findtext("a:content", default="", namespaces=ATOM) or ""
        tag = re.sub(r"<[^>]+>", " ", content).strip()[:220]
        pid = e.findtext("a:id", default=href, namespaces=ATOM) or href
        day = (e.findtext("a:updated", default="", namespaces=ATOM) or "")[:10]
        added += upsert(conn, f"ph:{pid}", title, tag, href, "producthunt", day)
    conn.commit()
    return added


def ingest_hn(conn: sqlite3.Connection) -> int:
    added = 0
    for q in ('"Show HN"', '"Launch"'):
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story"
               f"&query={urllib.parse.quote(q)}&hitsPerPage=50")
        data = json.loads(fetch(url))
        for h in data.get("hits", []):
            title = h.get("title") or ""
            ext = h.get("url") or ""
            text = f"{title} {ext}"
            key = f"hn:{h.get('objectID')}"
            day = (h.get("created_at") or "")[:10]
            added += upsert(conn, key, title[:120], text[:220], ext,
                            "hackernews", day)
    conn.commit()
    return added


def render(conn: sqlite3.Connection) -> None:
    rows = conn.execute("""SELECT name, tagline, url, source, seen_date,
        buckets, pain_hits FROM products
        WHERE pain_hits NOT IN ('[]','') ORDER BY seen_date DESC""").fetchall()
    stats = {
        r[0]: r[1] for r in conn.execute(
            "SELECT source, COUNT(*) FROM products GROUP BY source")
    }
    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    pain_total = conn.execute(
        "SELECT COUNT(*) FROM products WHERE pain_hits NOT IN ('[]','')"
    ).fetchone()[0]
    bucket_rows: dict[str, int] = {}
    for r in conn.execute("SELECT buckets FROM products"):
        for b in json.loads(r[0] or "[]"):
            bucket_rows[b] = bucket_rows.get(b, 0) + 1
    lines = [
        "# Opportunity Radar — was andere schon bauen",
        "",
        f"_Stand {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{total} Produkte gescannt ({stats}) · {pain_total} treffen unsere "
        "validierten Pain-Seeds_",
        "",
        "## 🗺️ Aktivitäts-Felder (Produkte pro Bucket, letzte Scans)",
        "",
    ]
    for b, n in sorted(bucket_rows.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {b}: {n}")
    lines += ["", "## 🎯 Treffer auf UNSERE Pain-Seeds (Wettbewerber-Check)", ""]
    if not rows:
        lines.append("- (noch keine Treffer)")
    for r in rows[:120]:
        buckets = json.loads(r[5] or "[]")
        hits = json.loads(r[6] or "[]")
        lines.append(
            f"- **{r[0]}** ({r[3]}, {r[4]}) — seeds: {', '.join(hits)}"
            f"{' | buckets: ' + ', '.join(buckets) if buckets else ''}\n"
            f"  {(r[1] or '').strip()[:160]}\n  {r[2] or ''}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"radar: {total} products | {pain_total} pain-seed hits -> {OUT}")


def main() -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    init(conn)
    n_ph = ingest_producthunt(conn)
    n_hn = ingest_hn(conn)
    render(conn)
    print(f"new: producthunt={n_ph} hackernews={n_hn}")
    conn.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
