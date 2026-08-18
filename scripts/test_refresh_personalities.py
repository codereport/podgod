import unittest
import xml.etree.ElementTree as ET

from scripts.refresh_personalities import (
    context_allowed,
    discovery_queries,
    hosted_podcast_id,
    name_matches,
    parse_hosted_podcast_feed,
    public_hosted_podcasts,
    rss_confirms_guest,
)


class PersonalityAliasTests(unittest.TestCase):
    def test_former_name_and_surname_match_without_changing_display_name(self):
        person = {
            "name": "Conor Shakory",
            "aliases": ["Conor Hoekstra", "Hoekstra"],
            "queries": ["Conor Shakory", "Conor Hoekstra"],
        }

        self.assertEqual(person["name"], "Conor Shakory")
        self.assertTrue(name_matches(
            {"title": "a conversation with conor hoekstra"}, person, "title"
        ))
        self.assertTrue(name_matches(
            {"title": "hoekstra on functional programming"}, person, "title"
        ))
        self.assertEqual(
            discovery_queries("podcastindex", person, "all"),
            [
                ("Conor Shakory", "all", False),
                ("Conor Hoekstra", "all", False),
            ],
        )


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


class HostedPodcastTests(unittest.TestCase):
    def setUp(self):
        self.person = {
            "hosted_podcasts": [
                {
                    "id": "stavvys-world",
                    "title": "Stavvy's World",
                    "title_aliases": ["Stavvy’s World"],
                    "feed_urls": ["https://example.com/stavvy/feed.xml"],
                },
                {
                    "id": "second-show",
                    "title": "A Second Show",
                    "feed_urls": ["https://example.com/second/"],
                },
            ]
        }

    def test_public_metadata_omits_matching_details(self):
        self.assertEqual(
            public_hosted_podcasts(self.person),
            [
                {"id": "stavvys-world", "title": "Stavvy's World"},
                {"id": "second-show", "title": "A Second Show"},
            ],
        )

    def test_matches_exact_feed_url_ignoring_trailing_slash(self):
        episode = {
            "podcast_title": "A renamed show",
            "feed_url": "https://example.com/second",
        }
        self.assertEqual(hosted_podcast_id(episode, self.person), "second-show")

    def test_falls_back_to_exact_title_or_alias(self):
        episode = {"podcast_title": "Stavvy’s World", "feed_url": None}
        self.assertEqual(hosted_podcast_id(episode, self.person), "stavvys-world")

    def test_does_not_match_a_partial_title(self):
        episode = {"podcast_title": "Stavvy's World Highlights", "feed_url": None}
        self.assertIsNone(hosted_podcast_id(episode, self.person))

    def test_confirmed_host_feed_imports_every_episode_for_later_classification(self):
        root = ET.fromstring(
            """\
            <rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
              <channel>
                <title>ADSP</title>
                <language>en-US</language>
                <itunes:image href="https://example.com/show.jpg" />
                <item>
                  <guid>conor-ben</guid>
                  <title>Conor and Ben</title>
                  <description>Conor and Ben chat about C++.</description>
                  <pubDate>Fri, 15 Aug 2026 12:00:00 +0000</pubDate>
                  <itunes:duration>42:30</itunes:duration>
                  <enclosure url="https://example.com/conor.mp3" type="audio/mpeg" />
                </item>
                <item>
                  <guid>bryce-ben</guid>
                  <title>Bryce and Ben</title>
                  <description>Bryce and Ben chat about C++.</description>
                  <pubDate>Fri, 08 Aug 2026 12:00:00 +0000</pubDate>
                  <itunes:duration>39:00</itunes:duration>
                  <enclosure url="https://example.com/bryce.mp3" type="audio/mpeg" />
                </item>
              </channel>
            </rss>
            """
        )

        episodes = parse_hosted_podcast_feed(
            root,
            {"id": "itunes-123", "title": "ADSP"},
            "https://example.com/feed.xml",
            0,
            "2026-08-17T00:00:00Z",
            600,
        )

        self.assertEqual(len(episodes), 2)
        self.assertEqual(
            {episode["hosted_podcast_id"] for episode in episodes},
            {"itunes-123"},
        )
        self.assertIn("Conor and Ben", episodes[0]["description"])
        self.assertIn("Bryce and Ben", episodes[1]["description"])


if __name__ == "__main__":
    unittest.main()
