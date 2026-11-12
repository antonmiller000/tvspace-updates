"""Fetching and parsing public t.me pages (no Telegram account needed)."""
from __future__ import annotations

import html
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

# Path words on t.me that are not usernames.
RESERVED = {
    "s", "c", "joinchat", "addstickers", "addemoji", "addtheme", "share", "proxy",
    "socks", "iv", "setlanguage", "login", "confirmphone", "invoice", "bg", "boost",
    "addlist", "m", "giftcode", "contact", "k", "a", "dl", "blog", "faq", "apps",
    "auth", "embed", "telegram_org", "nft", "stars", "premium", "username",
}

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/"
    r"(\+[A-Za-z0-9_-]{8,}|joinchat/[A-Za-z0-9_-]{8,}|s/[A-Za-z0-9_]+|[A-Za-z0-9_]+)",
    re.I,
)
_RESOLVE_RE = re.compile(r"tg://(?:resolve|join)\?(?:domain|invite)=([A-Za-z0-9_+-]+)", re.I)
_SUBDOMAIN_RE = re.compile(r"(?:https?://)?([A-Za-z][A-Za-z0-9_-]{3,31})\.t\.me\b", re.I)
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_@/.])@([A-Za-z][A-Za-z0-9_]{3,31})\b")
_TAG_RE = re.compile(r"<[^>]+>")


