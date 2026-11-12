"""SQLite persistence for searches, found chats and matching posts."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, finished REAL,
  query TEXT, params TEXT, status TEXT, stats TEXT);
CREATE TABLE IF NOT EXISTS entities(
  job_id INTEGER, ref TEXT, kind TEXT, title TEXT, description TEXT, members INTEGER,
  verified INTEGER, score REAL, relevant INTEGER, depth INTEGER, sources TEXT, matched TEXT,
  inbound INTEGER, post_hits INTEGER, found REAL,
  PRIMARY KEY(job_id, ref));
CREATE TABLE IF NOT EXISTS posts(
  job_id INTEGER, channel TEXT, post_id INTEGER, date TEXT, views INTEGER, text TEXT,
  matched TEXT, PRIMARY KEY(job_id, channel, post_id));
CREATE INDEX IF NOT EXISTS ent_job ON entities(job_id, relevant, score);
-- Every chat ever seen, across all searches: lets a new search answer instantly
-- and tell "new" chats from ones found before.
CREATE TABLE IF NOT EXISTS known(
  ref TEXT PRIMARY KEY, first_seen REAL, first_job INTEGER, kind TEXT, title TEXT,
  description TEXT, members INTEGER, verified INTEGER, last_post TEXT, online INTEGER,
  photo TEXT, checked REAL);
"""
# Columns added after the first release (name, type).
ENTITY_EXTRA = [("last_post", "TEXT"), ("online", "INTEGER"), ("activity", "TEXT"),
                ("is_new", "INTEGER"), ("photo", "TEXT"), ("first_seen", "REAL"), ("level", "TEXT")]
ENTITY_COLS = ["job_id", "ref", "kind", "title", "description", "members", "verified", "score",
               "relevant", "depth", "sources", "matched", "inbound", "post_hits", "found",
               "last_post", "online", "activity", "is_new", "photo", "first_seen", "level"]

