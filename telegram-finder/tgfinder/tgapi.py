"""Optional Telegram account connection (Telethon).

Logging in with your own account unlocks Telegram's internal search, "similar
channels", linked discussion groups and searching inside public groups.
Everything here is read-only: the app never joins, posts or messages anyone.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import io
import json
import os
import threading
import time

try:
    from telethon import TelegramClient, errors, functions, types
    HAVE_TELETHON = True
except Exception:  # not installed
    HAVE_TELETHON = False
try:
    import segno
except Exception:
    segno = None

APP_VERSION = "1.3"
# Where Telegram says it delivered the login code -> what to tell the user.
CODE_WHERE = {
    "SentCodeTypeApp": ("app", "Telegram sent the code as a chat message inside your Telegram app (not SMS). "
                               "Open Telegram on a device where you are already logged in and look for the chat "
                               "named “Telegram” (service notifications)."),
    "SentCodeTypeSms": ("sms", "Telegram sent the code by SMS to this number."),
    "SentCodeTypeSmsWord": ("sms", "Telegram sent a code word by SMS to this number."),
    "SentCodeTypeSmsPhrase": ("sms", "Telegram sent a code phrase by SMS to this number."),
    "SentCodeTypeFirebaseSms": ("sms", "Telegram sent the code by SMS to this number."),
    "SentCodeTypeCall": ("call", "Telegram is calling this number and will read out the code."),
    "SentCodeTypeFlashCall": ("call", "Telegram is placing a call to this number; the code is in the caller's number."),
    "SentCodeTypeMissedCall": ("call", "Telegram placed a missed call; the code is the last digits of the caller's number."),
    "SentCodeTypeEmailCode": ("email", "Telegram sent the code to the login e-mail address set on this account."),
    "SentCodeTypeFragmentSms": ("fragment", "The code was sent to Fragment (anonymous number); open fragment.com to read it."),
    "SentCodeTypeSetUpEmailRequired": ("email", "Telegram requires a login e-mail on this account before other apps can log in. "
                                                "Add one in Telegram: Settings → Privacy and Security → Login Email, then try again."),
}


class TgError(Exception):
    pass


FRIENDLY = {
    "ApiIdInvalidError": "The api_id / api_hash pair is not valid. Copy both again from my.telegram.org/apps.",
    "PhoneNumberInvalidError": "Telegram does not recognise this phone number. Use international format, e.g. +49 151 2345678.",
    "PhoneNumberBannedError": "This phone number is banned from Telegram.",
    "PhoneNumberFloodError": "Too many login attempts for this number. Wait a few hours before trying again.",
    "PhoneCodeInvalidError": "That code is not correct. Check it and try again.",
    "PhoneCodeExpiredError": "That code has expired. Press “Send code” to get a new one.",
    "PhoneCodeEmptyError": "Enter the code first.",
    "PasswordHashInvalidError": "The two-step password is not correct.",
    "SendCodeUnavailableError": "Telegram has no other way left to send the code right now. Wait a few minutes, or use QR login.",
    "PhonePasswordFloodError": "Too many wrong password attempts. Wait before trying again.",
}


class Tg:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.cfg_path = os.path.join(data_dir, "telegram.json")
        self.session = os.path.join(data_dir, "telegram")
        self.client = None
        self.phone = None
        self.me = None
        self.qr = {"state": "idle"}
        self._qr_run = 0
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
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()  # do not leave a stuck request running behind the next one
            raise

    async def _connect(self):
        if not HAVE_TELETHON:
            raise TgError("Telethon is not installed. Run: pip install telethon")
        cfg = self.config()
        if not cfg.get("api_id"):
            raise TgError("Telegram API id / hash are not set yet.")
        if self.client is None:
            self.client = TelegramClient(self.session, cfg["api_id"], cfg["api_hash"],
                                         flood_sleep_threshold=30, timeout=12, connection_retries=1,
                                         device_model="Telegram Finder", system_version="1.0",
                                         app_version=APP_VERSION, lang_code="en", system_lang_code="en")
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
              "authorized": False, "user": None, "qr_available": segno is not None}
        if not (st["installed"] and st["configured"]):
            return st
        try:
            async def go():
                c = await self._connect()
                if await c.is_user_authorized():
                    return await c.get_me()
            me = self._run(go(), 30)
            if me:
                self.me = me
                st["authorized"] = True
                st["user"] = " ".join(filter(None, [me.first_name, me.last_name])) or me.username
        except (concurrent.futures.TimeoutError, asyncio.TimeoutError, ConnectionError, OSError):
            st["error"] = ("Could not reach Telegram's servers. Check the internet connection; if Telegram is "
                           "restricted on this network, turn on a VPN and try again.")
        except Exception as e:
            st["error"] = str(e) or type(e).__name__
        return st

    def send_code(self, phone: str, sms: bool = False) -> dict:
        """Ask Telegram for a login code; returns where Telegram says it delivered it."""
        phone = "+" + "".join(ch for ch in phone if ch.isdigit())
        if len(phone) < 8:
            raise TgError("Enter the full phone number in international format, e.g. +49 151 2345678")

        async def go():
            c = await self._connect()
            return await c.send_code_request(phone, force_sms=sms)
        self.phone = phone
        sent = self._wrap(go, 45)
        where, text = CODE_WHERE.get(type(sent.type).__name__, ("other", "Telegram sent a login code."))
        nxt = type(sent.next_type).__name__ if getattr(sent, "next_type", None) else ""
        return {"where": where, "text": text, "phone": phone,
                "can_resend": bool(nxt), "next": {"CodeTypeSms": "SMS", "CodeTypeCall": "phone call",
                                                   "CodeTypeFlashCall": "phone call", "CodeTypeMissedCall": "missed call",
                                                   "CodeTypeFragmentSms": "Fragment"}.get(nxt, "")}

    # ---- QR login: no code needed, confirm from a phone that is already logged in
    def qr_start(self) -> dict:
        if segno is None:
            raise TgError("QR login needs the 'segno' package: pip install segno")
        self._qr_run += 1
        run = self._qr_run

        async def go():
            c = await self._connect()
            qr = await c.qr_login()
            self._set_qr(qr.url)
            asyncio.ensure_future(self._qr_wait(qr, run))
        self._wrap(go, 45)
        return self.qr_view()

    def _set_qr(self, url: str):
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=6, border=3, xmldecl=False, svgns=True,
                                         nl=False, dark="#000", light="#fff")
        self.qr = {"state": "waiting", "svg": buf.getvalue().decode()}

    async def _qr_wait(self, qr, run: int):
        deadline = time.time() + 300
        while run == self._qr_run and time.time() < deadline:
            try:
                await qr.wait(timeout=max(5, (qr.expires - datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
                self.me = await self.client.get_me()
                self.qr = {"state": "done"}
                return
            except asyncio.TimeoutError:
                try:
                    await qr.recreate()
                    self._set_qr(qr.url)
                except Exception as e:
                    self.qr = {"state": "error", "error": f"{type(e).__name__}: {e}"}
                    return
            except errors.SessionPasswordNeededError:
                self.qr = {"state": "password"}
                return
            except Exception as e:
                self.qr = {"state": "error", "error": f"{type(e).__name__}: {e}"}
                return
        if run == self._qr_run:
            self.qr = {"state": "expired"}

    def qr_view(self) -> dict:
        return dict(self.qr)

    def sign_in(self, code: str = "", password: str = "") -> str:
        """Returns 'ok' or 'password' (two-step verification password required)."""
        async def go():
            c = await self._connect()
            try:
                if password:
                    await c.sign_in(password=password)
                else:
                    if not self.phone:
                        raise TgError("Press “Send code” first.")
                    await c.sign_in(self.phone, "".join(ch for ch in code if ch.isalnum()))
            except errors.SessionPasswordNeededError:
                return "password"
            self.me = await c.get_me()
            self.qr = {"state": "idle"}
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
            self.qr = {"state": "idle"}
            self._qr_run += 1

    def _wrap(self, fn, timeout: float = 120):
        try:
            return self._run(fn(), timeout)
        except TgError:
            raise
        except (concurrent.futures.TimeoutError, asyncio.TimeoutError, ConnectionError, OSError) as e:
            raise TgError("Could not reach Telegram's servers. Check the internet connection; if Telegram is "
                          "restricted on this network, turn on a VPN and try again.") from e
        except Exception as e:
            raise TgError(FRIENDLY.get(type(e).__name__, f"{type(e).__name__}: {e}")) from e

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

    def last_date(self, username: str) -> str:
        """Date of the newest message in a public chat ('' if none)."""
        async def go():
            msgs = await self.client.get_messages(username, limit=1)
            return msgs[0].date.isoformat() if msgs and msgs[0].date else ""
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
