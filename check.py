#!/usr/bin/env python3
"""Proverava obaveštenja JGSP Novi Sad i šalje notifikaciju preko ntfy."""
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# HTTPS sertifikat sajta ne važi za ovaj domen, pa se koristi HTTP.
BASE_URL = "http://www.gspns.co.rs"
PAGES = ["/aktuelno", "/vazna-obavestenja"]
SEEN_FILE = Path(__file__).with_name("seen.json")
HEADERS = {"User-Agent": "jgsp-notifier/1.0"}

# 11А/11Б ćirilicom i 11A/11B latinicom, ali ne i datum kao "11. novembra".
LINE_RE = re.compile(r"(?<![\d.])11(?:[\s-]?[АБAB]|[абab])(?![^\W\d_])")
# "11" bez slova, proverava se samo u naslovu.
BARE_11_RE = re.compile(r"(?<![\d.])11(?![\d.])")
# Naslov navodi konkretne linije, npr. "Линија 52" ili "Линије 1, 17".
NAMES_LINES_RE = re.compile(r"(?:линиј|linij)\w*\s+\d", re.IGNORECASE)


def fetch(path):
    request = urllib.request.Request(BASE_URL + path, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except OSError:
            if attempt == 2:
                raise
            time.sleep(30)


def to_text(fragment):
    fragment = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse(page):
    page = page.split("<footer", 1)[0]
    items = []
    for block in re.split(r"""<div\s+class=["']?vest["']?\s*>""", page)[1:]:
        title = re.search(r"""(?s)class=["']?vest-naslov["']?\s*>(.*?)</div>""", block)
        date = re.search(r"""(?s)class=["']?vest-datum["']?\s*>(.*?)</div>""", block)
        if title:
            items.append({
                "title": to_text(title.group(1)),
                "date": to_text(date.group(1)) if date else "",
                "body": to_text(block[(date or title).end():]),
            })
    return items


def classify(item):
    if LINE_RE.search(f"{item['title']} {item['body']}") or BARE_11_RE.search(item["title"]):
        return "line"
    if not NAMES_LINES_RE.search(item["title"]):
        return "general"
    return None


def notify(topic, title, message, click, priority):
    payload = {"topic": topic, "title": title, "message": message,
               "click": click, "priority": priority}
    request = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(payload).encode(),
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=30).close()


def main():
    dry_run = "--dry-run" in sys.argv
    topic = None if dry_run else os.environ["NTFY_TOPIC"]
    first_run = not SEEN_FILE.exists()
    seen = set() if first_run else set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))

    for path in PAGES:
        items = parse(fetch(path))
        if not items:
            raise RuntimeError(f"{path}: nema obaveštenja, možda se sajt promenio")
        for item in items:
            kind = classify(item)
            if dry_run:
                print(f"{kind or '-':8} {item['date']:11} {item['title']}")
                continue
            key = f"{path}|{item['date']}|{item['title']}"
            if key in seen:
                continue
            if kind and not first_run:
                label = "11A/11B" if kind == "line" else "JGSP obaveštenje"
                notify(topic, f"{label}: {item['title']}"[:200],
                       f"{item['date']}\n{item['body'][:600]}".strip(),
                       BASE_URL + path, 4 if kind == "line" else 3)
            seen.add(key)

    if dry_run:
        return
    if first_run:
        notify(topic, "JGSP provera radi", f"Zapamćeno obaveštenja: {len(seen)}.",
               BASE_URL + PAGES[0], 3)
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")


if __name__ == "__main__":
    main()