ENTITY_SORTS = {
    "score": "relevant DESC, score DESC, members DESC",
    "members": "members DESC",
    "title": "title COLLATE NOCASE ASC",
    "found": "found DESC",
    "hits": "post_hits DESC, score DESC",
    "recent": "last_post DESC, score DESC",
}


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            have = {r[1] for r in self.db.execute("PRAGMA table_info(entities)")}
            for name, typ in ENTITY_EXTRA:
                if name not in have:
                    self.db.execute(f"ALTER TABLE entities ADD COLUMN {name} {typ}")
            if "is_new" not in have:  # upgrading: remember everything earlier searches found
                self.db.execute(
                    "INSERT OR IGNORE INTO known(ref, first_seen, first_job, kind, title, description, members, verified, checked) "
                    "SELECT ref, MIN(found), MIN(job_id), kind, title, description, members, verified, MAX(found) "
                    "FROM entities GROUP BY ref")
            self.db.execute("UPDATE jobs SET status='interrupted' WHERE status='running'")
            self.db.commit()
        self._dirty = 0.0

    def _commit(self, force: bool = False):
        now = time.monotonic()
        if force or now - self._dirty > 1.0:
            self.db.commit()
            self._dirty = now

    # ---- jobs
    def create_job(self, query: str, params: dict) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO jobs(created, query, params, status, stats) VALUES(?,?,?,?,?)",
                (time.time(), query, json.dumps(params), "running", "{}"))
            self.db.commit()
            return cur.lastrowid

    def update_job(self, job_id: int, status: str, stats: dict, finished: float | None = None):
        with self.lock:
            self.db.execute("UPDATE jobs SET status=?, stats=?, finished=? WHERE id=?",
                            (status, json.dumps(stats), finished, job_id))
            self._commit(force=True)

    def jobs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        return [self._job(r) for r in rows]

    def job(self, job_id: int) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(r) if r else None

    @staticmethod
    def _job(r) -> dict:
        d = dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        d["stats"] = json.loads(d["stats"] or "{}")
        return d

    def delete_job(self, job_id: int):
        with self.lock:
            for t in ("entities", "posts"):
                self.db.execute(f"DELETE FROM {t} WHERE job_id=?", (job_id,))
            self.db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            self.db.commit()

    # ---- entities
    def save_entity(self, job_id: int, e: dict):
        row = (job_id, e["ref"], e["kind"], e.get("title", ""), e.get("description", ""),
               e.get("members"), int(bool(e.get("verified"))), e.get("score", 0),
               int(bool(e.get("relevant"))), e.get("depth", 0),
               json.dumps(sorted(e.get("sources", []))), json.dumps(sorted(e.get("matched", []))),
               len(e.get("inbound", ())), e.get("post_hits", 0), e.get("found", time.time()),
               e.get("last_post"), e.get("online"), e.get("activity", "unknown"),
               int(bool(e.get("is_new"))), e.get("photo"), e.get("first_seen"), e.get("level", "exact"))
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO entities(%s) VALUES(%s)"
                            % (",".join(ENTITY_COLS), ",".join("?" * len(ENTITY_COLS))), row)
            self._commit()

    # ---- memory of every chat seen so far
    def known_all(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM known")]

    def known_get(self, ref: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM known WHERE ref=?", (ref,)).fetchone()
        return dict(r) if r else None

    def known_put(self, job_id: int, e: dict) -> tuple[bool, float]:
        """Remember a live chat. Returns (is_new_in_this_search, first_seen)."""
        now = time.time()
        with self.lock:
            r = self.db.execute("SELECT first_seen, first_job FROM known WHERE ref=?", (e["ref"],)).fetchone()
            first_seen, first_job = (r["first_seen"], r["first_job"]) if r else (now, job_id)
            self.db.execute(
                "INSERT OR REPLACE INTO known VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (e["ref"], first_seen, first_job, e["kind"], e.get("title", ""), e.get("description", ""),
                 e.get("members"), int(bool(e.get("verified"))), e.get("last_post"), e.get("online"),
                 e.get("photo"), now))
            self._commit()
        return first_job == job_id, first_seen

    def known_forget(self, ref: str):
        with self.lock:
            self.db.execute("DELETE FROM known WHERE ref=?", (ref,))
            self._commit()

    def entities(self, job_id: int, kinds: list[str] | None = None, relevant_only: bool = True,
                 text: str = "", min_members: int = 0, sort: str = "score",
                 new_only: bool = False, active_only: bool = False, exact_only: bool = False,
                 limit: int = 200, offset: int = 0) -> tuple[int, list[dict]]:
        where, args = ["job_id=?"], [job_id]
        if kinds:
            where.append("kind IN (%s)" % ",".join("?" * (len(kinds) + 1)))
            args += kinds + ["dead"]
        if relevant_only:
            where.append("relevant=1")
        if text:
            where.append("(title LIKE ? OR ref LIKE ? OR description LIKE ?)")
            args += [f"%{text}%"] * 3
        if min_members:
            where.append("members>=?")
            args.append(min_members)
        if new_only:
            where.append("is_new=1")
        if active_only:
            where.append("activity='active'")
        if exact_only:
            where.append("COALESCE(level,'exact') IN ('exact','posts')")
        w = " AND ".join(where)
        with self.lock:
            self.db.commit()
            total = self.db.execute(f"SELECT COUNT(*) FROM entities WHERE {w}", args).fetchone()[0]
            rows = self.db.execute(
                f"SELECT * FROM entities WHERE {w} ORDER BY {ENTITY_SORTS.get(sort, ENTITY_SORTS['score'])} "
                "LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["sources"] = json.loads(d["sources"] or "[]")
            d["matched"] = json.loads(d["matched"] or "[]")
            d["url"] = "https://t.me/" + d["ref"]
            out.append(d)
        return total, out

    def counts(self, job_id: int, kinds: list[str] | None = None) -> dict:
        where, args = "job_id=? AND relevant=1", [job_id]
        if kinds:
            where += " AND kind IN (%s)" % ",".join("?" * (len(kinds) + 1))
            args += kinds + ["dead"]
        with self.lock:
            r = self.db.execute(
                "SELECT COUNT(*), SUM(is_new=1), SUM(activity='active'), SUM(activity='dead'), "
                "SUM(COALESCE(level,'exact') IN ('exact','posts')) "
                f"FROM entities WHERE {where}", args).fetchone()
        return {"all": r[0] or 0, "new": r[1] or 0, "active": r[2] or 0, "dead": r[3] or 0, "exact": r[4] or 0}

    # ---- posts
    def save_post(self, job_id: int, p: dict, matched: list[str]):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO posts VALUES(?,?,?,?,?,?,?)",
                            (job_id, p["channel"], p["id"], p.get("date", ""), p.get("views"),
                             (p.get("text") or "")[:4000], json.dumps(matched)))
            self._commit()

    def posts(self, job_id: int, text: str = "", channel: str = "", sort: str = "date",
              limit: int = 200, offset: int = 0) -> tuple[int, list[dict]]:
        where, args = ["job_id=?"], [job_id]
        if text:
            where.append("text LIKE ?")
            args.append(f"%{text}%")
        if channel:
            where.append("channel=?")
            args.append(channel)
        w = " AND ".join(where)
        order = "views DESC" if sort == "views" else "date DESC"
        with self.lock:
            self.db.commit()
            total = self.db.execute(f"SELECT COUNT(*) FROM posts WHERE {w}", args).fetchone()[0]
            rows = self.db.execute(f"SELECT * FROM posts WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?",
                                   args + [limit, offset]).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["matched"] = json.loads(d["matched"] or "[]")
            d["url"] = f"https://t.me/{d['channel']}/{d['post_id']}"
            out.append(d)
        return total, out
