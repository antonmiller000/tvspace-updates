# Telegram Finder

A local app that hunts for Telegram **channels, groups and posts** on any topic —
including ones that Telegram's built-in search never shows. You type what you
want, choose what to look for (channels / groups / posts with the text / bots),
choose how thorough to be, and let it run. Results are saved, filterable and
exportable to CSV / JSON.

Results appear within a second or two and keep filling in while the search runs.
Every chat is checked live and marked:

- **New** — first time any of your searches has found it; otherwise "seen before".
  Chats found earlier are remembered, so a repeat search shows them instantly.
- **Active / Quiet / Inactive / Gone** — from the date of the newest post (channels),
  people online (groups), or a link that no longer works. Dead links are dropped.

## Start

```
python3 run.py
```

Needs Python 3.9+. Nothing else to install for the basic mode. The app opens at
http://127.0.0.1:8765 and is reachable only from your own computer.

## How it finds things

1. **Web search engines** (DuckDuckGo, Bing, Google, Yandex, Brave, Mojeek, Startpage)
   are queried for Telegram links about your keywords.
2. **Telegram directories** (tgramsearch, Combot, TGStat, Telemetr and others).
3. **Username guessing** — hundreds of likely names built from your keywords
   (`topic_chat`, `topicnews`, transliterated Cyrillic…) are checked directly on t.me.
4. **Snowballing** — the important part. Every relevant channel is read: links,
   @mentions, forwards and invite links in its posts lead to new chats. Each new chat
   is checked for your keywords in its name, description *and inside its own posts*,
   so a channel that talks about your topic is found even if its name says nothing.
   Relevant ones are read in turn, as many hops deep as you allow.
5. **Your Telegram account (optional)** — adds Telegram's internal search, global post
   search, "similar channels", linked discussion groups, and searching inside public
   groups (which have no web preview). Read-only: the app never joins, posts or messages.

Some search engines block automated requests; such a source is skipped and the
rest carry on (see the activity log of a search).

### Thoroughness

| Preset | Link hops | Time limit | Chats checked (max) |
|---|---|---|---|
| Quick | 1 | 10 min | 1,500 |
| Deep | 2 | 1.5 h | 8,000 |
| Exhaustive | 4 | 12 h | 40,000 |

All of these can be changed under **More options**, where you can also add
synonyms / other languages and chats you already know as starting points.
A search can be stopped at any time; what was found so far is kept.

## Connecting a Telegram account (optional)

```
pip install telethon
```

Restart the app, then in the **Telegram account** box: paste the `api_id` /
`api_hash` you get for free at https://my.telegram.org/apps, enter your phone
number and the login code. Keys and the session are stored only in `data/` on
this computer — keep that folder private (it is git-ignored).

## What it cannot do

Private chats are visible only if someone posted their invite link publicly
(those are listed as "private invite" with title and member count). Personal
accounts are never collected.

## Tests

```
python3 -m unittest discover -s tests
```

## Android app (APK)

`android/` wraps the same engine in an Android app (phones, tablets and Android TV,
Android 7.0+). The Python engine runs inside the app; a notification keeps long
searches alive in the background and has a **Quit** button. Telegram links open in
the Telegram app; exports are saved to Downloads.

Build (needs the Android SDK, JDK 17+, and `python3.11` on PATH):

```
cd android
echo "sdk.dir=/path/to/android-sdk" > local.properties
gradle :app:assembleRelease -PksFile=/path/key.jks -PksPass=... -PksAlias=...
```

Without the `-Pks…` options the APK is signed with the debug key. Updates install
over an older version only when signed with the same key.
