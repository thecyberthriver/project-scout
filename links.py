#!/usr/bin/env python3
"""
links.py — README link and install-instruction screening for third-party repos. stdlib only.

Treats README text as DATA (never as instructions). Finds links and risky phrases, classifies them, and — only for
URL shorteners — resolves the redirect chain with an SSRF-guarded HEAD request that never downloads a body.

  extract_links(text)              -> [url, ...]
  classify(url, full_name)          -> (severity, reason) | None       severity: "block" | "warn"
  phrases(text)                     -> [reason, ...]                   dangerous install instructions
  screen_readme(text, full_name)    -> {"checked": n, "block": [...], "warn": [...]}
  safe_resolve(url)                 -> final https/http URL or raises LinkError (private/loopback/metadata refused)

Heuristics: they can miss malicious links and flag legitimate ones. A pass is not a safety or legality judgement.
"""
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit, urljoin

MAX_HOPS, TIMEOUT, MAX_HEADER_BYTES = 5, 6, 8192
SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "rebrand.ly", "t.co", "goo.gl", "is.gd", "shorturl.at", "rb.gy",
              "tiny.cc", "ow.ly", "buff.ly", "s.id", "v.gd", "clck.ru", "urlz.fr", "shorte.st", "adf.ly", "linkvertise.com"}
DOWNLOAD_HOSTS = {"mediafire.com", "mega.nz", "mega.io", "anonfiles.com", "gofile.io", "sendspace.com", "zippyshare.com",
                  "filebin.net", "transfer.sh", "pixeldrain.com", "bayfiles.com", "anonfile.com", "krakenfiles.com",
                  "dropbox.com", "drive.google.com", "1fichier.com", "uploadhaven.com", "workupload.com", "files.fm",
                  "dosya.co", "ufile.io", "easyupload.io", "catbox.moe", "cdn.discordapp.com", "media.discordapp.net"}
CHAT_HOSTS = {"t.me", "telegram.me", "discord.gg", "discord.com", "wa.me"}
EXEC_EXT = re.compile(r"\.(exe|msi|dmg|pkg|apk|scr|bat|cmd|ps1|vbs|vbe|jse|hta|jar|zip|rar|7z|iso|img|lnk|dll|com)(\?|#|$)", re.I)
PHRASES = [
    (re.compile(r"(?i)(disable|turn off|switch off)\s+(your\s+)?(windows\s+)?(defender|antivirus|anti-virus|real[- ]time protection|smartscreen|firewall)"),
     "instructs to disable security protection"),
    (re.compile(r"(?i)add\s+(an\s+)?exclusion|exclude\s+(the\s+)?(folder|file)\s+(from|in)\s+(defender|antivirus)"), "instructs to add an antivirus exclusion"),
    (re.compile(r"(?i)(archive|zip|rar|7z)?\s*(password|pass(code)?)\s*(is|:)\s*\S{3,}"), "password-protected download"),
    (re.compile(r"(?i)\b(password|pass)\b[^\n]{0,40}\.(zip|rar|7z)\b|\.(zip|rar|7z)\b[^\n]{0,40}\b(password|pass)\b"), "password near an archive"),
    (re.compile(r"(?i)\b(cracked|nulled|keygen|activator|license key generator|pre-activated|unlocked version)\b"), "cracked / pirated software wording"),
    (re.compile(r"(?i)run\s+as\s+administrator[^\n]{0,80}(download|\.exe|installer)|(download|\.exe|installer)[^\n]{0,80}run\s+as\s+administrator"),
     "download + run as administrator instruction"),
    (re.compile(r"(?i)\b(iex|invoke-expression)\b[^\n]{0,120}(downloadstring|invoke-webrequest|iwr)\b"), "PowerShell download-and-execute one-liner"),
    (re.compile(r"(curl|wget)\s[^\n|]{0,160}\|\s*(sudo\s+)?(sh|bash|zsh|python3?|perl)\b"), "curl-pipe-shell install"),
    (re.compile(r"(?i)\b(download now|free download|direct download|mirror link)\b"), "download-bait wording"),
]
URL_RE = re.compile(r"""(?:\]\(|href=["']|src=["']|\b)(?P<u>[a-zA-Z][a-zA-Z0-9+.-]{1,20}://[^\s<>"'()\]]{1,600})""")


class LinkError(Exception):
    pass


def extract_links(text: str) -> list[str]:
    out, seen = [], set()
    for m in URL_RE.finditer(text or ""):
        u = m.group("u").rstrip(".,;:!?*")
        if u not in seen:
            seen.add(u); out.append(u)
    return out[:300]


def _host(u: str) -> str:
    try:
        return (urlsplit(u).hostname or "").lower()
    except ValueError:
        return ""


