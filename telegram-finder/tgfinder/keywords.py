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


STOP = set("""a an and are as at be by for from in is it of on or the to with your our you we new all best top
и в во на с со к по за из у о об от для не это как что или а но наш ваш все мы вы
і й та на з до від для це як що або про
channel channels group groups chat chats news official telegram tg bot https http www com org info
канал каналы группа группы чат чаты новости официальный телеграм телеграмм подписывайтесь подписаться
канали група групи чати новини""".split())


def _words(term: str) -> list[str]:
    ws = [w for w in re.findall(r"[^\W_]+", term.lower()) if len(w) >= 2]
    return [w for w in ws if w not in STOP] or ws or [term.lower()]


def stem(w: str) -> str:
    """Crude suffix stripping so word forms match (cars/car, электромобили/электромобилей)."""
    w = w.lower()
    if re.search(r"[а-яёіїєґ]", w):
        return w[:-2] if len(w) >= 7 else w[:-1] if len(w) >= 5 else w
    if len(w) >= 5 and w.endswith("ies"):
        return w[:-3]
    if len(w) >= 7 and w.endswith("ing"):
        return w[:-3]
    if len(w) >= 6 and w.endswith("es"):
        return w[:-2]
    if len(w) >= 4 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _word_rx(w: str):
    st = stem(w)
    tail = r"(?![^\W_])" if len(w) <= 3 else ""  # very short words must match whole
    return re.compile(r"(?<![^\W_])" + re.escape(st.casefold()) + tail)


class Matcher:
    """Graded matching.

    Strong terms are what the user asked for (plus translations); weak terms are
    related topics learned during the search. A *full* hit means every word of a
    term occurs (any word form); a *partial* hit means only some words do.
    """

    def __init__(self, terms: list[str], weak: list[str] | None = None):
        self.terms = list(terms)
        self.weak = [t for t in (weak or []) if t not in self.terms]
        self._rx = {t: [_word_rx(w) for w in _words(t)] for t in self.terms + self.weak}
        self._sq = {t: self._squash(t) for t in self.terms + self.weak}

    @staticmethod
    def _squash(term: str) -> set[str]:
        ws = _words(term)
        forms = {"".join(stem(w) for w in ws), "".join(ws)}
        forms |= {re.sub(r"[^a-z0-9]", "", ascii_fold(f)) for f in list(forms)}
        return {f for f in forms if len(f) >= 4}

    def _grade(self, term: str, low: str) -> float:
        rx = self._rx[term]
        n = sum(1 for r in rx if r.search(low))
        if n == len(rx):
            return 1.0
        if len(rx) > 1 and any(f in low for f in self._sq[term] if len(f) >= 7):
            return 1.0  # written together: #ElectricCars
        return n / len(rx)

    def grades(self, text: str) -> tuple[list[str], list[str]]:
        """(full hits of strong terms, weaker hits: partial strong + full weak)."""
        low = (text or "").casefold()
        if not low:
            return [], []
        full, part = [], []
        for t in self.terms:
            g = self._grade(t, low)
            if g == 1.0:
                full.append(t)
            elif g >= 0.5:
                part.append(t)
        part += [t for t in self.weak if self._grade(t, low) == 1.0]
        return full, part

    def hits(self, text: str) -> list[str]:
        return self.grades(text)[0]

    def username_grades(self, username: str) -> tuple[list[str], list[str]]:
        u = re.sub(r"[^a-z0-9]", "", (username or "").lower())
        tokens = set(re.split(r"[_\d]+", (username or "").lower()))
        if not u:
            return [], []

        def ok(t):
            if any(f in u for f in self._sq[t]):
                return True
            ws = _words(t)
            return len(ws) == 1 and ascii_fold(ws[0]) in tokens
        return [t for t in self.terms if ok(t)], [t for t in self.weak if ok(t)]

    def username_hits(self, username: str) -> list[str]:
        return self.username_grades(username)[0]


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
