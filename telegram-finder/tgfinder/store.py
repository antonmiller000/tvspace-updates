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
"""

ENTITY_SORTS = {
    "score": "relevant DESC, score DESC, members DESC",
    "members": "members DESC",
    "title": "title COLLATE NOCASE ASC",
    "found": "found DESC",
    "hits": "post_hits DESC, score DESC",
}


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
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
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, e["ref"], e["kind"], e.get("title", ""), e.get("description", ""),
                 e.get("members"), int(bool(e.get("verified"))), e.get("score", 0),
                 int(bool(e.get("relevant"))), e.get("depth", 0),
                 json.dumps(sorted(e.get("sources", []))), json.dumps(sorted(e.get("matched", []))),
                 len(e.get("inbound", ())), e.get("post_hits", 0), e.get("found", time.time())))
            self._commit()

    def entities(self, job_id: int, kinds: list[str] | None = None, relevant_only: bool = True,
                 text: str = "", min_members: int = 0, sort: str = "score",
                 limit: int = 200, offset: int = 0) -> tuple[int, list[dict]]:
        where, args = ["job_id=?"], [job_id]
        if kinds:
            where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
            args += kinds
        if relevant_only:
            where.append("relevant=1")
        if text:
            where.append("(title LIKE ? OR ref LIKE ? OR description LIKE ?)")
            args += [f"%{text}%"] * 3
        if min_members:
            where.append("members>=?")
            args.append(min_members)
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