def _base_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify(url: str, full_name: str = "") -> tuple[str, str] | None:
    """One link -> (severity, reason) or None when it looks ordinary."""
    s = urlsplit(url)
    scheme, host = (s.scheme or "").lower(), (s.hostname or "").lower()
    if scheme not in ("http", "https"):
        return ("block", f"non-web link scheme {scheme}:")
    if not host:
        return ("warn", "link without a host")
    try:
        ip = ipaddress.ip_address(host)
        return ("block", "link to a raw IP address" + (" (private)" if not ip.is_global else ""))
    except ValueError:
        pass
    base = _base_domain(host)
    owner = (full_name.split("/") + [""])[0].lower()
    own_repo = host in ("github.com", "www.github.com") and s.path.lower().startswith(f"/{owner}/") if owner else False
    if base in SHORTENERS or host in SHORTENERS:
        return ("warn", f"URL shortener {host} (destination hidden)")
    if base in DOWNLOAD_HOSTS or host in DOWNLOAD_HOSTS:
        return ("block", f"file-sharing host {host}")
    if EXEC_EXT.search(s.path) and not own_repo and host not in ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"):
        return ("block", f"executable/archive download from {host}")
    if EXEC_EXT.search(s.path) and host == "github.com" and not own_repo:
        return ("warn", "executable/archive download from another GitHub repo")
    if base in CHAT_HOSTS or host in CHAT_HOSTS:
        return ("warn", f"chat invite link {host}")
    if s.username or s.password:
        return ("block", "link embeds credentials")
    return None


def phrases(text: str) -> list[str]:
    return [why for rx, why in PHRASES if rx.search(text or "")]


def screen_readme(text: str, full_name: str = "", resolve: bool = False) -> dict:
    """Classify every link + dangerous phrases. resolve=True follows shorteners with the SSRF-guarded resolver."""
    block, warn = [], []
    links = extract_links(text)
    for u in links:
        c = classify(u, full_name)
        if c and resolve and c[1].startswith("URL shortener"):
            try:
                final = safe_resolve(u)
                c2 = classify(final, full_name)
                c = ("block", f"shortener resolves to: {c2[1]}") if c2 and c2[0] == "block" else ("warn", c[1])
            except LinkError as e:
                c = ("block", f"shortener refused: {e}")
        if c:
            (block if c[0] == "block" else warn).append(c[1])
    block += [p for p in phrases(text) if p not in ("download-bait wording",)]
    if "download-bait wording" in phrases(text):
        warn.append("download-bait wording")
    return {"checked": len(links), "block": sorted(set(block)), "warn": sorted(set(warn))}


# ---- SSRF-guarded resolver ----------------------------------------------------------------------------------------
def _refuse_ip(ip: ipaddress._BaseAddress) -> str | None:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "private/loopback/link-local address"
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return "carrier-grade NAT address"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _refuse_ip(ip.ipv4_mapped)
        if ip in ipaddress.ip_network("fc00::/7") or ip in ipaddress.ip_network("fe80::/10"):
            return "private IPv6 address"
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return "cloud metadata address"
    return None


def check_target(url: str) -> tuple[str, str, int, str]:
    """Validate scheme/host/port and resolve DNS; refuse anything not publicly routable. Returns (scheme, host, port, ip)."""
    s = urlsplit(url)
    scheme, host = (s.scheme or "").lower(), (s.hostname or "").lower()
    if scheme not in ("http", "https"):
        raise LinkError(f"scheme {scheme or '(none)'} not allowed")
    if not host or host in ("localhost", "metadata.google.internal", "metadata", "instance-data") or host.endswith((".local", ".internal", ".localhost")):
        raise LinkError("host not allowed")
    port = s.port or (443 if scheme == "https" else 80)
    if port not in (80, 443):
        raise LinkError("port not allowed")
    if s.username or s.password:
        raise LinkError("credentials in URL")
    try:
        ip = ipaddress.ip_address(host)
        infos = [(ip,)]
    except ValueError:
        try:
            infos = [(ipaddress.ip_address(ai[4][0]),) for ai in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]
        except (socket.gaierror, OSError) as e:
            raise LinkError(f"dns failed: {e.__class__.__name__}")
    if not infos:
        raise LinkError("no address")
    for (addr,) in infos:  # every resolved address must be public (a rebinding host with one private answer is refused)
        why = _refuse_ip(addr)
        if why:
            raise LinkError(why)
    return scheme, host, port, str(infos[0][0])


def _head(scheme: str, host: str, port: int, ip: str, path: str) -> tuple[int, str | None]:
    """HEAD to the already-validated IP (not to the hostname, so DNS can't change between check and connect)."""
    sock = socket.create_connection((ip, port), timeout=TIMEOUT)
    try:
        if scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        sock.settimeout(TIMEOUT)
        sock.sendall(f"HEAD {path or '/'} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: project-scout-linkcheck\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while b"\r\n\r\n" not in data and len(data) < MAX_HEADER_BYTES:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
    finally:
        sock.close()
    head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace")
    lines = head.split("\r\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError):
        raise LinkError("bad response")
    loc = next((ln.split(":", 1)[1].strip() for ln in lines[1:] if ln.lower().startswith("location:")), None)
    return status, loc


def safe_resolve(url: str, head=_head, check=check_target) -> str:
    """Follow at most MAX_HOPS redirects; every hop is re-validated (SSRF guard). Never reads a body, never downloads.
    `check` is injectable for tests; in production it is check_target, which does the real DNS + address checks."""
    cur = url
    for _ in range(MAX_HOPS + 1):
        scheme, host, port, ip = check(cur)
        s = urlsplit(cur)
        status, loc = head(scheme, host, port, ip, s.path + (f"?{s.query}" if s.query else ""))
        if status in (301, 302, 303, 307, 308) and loc:
            cur = urljoin(cur, loc)
            continue
        return cur
    raise LinkError("too many redirects")


if __name__ == "__main__":
    import sys
    print(screen_readme(sys.stdin.read(), sys.argv[1] if len(sys.argv) > 1 else "", resolve="--resolve" in sys.argv))
