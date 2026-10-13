"""Emails the items that are new since the last email.

Optional: if SMTP_USER is not set, this does nothing and exits cleanly, so the
workflow keeps working without email.

Environment variables (set as GitHub repository secrets):
    SMTP_USER      sending address, e.g. yourname@gmail.com
    SMTP_PASSWORD  an app password (NOT your normal Gmail password)
    MAIL_TO        recipient(s), comma separated; defaults to SMTP_USER
    SMTP_HOST      default smtp.gmail.com
    SMTP_PORT      default 465 (SSL); 587 uses STARTTLS
    SITE_URL       optional; otherwise built from GITHUB_REPOSITORY

    python -m scripts.send_email --dry-run   prints the email instead of sending it
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache.json"
BRIEFING = ROOT / "site" / "data" / "briefing.json"

ORDER = ["regulation", "ingredients", "pharma", "technology", "formulation", "company", "news", "market"]
TITLES = {
    "regulation": "Regulation", "ingredients": "Ingredients", "pharma": "Pharma and cosmetics crossover",
    "technology": "New technologies", "formulation": "Formulation updates", "company": "Company updates",
    "news": "Beauty and personal care news", "market": "Market trends",
}
MAX_PER_SECTION = 8
MAX_AGE_DAYS = 7  # never email items older than this, even on the first run


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def safe_url(u: str | None) -> str | None:
    try:
        p = urlparse(u or "")
        return u if p.scheme in ("http", "https") and p.netloc else None
    except ValueError:
        return None


def pick_new(cache: dict) -> list[dict]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    items = [v for v in cache.values()
             if v.get("relevant") and not v.get("emailed") and v.get("published", "") >= cutoff]
    items.sort(key=lambda x: x["published"], reverse=True)
    return items


def site_url() -> str:
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return ""


def group(items: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for it in items:
        sec = "pharma" if it.get("borderline") and it["section"] != "regulation" else it["section"]
        out.setdefault(sec, []).append(it)
    return out


def build_message(items: list[dict], digest: list[dict], sender: str, to: list[str]) -> EmailMessage:
    today = dt.date.today().strftime("%d %b %Y")
    n_reg = sum(1 for i in items if i.get("regulatory"))
    url = site_url()
    groups = group(items)

    text = [f"Cosmetics briefing, {today}", f"{len(items)} new items, {n_reg} regulatory.", ""]
    body = [f"<h2 style='font-family:Georgia,serif;margin:0 0 4px'>Cosmetics briefing, {html.escape(today)}</h2>",
            f"<p style='color:#53636B;margin:0 0 16px'>{len(items)} new items, {n_reg} regulatory.</p>"]

    if digest:
        text.append("WHAT CHANGED")
        body.append("<h3 style='margin:16px 0 6px'>What changed</h3><ul style='padding-left:18px'>")
        for d in digest:
            text.append(f"- {d['text']}")
            body.append(f"<li style='margin-bottom:6px'>{html.escape(d['text'])}</li>")
        body.append("</ul>")
        text.append("")

    for sec in ORDER:
        rows = groups.get(sec)
        if not rows:
            continue
        text.append(TITLES[sec].upper())
        body.append(f"<h3 style='margin:20px 0 6px;color:#0B6E6E'>{html.escape(TITLES[sec])} ({len(rows)})</h3>")
        for it in rows[:MAX_PER_SECTION]:
            link = safe_url(it.get("url"))
            regions = ", ".join(it.get("regions") or [])
            flag = " [REGULATORY]" if it.get("regulatory") else ""
            text.append(f"- {it['headline']}{flag} ({regions}; {it.get('source','')})")
            if link:
                text.append(f"  {link}")
            head = html.escape(it["headline"])
            head_html = f"<a href='{html.escape(link)}' style='color:#15232B'>{head}</a>" if link else head
            tag = " <span style='color:#A4286A;font-weight:600'>Regulatory</span>" if it.get("regulatory") else ""
            body.append(f"<p style='margin:0 0 8px'>{head_html}{tag}<br>"
                        f"<span style='font-size:13px;color:#53636B'>{html.escape(regions)} · "
                        f"{html.escape(it.get('source') or '')}</span></p>")
        if len(rows) > MAX_PER_SECTION:
            more = len(rows) - MAX_PER_SECTION
            text.append(f"  ...and {more} more on the website")
            body.append(f"<p style='font-size:13px;color:#53636B'>...and {more} more on the website.</p>")
        text.append("")

    if url:
        text.append(f"Full dashboard: {url}")
        body.append(f"<p style='margin-top:20px'><a href='{html.escape(url)}'>Open the full dashboard</a></p>")
    text.append("Summaries are generated automatically from headlines and snippets. Check each source before relying on it.")
    body.append("<p style='font-size:12px;color:#53636B;margin-top:16px'>Summaries are generated automatically "
                "from headlines and snippets. Check each source before relying on it. Not legal or investment advice.</p>")

    msg = EmailMessage()
    msg["Subject"] = f"Cosmetics briefing {today}: {len(items)} new, {n_reg} regulatory"
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content("\n".join(text))
    msg.add_alternative("<div style='font-family:Arial,sans-serif;max-width:680px;line-height:1.5'>"
                        + "".join(body) + "</div>", subtype="html")
    return msg


def send(msg: EmailMessage, user: str, password: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the email instead of sending")
    args = ap.parse_args()

    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    to = [a.strip() for a in (os.environ.get("MAIL_TO") or user).split(",") if a.strip()]

    if not args.dry_run and not (user and password and to):
        print("Email not configured (SMTP_USER / SMTP_PASSWORD / MAIL_TO). Skipping.")
        return 0

    cache = load(CACHE, {})
    items = pick_new(cache)
    if not items:
        print("No new items to email.")
        return 0

    digest = load(BRIEFING, {}).get("digest", [])
    msg = build_message(items, digest, user or "briefing@example.com", to or ["you@example.com"])
    if args.dry_run:
        print(msg.get_body(preferencelist=("plain",)).get_content())
        return 0

    send(msg, user, password)
    for it in items:
        cache[it["id"]]["emailed"] = True
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Emailed {len(items)} items to {', '.join(to)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
