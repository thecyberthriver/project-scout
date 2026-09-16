"""Tests for the extra screening engines: YARA byte-signatures (real), and the ClamAV / OSV parsers (fixtures)."""
import os
import tempfile
import unittest

import scan


class Yara(unittest.TestCase):
    def setUp(self):
        if not scan.yara_available():
            self.skipTest("yara-python not installed")
        self.dir = tempfile.mkdtemp()

    def write(self, name, data: bytes):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_catches_malicious_files(self):
        self.write("grabber.py", b'requests.post("https://discord.com/api/webhooks/123456789012345678/'
                                  + b"A" * 60 + b'", json={})')
        self.write("wallet.txt", b"target ext nkbihfbeogaeaoehlefnkodbefgpgknn")
        hits = scan.run_yara(self.dir)
        rules = {h.split("@")[0] for h in hits}
        self.assertIn("TLDP_Discord_Token_Grabber", rules)
        self.assertIn("TLDP_Crypto_Wallet_Theft", rules)

    def test_benign_files_clean(self):
        self.write("app.py", b'import requests\nrequests.get("https://api.example.com/price")')
        self.write("README.md", b"# Project\nRun pip install pandas. It uses Chrome for a demo.")
        self.assertEqual(scan.run_yara(self.dir), [])

    def test_embedded_executable_flagged(self):
        # a fake PE marker committed in a repo
        self.write("setup.dat", b"MZ\x90\x00" + b"PE\x00\x00" + b"This program cannot be run in DOS mode")
        rules = {h.split("@")[0] for h in scan.run_yara(self.dir)}
        self.assertIn("TLDP_Embedded_Windows_Executable", rules)


class OsvParser(unittest.TestCase):
    def test_malicious_advisory_blocks_vulns_counted(self):
        data = {"results": [{"packages": [
            {"package": {"name": "evil-pkg"}, "vulnerabilities": [{"id": "MAL-2024-1234", "aliases": []}]},
            {"package": {"name": "lodash"}, "vulnerabilities": [{"id": "GHSA-xxxx", "aliases": ["CVE-2021-1"]},
                                                                {"id": "GHSA-yyyy"}]},
        ]}]}
        malicious, vulns = scan.parse_osv(data)
        self.assertEqual(malicious, ["evil-pkg:MAL-2024-1234"])
        self.assertEqual(vulns, 2)

    def test_summary_marked_malicious(self):
        data = {"results": [{"packages": [{"package": {"name": "p"}, "vulnerabilities": [
            {"id": "GHSA-zzzz", "summary": "Malicious code in p"}]}]}]}
        malicious, vulns = scan.parse_osv(data)
        self.assertEqual(malicious, ["p:GHSA-zzzz"])
        self.assertEqual(vulns, 0)

    def test_empty(self):
        self.assertEqual(scan.parse_osv({}), ([], 0))


class ClamavParser(unittest.TestCase):
    def test_parses_found_lines(self):
        out = ("/tmp/x/repo/a.py: OK\n"
               "/tmp/x/repo/bad.exe: Win.Trojan.Agent-12345 FOUND\n"
               "/tmp/x/repo/sub/drop.bin: Unix.Malware.Generic FOUND\n")
        hits = scan.parse_clamav(out, "/tmp/x/repo")
        rules = {h.split("@")[0] for h in hits}
        self.assertIn("Win.Trojan.Agent-12345", rules)
        self.assertIn("Unix.Malware.Generic", rules)
        self.assertEqual(len(hits), 2)

    def test_clean_output(self):
        self.assertEqual(scan.parse_clamav("/tmp/x/a.py: OK\n", "/tmp/x"), [])


if __name__ == "__main__":
    unittest.main()