def norm_ref(raw: str) -> str | None:
    """Normalise a username / invite link to a canonical reference.

    Public usernames become lowercase ("durov"); invite links become "+HASH".
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    m = _LINK_RE.search(raw)
    if m:
        raw = m.group(1)
    raw = raw.lstrip("@")
    if raw.lower().startswith("joinchat/"):
        return "+" + raw[9:]
    if raw.startswith("+"):
        return raw if len(raw) >= 9 else None
    if raw.lower().startswith("s/"):
        raw = raw[2:]
    raw = raw.split("/")[0].split("?")[0]
    if not USERNAME_RE.match(raw) or raw.lower() in RESERVED:
        return None
    return raw.lower()


def extract_refs(text: str, mentions: bool = True) -> set[str]:
    """Find every Telegram username / invite link mentioned in text or HTML."""
    text = urllib.parse.unquote(html.unescape(text or ""))
    found: set[str] = set()
    for rx in (_LINK_RE, _RESOLVE_RE, _SUBDOMAIN_RE):
        for m in rx.finditer(text):
            ref = norm_ref(m.group(1))
            if ref:
                found.add(ref)
    if mentions:
        for m in _MENTION_RE.finditer(text):
            ref = norm_ref(m.group(1))
            if ref:
                found.add(ref)
    return found


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment or "")
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def parse_count(s: str) -> int | None:
    """'9 137 542' -> 9137542, '9.14M' -> 9140000, '12.3K' -> 12300."""
    s = (s or "").replace("\xa0", " ").strip()
    m = re.match(r"^(\d[\d\s.,]*)", s)
    if not m:
        return None
    num, rest = m.group(1).strip(), s[m.end():]
    suf = rest[:1].upper() if rest[:1] in "KkMm" and not rest[1:2].isalpha() else ""
    try:
        if suf:
            return int(float(num.replace(" ", "").replace(",", ".")) * (1000 if suf == "K" else 1_000_000))
        return int(re.sub(r"[^\d]", "", num))
    except ValueError:
        return None


class Fetcher:
    """Polite HTTP client: global rate limit, retries, back-off on 429."""

    def __init__(self, min_interval: float = 0.3, timeout: float = 25):
        self.min_interval = min_interval
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}
        self.requests = 0
        self.errors = 0

    def _wait(self, host: str):
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next.get(host, 0))
            self._next[host] = at + self.min_interval
        if at > now:
            time.sleep(at - now)

    def penalise(self, host: str, seconds: float):
        with self._lock:
            self._next[host] = max(self._next.get(host, 0), time.monotonic() + seconds)

    def get(self, url: str, retries: int = 3, headers: dict | None = None) -> tuple[int, str, str]:
        """Return (status, final_url, body). status 0 = network failure."""
        host = urllib.parse.urlsplit(url).netloc
        last = (0, url, "")
        for attempt in range(retries):
            self._wait(host)
            self.requests += 1
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read(3_000_000).decode("utf-8", "replace")
                    return r.status, r.geturl(), body
            except urllib.error.HTTPError as e:
                last = (e.code, url, "")
                if e.code in (429, 500, 502, 503):
                    self.penalise(host, 4 * (attempt + 1))
                    continue
                return last
            except Exception:
                self.errors += 1
                time.sleep(1 + attempt)
        return last


def _first(rx: str, text: str, flags=re.S) -> str | None:
    m = re.search(rx, text, flags)
    return m.group(1) if m else None


def parse_info(page: str) -> dict:
    """Parse https://t.me/<ref>. Returns {'kind': 'none'} if nothing is there."""
    title = _first(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', page)
    if not title or not strip_tags(title):
        return {"kind": "none"}
    extra = strip_tags(" ".join(re.findall(r'<div class="tgme_page_extra"[^>]*>(.*?)</div>', page, re.S)))
    button = strip_tags(_first(r'class="tgme_action_button_new[^"]*"[^>]*>(.*?)</a>', page) or "")
    desc_html = _first(r'<div class="tgme_page_description[^"]*"[^>]*>(.*?)</div>', page) or ""
    low, btn = extra.lower(), button.lower()
    members = None
    if "subscriber" in low:
        kind = "channel"
    elif "member" in low:
        kind = "group"
    elif "bot" in btn or "monthly user" in low:
        kind = "bot"
    elif "channel" in btn:
        kind = "channel"
    elif "group" in btn:
        kind = "group"
    else:
        kind = "user"
    if kind in ("channel", "group"):
        members = parse_count(extra.split(",")[0])
    return {
        "kind": kind,
        "title": strip_tags(title).replace("✔", "").strip(),
        "description": strip_tags(desc_html),
        "members": members,
        "verified": "verified-icon" in title,
        "has_preview": 'tgme_page_context_link' in page and "/s/" in page,
        "refs": extract_refs(desc_html),
    }


def parse_posts(page: str) -> dict:
    """Parse https://t.me/s/<channel>[?q=...] into posts and outgoing references."""
    posts = []
    chunks = page.split('tgme_widget_message_wrap')[1:]
    for chunk in chunks:
        post = _first(r'data-post="([^"]+)"', chunk)
        if not post or "/" not in post:
            continue
        channel, pid = post.rsplit("/", 1)
        text_html = _first(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>\s*(?:<div class="tgme_widget_message_(?:footer|reactions|inline)|</div>)', chunk) \
            or _first(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk) or ""
        fwd = _first(r'tgme_widget_message_forwarded_from_name"\s+href="([^"]+)"', chunk)
        refs = extract_refs(text_html)
        # Link previews, buttons and reply headers also carry links.
        for href in re.findall(r'href="([^"]+)"', chunk):
            if "t.me/" in href or "telegram.me/" in href or href.startswith("tg://"):
                refs |= extract_refs(href, mentions=False)
        fwd_ref = norm_ref(fwd) if fwd else None
        if fwd_ref:
            refs.add(fwd_ref)
        refs.discard(channel.lower())
        posts.append({
            "channel": channel.lower(),
            "id": int(pid) if pid.isdigit() else 0,
            "date": _first(r'<time datetime="([^"]+)"', chunk) or "",
            "views": parse_count(_first(r'tgme_widget_message_views">([^<]*)', chunk) or ""),
            "text": strip_tags(text_html),
            "forwarded_from": fwd_ref,
            "refs": refs,
        })
    before = _first(r'data-before="(\d+)"', page)
    return {"posts": posts, "before": int(before) if before else None}


def info_url(ref: str) -> str:
    return "https://t.me/" + ref


def preview_url(username: str, q: str | None = None, before: int | None = None) -> str:
    params = {}
    if q:
        params["q"] = q
    if before:
        params["before"] = before
    return f"https://t.me/s/{username}" + ("?" + urllib.parse.urlencode(params) if params else "")
