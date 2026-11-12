import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tgfinder import keywords, tme, websearch

INFO = '''<div class="tgme_page_title" dir="auto"><span dir="auto">Py Group</span></div>
<div class="tgme_page_extra">9 878 members, 1 419 online</div>
<div class="tgme_page_description" dir="auto">Chat. See <a href="https://t.me/other_chat">@other_chat</a></div>
<a class="tgme_action_button_new shine" href="tg://resolve?domain=pygroup">View in Telegram</a>'''
POSTS = '''<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="News/12">
<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/source_chan/5">Src</a>
<div class="tgme_widget_message_text js-message_text" dir="auto">Hello <b>world</b> join <a href="https://t.me/+AbCdEfGh1234">here</a> and @friend_chan</div>
<div class="tgme_widget_message_footer"><span class="tgme_widget_message_views">1.2K</span><time datetime="2026-01-02T03:04:05+00:00"></time></div></div></div>
<a class="tme_messages_more" data-before="12"></a>'''


class T(unittest.TestCase):
    def test_norm_ref(self):
        self.assertEqual(tme.norm_ref("https://t.me/s/Durov?q=x"), "durov")
        self.assertEqual(tme.norm_ref("@Some_Chat"), "some_chat")
        self.assertEqual(tme.norm_ref("t.me/joinchat/AAAAAEQbPsLl"), "+AAAAAEQbPsLl")
        self.assertIsNone(tme.norm_ref("https://t.me/share/url?x"))
        self.assertIsNone(tme.norm_ref("abc"))

    def test_extract(self):
        refs = tme.extract_refs("x https%3A%2F%2Ft.me%2Fabcde1 and tg://resolve?domain=Qwerty and mail@example.com @real_one")
        self.assertEqual(refs, {"abcde1", "qwerty", "real_one"})

    def test_counts(self):
        self.assertEqual(tme.parse_count("9 137 542 subscribers"), 9137542)
        self.assertEqual(tme.parse_count("9.14M"), 9140000)
        self.assertEqual(tme.parse_count("1.2K"), 1200)

    def test_info(self):
        i = tme.parse_info(INFO)
        self.assertEqual((i["kind"], i["title"], i["members"]), ("group", "Py Group", 9878))
        self.assertIn("other_chat", i["refs"])
        self.assertEqual(i["online"], 1419)
        self.assertEqual(tme.parse_info("<html></html>")["kind"], "none")

    def test_posts(self):
        r = tme.parse_posts(POSTS)
        p = r["posts"][0]
        self.assertEqual((p["channel"], p["id"], p["views"], r["before"]), ("news", 12, 1200, 12))
        self.assertEqual(p["refs"], {"source_chan", "+AbCdEfGh1234", "friend_chan"})
        self.assertIn("Hello world", p["text"])

    def test_keywords(self):
        terms = keywords.parse_terms("Electric Cars, новости Киева", "ev\n")
        self.assertEqual(terms, ["electric cars", "новости киева", "ev"])
        m = keywords.Matcher(terms)
        self.assertEqual(m.hits("Best cars: ELECTRIC only"), ["electric cars"])
        self.assertEqual(m.username_hits("the_electriccars_hub"), ["electric cars"])
        self.assertEqual(m.username_hits("novostikieva24"), ["новости киева"])
        g = keywords.username_guesses(terms)
        self.assertIn("electriccars", g)
        self.assertIn("novosti_kieva_chat", g)

    def test_bing_redirect(self):
        import base64
        tok = base64.urlsafe_b64encode(b"https://t.me/hidden_chan").decode().rstrip("=")
        page = websearch._decode_redirects(f'<a href="https://www.bing.com/ck/a?x=1&amp;u=a1{tok}&amp;ntb=1">')
        self.assertIn("hidden_chan", tme.extract_refs(page))


class Memory(unittest.TestCase):
    def test_new_then_known_and_activity(self):
        import datetime, tempfile
        from tgfinder.engine import activity_of
        from tgfinder.store import Store
        st = Store(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
        e = {"ref": "abcde", "kind": "channel", "title": "T"}
        self.assertTrue(st.known_put(1, e)[0])     # first search: new
        self.assertTrue(st.known_put(1, e)[0])     # still the same search
        self.assertFalse(st.known_put(2, e)[0])    # later search: already known
        now = datetime.datetime.now(datetime.timezone.utc)
        iso = lambda d: (now - datetime.timedelta(days=d)).isoformat()
        self.assertEqual(activity_of({"last_post": iso(3)}), "active")
        self.assertEqual(activity_of({"last_post": iso(90)}), "quiet")
        self.assertEqual(activity_of({"last_post": iso(900)}), "inactive")
        self.assertEqual(activity_of({"online": 12}), "active")
        self.assertEqual(activity_of({"kind": "dead", "last_post": iso(1)}), "dead")
        self.assertEqual(activity_of({}), "unknown")


if __name__ == "__main__":
    unittest.main()
