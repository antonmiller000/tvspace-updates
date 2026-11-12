"""The discovery engine: seeds candidates from many sources, then snowballs.

Snowballing is what finds chats that Telegram's own search never shows:
every relevant channel is read for links, @mentions and forwards, each
newly found chat is checked for the keywords (name, description and its
own post history), and relevant ones are read in turn.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time
import traceback

from . import keywords, tme, websearch

PRESETS = {
    "quick": {"depth": 1, "history_pages": 1, "minutes": 10, "max_entities": 1500, "guesses": 80, "pages_scale": 0.5},
    "deep": {"depth": 2, "history_pages": 3, "minutes": 90, "max_entities": 8000, "guesses": 250, "pages_scale": 1.0},
    "exhaustive": {"depth": 4, "history_pages": 10, "minutes": 720, "max_entities": 40000, "guesses": 400, "pages_scale": 1.5},
}
DEFAULT_SOURCES = {"web": True, "directories": True, "guess": True, "crawl": True, "telegram": True}


class Job:
    def __init__(self, store, tg, query: str, extra: str = "", seeds: str = "", preset: str = "deep",
                 kinds: list[str] | None = None, sources: dict | None = None, workers: int = 4, **overrides):
        self.store, self.tg = store, tg
        self.terms = keywords.parse_terms(query, extra)
        if not self.terms:
            raise ValueError("Enter at least one keyword")
        self.matcher = keywords.Matcher(self.terms)
        self.p = dict(PRESETS.get(preset, PRESETS["deep"]))
        for k, v in overrides.items():
            if k in self.p and v not in (None, ""):
                self.p[k] = float(v) if k == "minutes" else int(float(v))
        self.sources = {**DEFAULT_SOURCES, **(sources or {})}
        self.kinds = kinds or ["channel", "group"]
        self.seeds = sorted(tme.extract_refs(seeds) | {r for r in map(tme.norm_ref, seeds.split()) if r})
        self.workers = max(1, min(int(workers), 8))
        self.params = {"terms": self.terms, "preset": preset, "kinds": self.kinds, "sources": self.sources,
                       "seeds": self.seeds, **self.p}
        self.id = store.create_job(query, self.params)

        self.fetcher = tme.Fetcher()
        self.ents: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)
        self.heap: list = []
        self.tg_heap: list = []
        self.seq = itertools.count()
        self.active = 0
        self.stop_flag = False
        self.status = "running"
        self.started = time.time()
        self.deadline = self.started + self.p["minutes"] * 60
        self.log: list[dict] = []
        self.stats = {"checked": 0, "found": 0, "relevant": 0, "channels": 0, "groups": 0, "bots": 0,
                      "posts": 0, "requests": 0, "queue": 0, "dead": 0}
        self.source_fail: dict[str, int] = {}
        self.source_found: dict[str, int] = {}
        self.use_tg = bool(self.sources.get("telegram") and tg and tg.ready())

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self._seed()
        for i in range(self.workers):
            threading.Thread(target=self._worker, args=(self.heap, False), daemon=True, name=f"job{self.id}-w{i}").start()
        if self.use_tg:
            threading.Thread(target=self._worker, args=(self.tg_heap, True), daemon=True, name=f"job{self.id}-tg").start()
        threading.Thread(target=self._monitor, daemon=True, name=f"job{self.id}-mon").start()

    def stop(self):
        with self.cv:
            self.stop_flag = True
            self.cv.notify_all()

    def note(self, msg: str):
        with self.lock:
            self.log.append({"t": time.time(), "msg": msg})
            del self.log[:-400]

    def snapshot(self) -> dict:
        with self.lock:
            s = dict(self.stats)
            s.update(queue=len(self.heap) + len(self.tg_heap), requests=self.fetcher.requests,
                     elapsed=int(time.time() - self.started), sources=dict(self.source_found),
                     telegram_account=self.use_tg)
            return s

    def _monitor(self):
        while True:
            time.sleep(1.5)
            with self.cv:
                idle = not self.heap and not self.tg_heap and self.active == 0
                timeout = time.time() > self.deadline
                if idle or timeout or self.stop_flag:
                    self.status = "stopped" if self.stop_flag else ("time limit" if timeout and not idle else "done")
                    self.stop_flag = True
                    self.cv.notify_all()
                    break
            self.store.update_job(self.id, "running", self.snapshot())
        deadline = time.time() + 40
        while self.active and time.time() < deadline:
            time.sleep(0.3)
        self.note(f"Finished: {self.status}. {self.stats['relevant']} relevant chats, {self.stats['posts']} matching posts.")
        self.store.update_job(self.id, self.status, self.snapshot(), time.time())

    def _push(self, prio: float, task: tuple, tg: bool = False):
        with self.cv:
            heapq.heappush(self.tg_heap if tg else self.heap, (prio, next(self.seq), task))
            self.cv.notify_all()

    def _worker(self, heap: list, is_tg: bool):
        while True:
            with self.cv:
                while not heap and not self.stop_flag:
                    self.cv.wait(1.0)
                if self.stop_flag:
                    return
                _, _, task = heapq.heappop(heap)
                self.active += 1
            try:
                getattr(self, "_t_" + task[0])(*task[1:])
            except Exception as e:
                self.note(f"{task[0]} {task[1] if len(task) > 1 else ''}: {type(e).__name__}: {e}")
                if type(e).__name__ != "TgError":
                    traceback.print_exc()
            finally:
                with self.cv:
                    self.active -= 1

    # ------------------------------------------------------------ seeding
    def _seed(self):
        self.note("Keywords: " + " | ".join(self.terms))
        for ref in self.seeds:
            self.candidate(ref, 0, "seed")
        if self.sources.get("web") or self.sources.get("directories"):
            jobs = websearch.tasks(self.terms, self.sources.get("web"), self.sources.get("directories"),
                                   self.p["pages_scale"])
            for i, (source, url) in enumerate(jobs):
                self._push(1 + i * 0.2, ("web", source, url))
            self.note(f"Queued {len(jobs)} web / directory queries")
        if self.sources.get("guess"):
            guesses = keywords.username_guesses(self.terms, self.p["guesses"])
            for i, g in enumerate(guesses):
                self.candidate(g, 0, "guess", prio=3 + i * 0.01)
            self.note(f"Probing {len(guesses)} likely usernames")
        if self.use_tg:
            for i, q in enumerate(keywords.search_variants(self.terms)):
                self._push(i, ("tg_search", q), tg=True)
            for i, t in enumerate(self.terms):
                self._push(0.5 + i, ("tg_posts", t), tg=True)
                self._push(0.6 + i, ("tg_mine", t), tg=True)
            self.note("Telegram account connected: using Telegram's internal search too")
        elif self.sources.get("telegram"):
            self.note("Telegram account not connected: running with open-web sources only")

    # ------------------------------------------------------------ candidates
    def candidate(self, ref: str, depth: int, source: str, parent: str | None = None, prio: float | None = None):
        ref = tme.norm_ref(ref) if not ref.startswith("+") else ref
        if not ref or ref in websearch.IGNORE:
            return
        label = source.split(":")[0]
        with self.lock:
            e = self.ents.get(ref)
            if e is None:
                if len(self.ents) >= self.p["max_entities"]:
                    return
                e = self.ents[ref] = {"ref": ref, "kind": "new", "depth": depth, "sources": {label},
                                      "inbound": set(), "matched": set(), "post_hits": 0, "searched": set(),
                                      "found": time.time(), "crawled": False}
                if parent:
                    e["inbound"].add(parent)
                if prio is None:
                    prio = 5 + depth * 10 - (4 if self.matcher.username_hits(ref) else 0)
                self._push(prio, ("inspect", ref))
                return
            changed = label not in e["sources"] or (parent and parent not in e["inbound"])
            e["sources"].add(label)
            if parent:
                e["inbound"].add(parent)
            e["depth"] = min(e["depth"], depth)
            if changed and e["kind"] not in ("new", "none", "user"):
                self._rescore(e)

    def _rescore(self, e: dict, save: bool = True):
        name_hits = set(self.matcher.hits(e.get("title", ""))) | set(self.matcher.username_hits(e["ref"]))
        desc_hits = set(self.matcher.hits(e.get("description", "")))
        with self.lock:
            was = e.get("relevant", False)
            e["matched"] = name_hits | desc_hits | set(e.get("post_terms", ()))
            e["relevant"] = bool(name_hits or desc_hits or e["post_hits"])
            e["score"] = round(10 * len(name_hits) + 5 * len(desc_hits) + min(e["post_hits"], 20)
                               + 0.5 * min(len(e["inbound"]), 10) + 0.5 * (len(e["sources"]) - 1), 1)
            if e["relevant"] and not was:
                self.stats["relevant"] += 1
        if save:
            self.store.save_entity(self.id, e)

    # ------------------------------------------------------------ tasks
    def _t_web(self, source: str, url: str):
        if self.source_fail.get(source, 0) >= 3:
            return
        refs, note = websearch.run(self.fetcher, source, url)
        with self.lock:
            if note != "ok":
                self.source_fail[source] = self.source_fail.get(source, 0) + 1
                if self.source_fail[source] == 3:
                    self.note(f"Source {source} unavailable ({note}); skipping it")
                return
            self.source_fail[source] = 0
            self.source_found[source] = self.source_found.get(source, 0) + len(refs)
        for r in refs:
            self.candidate(r, 0, source)

    def _t_inspect(self, ref: str):
        e = self.ents[ref]
        status, _u, body = self.fetcher.get(tme.info_url(ref))
        info = tme.parse_info(body) if status == 200 else {"kind": "none"}
        with self.lock:
            self.stats["checked"] += 1
            e["kind"] = info["kind"]
            if info["kind"] in ("none", "user"):  # personal accounts are never catalogued
                self.stats["dead"] += 1
                return
            e.update({k: info[k] for k in ("title", "description", "members", "verified", "has_preview")})
            self.stats["found"] += 1
            key = {"channel": "channels", "group": "groups", "bot": "bots"}.get(info["kind"])
            if key:
                self.stats[key] += 1
        self._rescore(e)
        expand = e["relevant"] and e["depth"] < self.p["depth"]
        if expand:
            for r in info["refs"]:
                self.candidate(r, e["depth"] + 1, "description", ref)
        if not self.sources.get("crawl") or ref.startswith("+"):
            return
        if info["kind"] == "channel" and info.get("has_preview"):
            # Relevant channels get read; others are first searched for the keywords.
            if e["relevant"] or e["depth"] <= self.p["depth"]:
                self._push(e["depth"] * 10 + (2 if e["relevant"] else 7), ("crawl", ref))
        if self.use_tg and info["kind"] in ("channel", "group") and e["depth"] <= self.p["depth"]:
            if info["kind"] == "group" or not info.get("has_preview"):
                self._push(e["depth"] * 10 + 5, ("tg_inside", ref), tg=True)
            if e["relevant"]:
                self._push(e["depth"] * 10 + 3, ("tg_related", ref), tg=True)

    def _record_posts(self, e: dict, posts: list[dict], term: str | None, follow: bool):
        hits = 0
        for p in posts:
            matched = self.matcher.hits(p["text"])
            if term and term not in matched:
                matched.append(term)
            if matched:
                hits += 1
                if p["channel"] == e["ref"]:
                    with self.lock:
                        key = (p["channel"], p["id"])
                        seen = e.setdefault("post_ids", set())
                        if key not in seen:
                            seen.add(key)
                            e["post_hits"] += 1
                            e.setdefault("post_terms", set()).update(matched)
                            self.stats["posts"] += 1
                    self.store.save_post(self.id, p, matched)
            if follow or matched:
                for r in p.get("refs") or tme.extract_refs(p["text"]):
                    self.candidate(r, e["depth"] + 1, "post", e["ref"])
        return hits

    def _t_crawl(self, ref: str):
        e = self.ents[ref]
        can_follow = e["depth"] < self.p["depth"]
        was_relevant = e.get("relevant", False)
        terms = self.terms[:8] if was_relevant else self.terms[:3]
        for term in terms:
            if term in e["searched"] or self.stop_flag:
                continue
            e["searched"].add(term)
            status, _u, body = self.fetcher.get(tme.preview_url(ref, q=term))
            if status != 200:
                break
            self._record_posts(e, tme.parse_posts(body)["posts"], term, follow=False)
        self._rescore(e)
        if not e["relevant"] or e["crawled"]:
            return
        if not was_relevant and self.use_tg:
            self._push(e["depth"] * 10 + 3, ("tg_related", ref), tg=True)
        e["crawled"] = True
        before = None
        for _page in range(self.p["history_pages"]):
            if self.stop_flag:
                break
            status, _u, body = self.fetcher.get(tme.preview_url(ref, before=before))
            if status != 200:
                break
            parsed = tme.parse_posts(body)
            self._record_posts(e, parsed["posts"], None, follow=can_follow)
            before = parsed["before"]
            if not before or not parsed["posts"]:
                break
        self._rescore(e)

    # ---- Telegram account tasks (single thread, rate limited)
    def _tg_ok(self) -> bool:
        return self.use_tg and self.tg.ready()

    def _t_tg_search(self, q: str):
        if not self._tg_ok():
            return
        refs = self.tg.search(q)
        with self.lock:
            self.source_found["telegram search"] = self.source_found.get("telegram search", 0) + len(refs)
        for r in refs:
            self.candidate(r, 0, "telegram search")

    def _tg_posts(self, label: str, refs: list[str], posts: list[dict]):
        with self.lock:
            self.source_found[label] = self.source_found.get(label, 0) + len(refs)
        for r in refs:
            self.candidate(r, 0, label)
        for p in posts:
            e = self.ents.get(p["channel"])
            if e:
                self._record_posts(e, [p], None, follow=False)
                if e["kind"] not in ("new", "none", "user"):
                    self._rescore(e)

    def _t_tg_posts(self, term: str):
        if self._tg_ok() and self.tg.posts_search_ok:
            self._tg_posts("telegram post search", *self.tg.search_posts(term))

    def _t_tg_mine(self, term: str):
        if self._tg_ok():
            self._tg_posts("my chats", *self.tg.search_my_chats(term))

    def _t_tg_related(self, ref: str):
        if not self._tg_ok():
            return
        e = self.ents[ref]
        if e["kind"] == "channel":
            for r in self.tg.similar(ref):
                self.candidate(r, e["depth"] + 1, "similar channels", ref)
        full = self.tg.full(ref)
        for r in full["linked"]:
            self.candidate(r, e["depth"], "linked chat", ref)
        if e["depth"] < self.p["depth"]:
            for r in tme.extract_refs(full["about"]):
                self.candidate(r, e["depth"] + 1, "description", ref)

    def _t_tg_inside(self, ref: str):
        """Keyword search inside public groups (no web preview exists for them)."""
        if not self._tg_ok():
            return
        e = self.ents[ref]
        was = e.get("relevant", False)
        for term in (self.terms[:5] if was else self.terms[:2]):
            if term in e["searched"]:
                continue
            e["searched"].add(term)
            self._record_posts(e, self.tg.search_in(ref, term), term, follow=e["depth"] < self.p["depth"])
        self._rescore(e)
        if e["relevant"] and not was:
            self._push(e["depth"] * 10 + 3, ("tg_related", ref), tg=True)
