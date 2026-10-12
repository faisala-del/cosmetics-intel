"""Fetchers: RSS/Atom feeds, Google News RSS, PubMed, Federal Register.

Every fetcher returns a list of "item" dicts with the same shape:
    id, title, url, source, published (ISO UTC), snippet, region_hint,
    section_hint, origin
A failing source raises; build.py catches it and records the error so one
broken feed never stops the whole run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import feedparser
import requests

GN_EDITIONS = {
    "India": ("en-IN", "IN", "IN:en"),
    "US": ("en-US", "US", "US:en"),
    "UK": ("en-GB", "GB", "GB:en"),
    "Canada": ("en-CA", "CA", "CA:en"),
    "Singapore": ("en-SG", "SG", "SG:en"),
}
DEFAULT_EDITION = ("en-US", "US", "US:en")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def clean(text: str | None, limit: int = 700) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def make_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title.lower()}".encode("utf-8")).hexdigest()[:12]


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:80]


def entry_date(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return dt.datetime(*value[:6], tzinfo=dt.timezone.utc)
    return None


def http_get(url: str, ua: str, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"User-Agent": ua}, timeout=30, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:  # network, 4xx, 5xx
            last_exc = exc
            time.sleep(2 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _item(title, url, source, published, snippet, region, hint, origin) -> dict:
    published = published or now_utc()
    title = clean(title, 300)
    return {
        "id": make_id(url or "", title),
        "title": title,
        "url": url or "",
        "source": source,
        "published": published.isoformat(),
        "snippet": clean(snippet),
        "region_hint": region,
        "section_hint": hint,
        "origin": origin,
    }


def fetch_feed(src: dict, days: int, ua: str, max_n: int) -> list[dict]:
    cutoff = now_utc() - dt.timedelta(days=days)
    feed = feedparser.parse(http_get(src["url"], ua).content)
    out = []
    for e in feed.entries:
        published = entry_date(e)
        if published and published < cutoff:
            continue
        out.append(_item(e.get("title", ""), e.get("link", ""), src["name"], published,
                         e.get("summary", ""), src.get("region", "Global"),
                         src.get("section_hint", "news"), "feed"))
    out.sort(key=lambda x: x["published"], reverse=True)
    return out[:max_n]


def fetch_google_news(q: str, region: str, hint: str, days: int, ua: str, max_n: int) -> list[dict]:
    hl, gl, ceid = GN_EDITIONS.get(region, DEFAULT_EDITION)
    query = quote_plus(f"{q} when:{days}d")
    url = f"https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"
    feed = feedparser.parse(http_get(url, ua).content)
    out = []
    for e in feed.entries[:max_n]:
        publisher = (e.get("source") or {}).get("title", "Google News")
        title = e.get("title", "")
        suffix = f" - {publisher}"
        if publisher and title.endswith(suffix):
            title = title[: -len(suffix)]
        # Google News gives headline + publisher only, so snippet stays empty.
        out.append(_item(title, e.get("link", ""), publisher, entry_date(e), "",
                         region, hint, "google_news"))
    return out


def fetch_pubmed(term: str, hint: str, days: int, ua: str, max_n: int, api_key: str | None = None) -> list[dict]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    params = {"db": "pubmed", "term": term, "reldate": days, "datetype": "pdat",
              "retmax": max_n, "retmode": "json", "sort": "date"}
    if api_key:
        params["api_key"] = api_key
    ids = http_get(base + "esearch.fcgi", ua, params=params).json()["esearchresult"].get("idlist", [])
    if not ids:
        return []
    fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    if api_key:
        fetch_params["api_key"] = api_key
    root = ET.fromstring(http_get(base + "efetch.fcgi", ua, params=fetch_params).content)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title_el = art.find(".//ArticleTitle")
        title = "".join(title_el.itertext()) if title_el is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
        journal = art.findtext(".//Journal/Title") or "PubMed"
        year = art.findtext(".//ArticleDate/Year")
        month = art.findtext(".//ArticleDate/Month")
        day = art.findtext(".//ArticleDate/Day")
        try:
            published = dt.datetime(int(year), int(month), int(day), tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            published = None
        out.append(_item(title, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", journal, published,
                         abstract, "Global", hint, "pubmed"))
    return out


def fetch_federal_register(term: str, days: int, ua: str, max_n: int) -> list[dict]:
    cutoff = (now_utc() - dt.timedelta(days=days)).date().isoformat()
    params = {
        "conditions[term]": term,
        "conditions[publication_date][gte]": cutoff,
        "order": "newest",
        "per_page": max_n,
        "fields[]": ["title", "html_url", "publication_date", "abstract", "agency_names"],
    }
    data = http_get("https://www.federalregister.gov/api/v1/documents.json", ua, params=params).json()
    out = []
    for doc in data.get("results", []):
        try:
            published = dt.datetime.fromisoformat(doc["publication_date"]).replace(tzinfo=dt.timezone.utc)
        except (KeyError, ValueError):
            published = None
        agencies = ", ".join(doc.get("agency_names") or [])
        out.append(_item(doc.get("title", ""), doc.get("html_url", ""), "Federal Register", published,
                         f"{agencies}. {doc.get('abstract') or ''}", "US", "regulation",
                         "federal_register"))
    return out


def dedupe(items: list[dict]) -> list[dict]:
    seen_id, seen_title, out = set(), set(), []
    for it in items:
        key = norm_title(it["title"])
        if it["id"] in seen_id or (key and key in seen_title):
            continue
        seen_id.add(it["id"])
        seen_title.add(key)
        out.append(it)
    return out
