"""Widening a search beyond the exact words: translations and learned related topics."""
from __future__ import annotations

import json
import re
import urllib.parse
from collections import Counter

from .keywords import STOP, _words, stem
from .tme import Fetcher

LANGUAGES = {"en": "English", "ru": "Russian", "uk": "Ukrainian", "de": "German", "es": "Spanish",
             "fr": "French", "tr": "Turkish", "fa": "Persian", "ar": "Arabic", "pt": "Portuguese",
             "it": "Italian", "zh": "Chinese", "hi": "Hindi", "id": "Indonesian", "uz": "Uzbek"}


def _guess_lang(text: str) -> str:
    if re.search(r"[іїєґ]", text.lower()):
        return "uk"
    if re.search(r"[а-яё]", text.lower()):
        return "ru"
    if re.search(r"[؀-ۿ]", text):
        return "ar"
    return "en"


def translate(fetcher: Fetcher, text: str, lang: str) -> str | None:
    """Translate a search term with free public endpoints; None if unavailable or unchanged."""
    if _guess_lang(text) == lang:
        return None
    q = urllib.parse.quote(text)
    out = None
    status, _u, body = fetcher.get(
        f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={lang}&dt=t&q={q}", retries=1)
    if status == 200 and body.startswith("["):
        try:
            out = "".join(part[0] for part in json.loads(body)[0] if part[0])
        except Exception:
            out = None
    if not out:
        status, _u, body = fetcher.get(
            f"https://api.mymemory.translated.net/get?q={q}&langpair={_guess_lang(text)}|{lang}", retries=1)
        if status == 200:
            try:
                data = json.loads(body)
                if str(data.get("responseStatus")) == "200":
                    out = data["responseData"]["translatedText"]
            except Exception:
                out = None
    out = " ".join((out or "").split()).strip(" .!?\"'").lower()
    if not out or out == text.lower() or len(out) > 80:
        return None
    return out


def learn_related(exact_titles: list[str], other_titles: list[str], known_terms: list[str], limit: int = 6) -> list[str]:
    """Words typical for the names of matching chats but rare in other chats' names
    (e.g. 'tesla' for electric cars). Needs a decent sample of both to avoid generic words."""
    if len(exact_titles) < 12 or len(other_titles) < 60 or limit <= 0:
        return []
    have = [stem(w) for t in known_terms for w in _words(t)]

    def toks(text):
        out = set()
        for w in re.findall(r"[^\W\d_]{3,}", text.lower()):
            st = stem(w)
            if w not in STOP and not any(st.startswith(h) or h.startswith(st) for h in have):
                out.add(w)
        return out

    exact, other, surface = Counter(), Counter(), {}
    for t in exact_titles:
        ws = toks(t)
        exact.update({stem(w) for w in ws})
        for w in ws:
            surface.setdefault(stem(w), w)
    for t in other_titles:
        other.update({stem(w) for w in toks(t)})
    need = max(3, len(exact_titles) // 12)
    rate = len(exact_titles) / len(other_titles)
    cand = []
    for st, n in exact.items():
        # must be at least 8x more common among matching chats than elsewhere
        if n >= need and len(st) >= 3 and n / len(exact_titles) >= 8 * (other[st] + 0.5) / len(other_titles):
            cand.append((n, st))
    cand.sort(reverse=True)
    return [surface[st] for _n, st in cand[:limit]]
