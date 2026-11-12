"""Query handling: keyword terms, relevance matching, username guessing."""
from __future__ import annotations

import re
import unicodedata

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e", "є": "e",
    "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}

SUFFIXES = ["", "s", "_channel", "channel", "_chat", "chat", "_group", "group", "_news", "news",
            "_official", "official", "_community", "community", "_hub", "hub", "_club", "club",
            "_info", "info", "_live", "live", "_daily", "daily", "_world", "world", "_talk",
            "_forum", "forum", "_tg", "tg", "_ru", "_en", "_ua", "_uk", "_de", "_es", "hq", "_hq",
            "_today", "today", "_now", "_pro", "pro", "_base", "_room", "_zone", "online",
            "_online", "1", "2", "_1", "24", "_24"]
PREFIXES = ["the", "the_", "my", "real", "all", "all_", "best", "top", "top_", "we", "i",
            "tg", "tg_", "chat_", "news_", "official_", "team", "club_", "pro", "its"]


def translit(s: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in s.lower())


def ascii_fold(s: str) -> str:
    s = translit(s)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def parse_terms(query: str, extra: str = "") -> list[str]:
    """Split user input into search terms. Each line / comma-separated item is one term."""
    terms: list[str] = []
    for part in re.split(r"[\n,;]+", f"{query}\n{extra}"):
        t = " ".join(part.split()).strip().lower()
        if t and t not in terms:
            terms.append(t)
    return terms


def _words(term: str) -> list[str]:
    return [w for w in re.findall(r"[^\W_]+", term.lower()) if len(w) >= 2] or [term.lower()]


class Matcher:
    """A text matches a term when every word of that term occurs in the text."""

    def __init__(self, terms: list[str]):
        self.terms = terms
        self._words = {t: _words(t) for t in terms}
        self._squashed = {t: {re.sub(r"[^a-z0-9]", "", ascii_fold(t)), re.sub(r"[\W_]", "", t)} - {""}
                          for t in terms}

    def hits(self, text: str) -> list[str]:
        low = (text or "").casefold()
        if not low:
            return []
        return [t for t in self.terms if all(w.casefold() in low for w in self._words[t])]

    def username_hits(self, username: str) -> list[str]:
        u = re.sub(r"[^a-z0-9]", "", (username or "").lower())
        if not u:
            return []
        return [t for t in self.terms if any(len(s) >= 3 and s in u for s in self._squashed[t])]


def username_guesses(terms: list[str], limit: int = 400) -> list[str]:
    """Plausible usernames built from the keywords (probed directly on t.me)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str):
        name = re.sub(r"_+", "_", name).strip("_")
        if 5 <= len(name) <= 32 and re.match(r"^[a-z][a-z0-9_]+$", name) and name not in seen:
            seen.add(name)
            out.append(name)

    stems: list[str] = []
    for t in terms:
        words = [re.sub(r"[^a-z0-9]", "", ascii_fold(w)) for w in t.split()]
        words = [w for w in words if w]
        if not words:
            continue
        for stem in ("".join(words), "_".join(words), "".join(reversed(words)) if len(words) == 2 else ""):
            if stem and stem not in stems:
                stems.append(stem)
    # Round-robin over affixes so every stem gets its most likely variants first.
    for suf in SUFFIXES:
        for stem in stems:
            add(stem + suf)
    for pre in PREFIXES:
        for stem in stems:
            add(pre + stem)
    return out[:limit]


def search_variants(terms: list[str]) -> list[str]:
    """Extra query strings for Telegram's own (prefix-based) search."""
    out: list[str] = []
    for t in terms:
        cands = [t, ascii_fold(t), t.replace(" ", ""), t.replace(" ", "_")]
        cands += [w for w in t.split() if len(w) >= 4]
        for extra in ("chat", "group", "news", "channel", "чат", "новости", "канал"):
            cands.append(f"{t} {extra}")
        for c in cands:
            c = c.strip()
            if c and c not in out:
                out.append(c)
    return out
