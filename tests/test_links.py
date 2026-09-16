"""Link screening + SSRF guard tests. The resolver is tested with a fake HEAD so no real network is used."""
import unittest

import links
from links import LinkError


class Classify(unittest.TestCase):
    def test_download_host_blocks(self):
        self.assertEqual(links.classify("https://mediafire.com/file/x")[0], "block")
        self.assertEqual(links.classify("https://gofile.io/d/abc")[0], "block")

    def test_executable_download_from_unrelated_domain_blocks(self):
        self.assertEqual(links.classify("https://example.ru/setup.exe")[0], "block")

    def test_own_repo_release_asset_ok(self):
        self.assertIsNone(links.classify("https://github.com/owner/repo/releases/download/v1/tool.zip", "owner/repo"))

    def test_shortener_warns(self):
        self.assertEqual(links.classify("https://bit.ly/abc")[0], "warn")

    def test_non_web_scheme_blocks(self):
        self.assertEqual(links.classify("javascript:alert(1)")[0], "block")
        self.assertEqual(links.classify("file:///etc/passwd")[0], "block")

    def test_raw_ip_blocks(self):
        self.assertEqual(links.classify("http://169.254.169.254/latest/meta-data")[0], "block")

    def test_ordinary_github_link_ok(self):
        self.assertIsNone(links.classify("https://github.com/pandas-dev/pandas"))


class Phrases(unittest.TestCase):
    def test_disable_defender_flagged(self):
        self.assertIn("instructs to disable security protection", links.phrases("First, disable Windows Defender before running."))

    def test_archive_password_flagged(self):
        self.assertTrue(links.phrases("Download the archive. Password: 12345"))

    def test_curl_pipe_shell_flagged(self):
        self.assertTrue(links.phrases("Install: curl https://x.sh | sudo bash"))

    def test_ordinary_readme_clean(self):
        self.assertEqual(links.phrases("Run `pip install pandas` then `python app.py`."), [])


class ScreenReadme(unittest.TestCase):
    def test_block_and_warn_collected(self):
        text = "Get it from https://mediafire.com/x . Chat: https://t.me/group . Password: 9999 for the zip."
        r = links.screen_readme(text, "owner/repo")
        self.assertTrue(r["block"])
        self.assertTrue(any("mediafire" in b for b in r["block"]))


class SSRFGuard(unittest.TestCase):
    def test_refuses_loopback(self):
        with self.assertRaises(LinkError):
            links.check_target("http://127.0.0.1/")

    def test_refuses_localhost_name(self):
        with self.assertRaises(LinkError):
            links.check_target("http://localhost:8080/")

    def test_refuses_metadata_ip(self):
        with self.assertRaises(LinkError):
            links.check_target("http://169.254.169.254/")

    def test_refuses_nonstandard_port(self):
        with self.assertRaises(LinkError):
            links.check_target("https://example.com:22/")

    def test_refuses_bad_scheme(self):
        with self.assertRaises(LinkError):
            links.check_target("gopher://example.com/")

    def test_resolve_revalidates_each_hop(self):
        # a shortener that 302s to a private address must be refused at the redirect target, never followed to it
        hops = {"https://sho.rt/x": (302, "http://127.0.0.1/secret")}

        def fake_head(scheme, host, port, ip, path):
            url = f"{scheme}://{host}{path}"
            return hops.get(url, (200, None))
        with self.assertRaises(LinkError):
            links.safe_resolve("https://sho.rt/x", head=fake_head)

    def test_resolve_allows_public_destination(self):
        def fake_head(scheme, host, port, ip, path):
            if host == "sho.rt":
                return (301, "https://github.com/owner/repo")
            return (200, None)

        def fake_check(url):  # stub DNS so the test is hermetic; the real check_target is tested above
            from urllib.parse import urlsplit
            s = urlsplit(url)
            if s.scheme not in ("http", "https"):
                raise LinkError("scheme")
            return s.scheme, s.hostname, 443, "93.184.216.34"
        self.assertEqual(links.safe_resolve("https://sho.rt/x", head=fake_head, check=fake_check), "https://github.com/owner/repo")


if __name__ == "__main__":
    unittest.main()
