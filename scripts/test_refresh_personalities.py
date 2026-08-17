import unittest
import xml.etree.ElementTree as ET

from scripts.refresh_personalities import context_allowed, discovery_queries, rss_confirms_guest


class CommonNameContextTests(unittest.TestCase):
    def test_requires_identifying_keyword_for_common_names(self):
        person = {
            "potentially_common_name": True,
            "required_context_keywords": ["Google", "machine learning"],
        }
        self.assertTrue(context_allowed(
            {"title": "Jeff Dean interview", "description": "A conversation about Google AI."},
            person,
        ))
        self.assertFalse(context_allowed(
            {"title": "Jeff Dean joins us", "description": "Portland horror and VHS."},
            person,
        ))

    def test_does_not_filter_unmarked_names(self):
        self.assertTrue(context_allowed(
            {"title": "Any episode", "description": ""},
            {"required_context_keywords": []},
        ))


class ItunesGuestFallbackTests(unittest.TestCase):
    def test_itunes_guest_query_searches_all_text_and_requires_rss_confirmation(self):
        person = {
            "name": "Sean Parent",
            "queries": ["Sean Parent"],
            "itunes_guest_queries": ["Sean Parent Adobe"],
        }
        self.assertEqual(
            discovery_queries("itunes", person, "title"),
            [
                ("Sean Parent", "title", False),
                ("Sean Parent Adobe", "all", True),
            ],
        )
        self.assertEqual(
            discovery_queries("podcastindex", person, "all"),
            [("Sean Parent", "all", False)],
        )

    def test_exact_guest_tag_confirms_episode_with_opaque_title(self):
        root = ET.fromstring(
            """\
            <rss xmlns:podcast="https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md">
              <channel>
                <item>
                  <guid>cppchat-42</guid>
                  <title>I'm Surprised You Brought up Rotate</title>
                  <enclosure url="https://example.com/rotate.mp3" />
                  <description>Sean Parent talks about C++.</description>
                  <podcast:person role="guest">Sean Parent</podcast:person>
                </item>
              </channel>
            </rss>
            """
        )
        ep = {
            "guid": "cppchat-42",
            "title": "I'm Surprised You Brought up Rotate",
            "audio_url": "https://example.com/rotate.mp3",
        }
        self.assertTrue(rss_confirms_guest(root, ep, {"name": "Sean Parent", "aliases": []}))

    def test_mention_or_non_guest_person_tag_is_rejected(self):
        root = ET.fromstring(
            """\
            <rss xmlns:podcast="https://podcastindex.org/namespace/1.0">
              <channel>
                <item>
                  <guid>mention-only</guid>
                  <title>Podcasting and Advocating</title>
                  <description>We discuss an earlier Sean Parent episode.</description>
                  <podcast:person role="host">Sean Parent</podcast:person>
                </item>
              </channel>
            </rss>
            """
        )
        ep = {"guid": "mention-only", "title": "Podcasting and Advocating"}
        self.assertFalse(rss_confirms_guest(root, ep, {"name": "Sean Parent", "aliases": []}))


if __name__ == "__main__":
    unittest.main()
