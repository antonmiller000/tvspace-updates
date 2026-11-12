"""Open-web sources: search engines and Telegram directories.

Every source is "fetch a results page, pull every Telegram link out of it".
Sources fail independently (captcha, block, layout change) without stopping a search.
"""
from __future__ import annotations

import base64
import re
import urllib.parse

from .tme import Fetcher, extract_refs

# name -> (url template, page-parameter builder, pages available)
ENGINES = {
    "duckduckgo": ("https://html.duckduckgo.com/html/?q={q}&s={off}", lambda p: p * 30, 4),
    "bing": ("https://www.bing.com/search?q={q}&first={off}&count=30", lambda p: p * 30 + 1, 5),
    "google": ("https://www.google.com/search?q={q}&start={off}&num=30&hl=en", lambda p: p * 30, 3),
    "yandex": ("https://yandex.com/search/?text={q}&p={off}", lambda p: p, 3),
    "brave": ("https://search.brave.com/search?q={q}&offset={off}", lambda p: p, 3),
    "mojeek": ("https://www.mojeek.com/search?q={q}&s={off}", lambda p: p * 10 + 1, 3),
    "startpage": ("https://www.startpage.com/do/search?q={q}&page={off}", lambda p: p + 1, 2),
}

DIRECTORIES = {
    "tgramsearch": ("https://en.tgramsearch.com/search?query={q}&page={off}", lambda p: p + 1, 3),
    "combot": ("https://combot.org/top/telegram/groups?q={q}&page={off}", lambda p: p + 1, 2),
    "tgstat": ("https://tgstat.com/channels/search?q={q}&page={off}", lambda p: p + 1, 2),
    "telemetr": ("https://telemetr.io/en/channels?search={q}&page={off}", lambda p: p + 1, 2),
    "tlgrm": ("https://tlgrm.eu/channels?q={q}&page={off}", lambda p: p + 1, 2),
    "telegramchannels": ("https://telegramchannels.me/search?type=all&search={q}&page={off}", lambda p: p + 1, 2),
    "xtea": ("https://xtea.io/ts_en.html?q={q}&p={off}", lambda p: p + 1, 1),
}

QUERY_TEMPLATES = [
    "site:t.me {kw}",
    '"t.me" {kw} telegram channel',
    '"t.me" {kw} telegram group chat',
    '{kw} "t.me/+" OR "t.me/joinchat"',
    "site:t.me/s {kw}",
    "{kw} telegram каналы чаты t.me",
]

# Accounts that belong to the sources themselves, not to results.
IGNORE = {
    "tgramsearch", "tgramsearchbot", "combot", "combotnews", "tgstat", "tgstat_bot", "telemetr_io",
    "telemetrio", "tlgrm", "lyzemcom", "lyzembot", "mlyzembot", "xtea_io", "share", "telegram",
    "telegramchannels_me", "telemetr_me", "tg_analytics", "tgstat_com", "tgstat_ru",
}

_BING_RE = re.compile(r"[?&;]u=a1([A-Za-z0-9_-]+)")


def _decode_redirects(page: str) -> str:
    """Bing hides targets in base64 redirect links; append the decoded URLs."""
    extra = []
    for token in set(_BING_RE.findall(page)):
        try:
            extra.append(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "ignore"))
        except Exception:
            pass
    return page + "\n" + "\n".join(extra)


def tasks(terms: list[str], engines: bool, directories: bool, pages_scale: float = 1.0):
    """Yield (source, url) for every query to run."""
    out = []
    if engines:
        for name, (tpl, off, pages) in ENGINES.items():
            for kw in terms:
                for qi, qt in enumerate(QUERY_TEMPLATES):
                    n = max(1, round(pages * pages_scale)) if qi == 0 else 1
                    for p in range(n):
                        q = urllib.parse.quote_plus(qt.format(kw=kw))
                        out.append((name, tpl.format(q=q, off=off(p))))
    if directories:
        for name, (tpl, off, pages) in DIRECTORIES.items():
            for kw in terms:
                for p in range(max(1, round(pages * pages_scale))):
                    out.append((name, tpl.format(q=urllib.parse.quote_plus(kw), off=off(p))))
    return out


def run(fetcher: Fetcher, source: str, url: str) -> tuple[set[str], str]:
    """Return (refs, status-note)."""
    status, _final, body = fetcher.get(url, retries=1)
    if status != 200 or not body:
        return set(), f"HTTP {status or 'error'}"
    refs = extract_refs(_decode_redirects(body), mentions=source in DIRECTORIES) - IGNORE
    if not refs and re.search(r"captcha|anomaly|unusual traffic|just a moment|verifying your browser", body, re.I):
        return set(), "blocked (captcha)"
    return refs, "ok"
