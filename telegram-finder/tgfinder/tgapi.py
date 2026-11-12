"""Optional Telegram account connection (Telethon).

Logging in with your own account unlocks Telegram's internal search, "similar
channels", linked discussion groups and searching inside public groups.
Everything here is read-only: the app never joins, posts or messages anyone.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time

try:
    from telethon import TelegramClient, errors, functions, types
    HAVE_TELETHON = True
except Exception:  # not installed
    HAVE_TELETHON = False


class TgError(Exception):
    pass


class Tg:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.cfg_path = os.path.join(data_dir, "telegram.json")
        self.session = os.path.join(data_dir, "telegram")
        self.client = None
        self.phone = None
        self.me = None
        self.paused_until = 0.0
        self.posts_search_ok = True
        self._loop = None
        self._lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._last_call = 0.0

    # ---- plumbing
    def config(self) -> dict:
        try:
            with open(self.cfg_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def save_config(self, api_id: int, api_hash: str):
        with open(self.cfg_path, "w") as f:
            json.dump({"api_id": int(api_id), "api_hash": api_hash.strip()}, f)
        os.chmod(self.cfg_path, 0o600)
        self._disconnect()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True, name="tg-loop").start()

    def _run(self, coro, timeout: float = 180):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _connect(self):
        if not HAVE_TELETHON:
            raise TgError("Telethon is not installed. Run: pip install telethon")
        cfg = self.config()
        if not cfg.get("api_id"):
            raise TgError("Telegram API id / hash are not set yet.")
        if self.client is None:
            self.client = TelegramClient(self.session, cfg["api_id"], cfg["api_hash"],
                                         flood_sleep_threshold=30)
        if not self.client.is_connected():
            await self.client.connect()
        return self.client

    def _disconnect(self):
        if self.client is not None:
            try:
                self._run(self.client.disconnect(), 20)
            except Exception:
                pass
        self.client, self.me = None, None

    # ---- login
    def status(self) -> dict:
        st = {"installed": HAVE_TELETHON, "configured": bool(self.config().get("api_id")),
              "authorized": False, "user": None}
        if not (st["installed"] and st["configured"]):
            return st
        try:
            async def go():
                c = await self._connect()
                if await c.is_user_authorized():
                    return await c.get_me()
            me = self._run(go(), 40)
            if me:
                self.me = me
                st["authorized"] = True
                st["user"] = " ".join(filter(None, [me.first_name, me.last_name])) or me.username
        except Exception as e:
            st["error"] = str(e)
        return st

    def send_code(self, phone: str):
        async def go():
            c = await self._connect()
            await c.send_code_request(phone)
        self.phone = phone
        self._wrap(go)

    def sign_in(self, code: str = "", password: str = "") -> str:
        """Returns 'ok' or 'password' (two-step verification password required)."""
        async def go():
            c = await self._connect()
            try:
                if password:
                    await c.sign_in(password=password)
                else:
                    await c.sign_in(self.phone, code)
            except errors.SessionPasswordNeededError:
                return "password"
            return "ok"
        return self._wrap(go)

    def logout(self):
        async def go():
            c = await self._connect()
            await c.log_out()
        try:
            self._wrap(go)
        finally:
            self.client, self.me = None, None

    def _wrap(self, fn):
        try:
            return self._run(fn())
        except TgError:
            raise
        except Exception as e:
            raise TgError(f"{type(e).__name__}: {e}") from e

    def ready(self) -> bool:
        return bool(self.me) and time.time() >= self.paused_until

    # ---- read-only discovery calls
    def _call(self, fn):
        """Run one API call, spaced out, converting flood waits into a pause."""
        if time.time() < self.paused_until:
            raise TgError("paused by Telegram rate limit")
        with self._call_lock:
            gap = 1.5 - (time.time() - self._last_call)
            if gap > 0:
                time.sleep(gap)
            try:
                return self._run(fn())
            except errors.FloodWaitError as e:
                self.paused_until = time.time() + e.seconds + 5
                raise TgError(f"Telegram asked to wait {e.seconds}s") from e
            except Exception as e:
                raise TgError(f"{type(e).__name__}: {e}") from e
            finally:
                self._last_call = time.time()

    @staticmethod
    def _refs(chats) -> list[str]:
        out = []
        for ch in chats or []:
            names = []
            if getattr(ch, "username", None):
                names.append(ch.username)
            for u in getattr(ch, "usernames", None) or []:
                if getattr(u, "active", True):
                    names.append(u.username)
            out += [n.lower() for n in names]
        return out

    def search(self, q: str) -> list[str]:
        """Telegram's own global chat search."""
        async def go():
            r = await self.client(functions.contacts.SearchRequest(q=q, limit=100))
            return self._refs(r.chats) + [u.username.lower() for u in r.users
                                          if getattr(u, "bot", False) and u.username]
        return self._call(go)

    def search_posts(self, q: str, limit: int = 100) -> tuple[list[str], list[dict]]:
        """Global search over public channel posts (needs a recent Telegram layer)."""
        async def go():
            r = await self.client(functions.channels.SearchPostsRequest(
                query=q, offset_rate=0, offset_peer=types.InputPeerEmpty(), offset_id=0, limit=limit))
            return self._refs(r.chats), self._posts(r.messages, {c.id: c for c in r.chats})
        try:
            return self._call(go)
        except TgError:
            self.posts_search_ok = False
            raise

    def search_my_chats(self, q: str, limit: int = 100) -> tuple[list[str], list[dict]]:
        """Messages matching q in chats the account already sees."""
        async def go():
            r = await self.client(functions.messages.SearchGlobalRequest(
                q=q, filter=types.InputMessagesFilterEmpty(), min_date=None, max_date=None,
                offset_rate=0, offset_peer=types.InputPeerEmpty(), offset_id=0, limit=limit))
            return self._refs(r.chats), self._posts(r.messages, {c.id: c for c in r.chats})
        return self._call(go)

    def similar(self, username: str) -> list[str]:
        async def go():
            ch = await self.client.get_input_entity(username)
            r = await self.client(functions.channels.GetChannelRecommendationsRequest(channel=ch))
            return self._refs(r.chats)
        return self._call(go)

    def full(self, username: str) -> dict:
        """About text, member count and linked discussion group / channel."""
        async def go():
            r = await self.client(functions.channels.GetFullChannelRequest(channel=username))
            return {"about": r.full_chat.about or "", "members": r.full_chat.participants_count,
                    "linked": [x for x in self._refs(r.chats) if x != username.lower()]}
        return self._call(go)

    def search_in(self, username: str, q: str, limit: int = 50) -> list[dict]:
        """Search messages inside one public group or channel."""
        async def go():
            msgs = await self.client.get_messages(username, search=q, limit=limit)
            return [{"channel": username.lower(), "id": m.id,
                     "date": m.date.isoformat() if m.date else "", "views": getattr(m, "views", None),
                     "text": m.message or ""} for m in msgs if m.message]
        return self._call(go)

    @staticmethod
    def _posts(messages, chats: dict) -> list[dict]:
        out = []
        for m in messages or []:
            peer = getattr(m, "peer_id", None)
            ch = chats.get(getattr(peer, "channel_id", None))
            name = getattr(ch, "username", None)
            if name and getattr(m, "message", None):
                out.append({"channel": name.lower(), "id": m.id,
                            "date": m.date.isoformat() if m.date else "",
                            "views": getattr(m, "views", None), "text": m.message})
        return out
