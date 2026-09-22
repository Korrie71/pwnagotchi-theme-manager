"""Handshake quality: a best-effort look at the raw capture bytes, without waiting on wpa-sec."""
import os
import tempfile

from _util import T, finish, ok, sandbox

sandbox()
HS = tempfile.mkdtemp()
T._handshake_dir = lambda: HS
T.WPA_SEC_DB = os.path.join(HS, ".wpa_sec_db")


def eapol(ack, mic, secure, key_data=b""):
    """A minimal, syntactically valid EAPOL-Key frame (as it would appear inside a captured packet)."""
    info = (0x80 if ack else 0) | (0x100 if mic else 0) | (0x200 if secure else 0)
    key_body = bytes([2]) + info.to_bytes(2, "big") + b"\x00" * (2 + 8 + 32 + 16 + 8 + 8 + 16) + len(key_data).to_bytes(2, "big") + key_data
    return b"\x88\x8e\x02\x03" + len(key_body).to_bytes(2, "big") + key_body  # EtherType, version 2, type 3, body length, body


def pcap(*frames, junk=b"some unrelated packet bytes that do not contain the signature"):
    return junk + junk.join(frames) + junk


def write(name, data):
    p = os.path.join(HS, name)
    open(p, "wb").write(data)
    return p


M1, M2, M3, M4 = eapol(True, False, False), eapol(False, True, False), eapol(True, True, True), eapol(False, True, True)
PMKID_M1 = eapol(True, False, False, key_data=T.PMKID_KDE + b"\x11" * 16 + b"\xdd\x18more RSN stuff")

# ---------------------------------------------------------------- classification
ok("M1 + M2: a real handshake", T._handshake_quality(write("a.pcap", pcap(M1, M2))) == "handshake")
ok("all four messages: still just 'handshake' (M1+M2 is what matters for cracking)", T._handshake_quality(write("b.pcap", pcap(M1, M2, M3, M4))) == "handshake")
ok("only M1 with a PMKID in its key data: 'pmkid'", T._handshake_quality(write("c.pcap", pcap(PMKID_M1))) == "pmkid")
ok("only M1, no PMKID: 'partial' (not enough to crack)", T._handshake_quality(write("d.pcap", pcap(M1))) == "partial")
ok("only M3+M4 (a retried or late capture): 'partial'", T._handshake_quality(write("e.pcap", pcap(M3, M4))) == "partial")
ok("no EAPOL bytes anywhere: 'empty'", T._handshake_quality(write("f.pcap", b"nothing interesting here" * 20)) == "empty")
ok("an empty file: 'empty', not a crash", T._handshake_quality(write("g.pcap", b"")) == "empty")
ok("a file that doesn't exist: 'unknown', not a crash", T._handshake_quality(os.path.join(HS, "missing.pcap")) == "unknown")
ok("a real handshake still counts with noise around it", T._handshake_quality(write("h.pcap", pcap(M1) + pcap(M2))) == "handshake")

# ---------------------------------------------------------------- caching (a file's quality is not re-read every call)
p = write("cache.pcap", pcap(M1, M2))
size0 = os.path.getsize(p)
os.utime(p, (12345, 12345))
ok("computed once", T._handshake_quality(p) == "handshake")
replacement = (pcap(M3) + b"x" * size0)[:size0]   # different bytes, same size
open(p, "wb").write(replacement)
os.utime(p, (12345, 12345))   # same mtime and size as what was cached: an unchanged-looking file
ok("...but a change nobody told it about (same mtime and size) still reads the cache", T._handshake_quality(p) == "handshake")
os.utime(p, (0, 0))   # a genuinely different stat is re-read
ok("a genuinely changed file (new mtime) is re-read", T._handshake_quality(p) == "partial")

# ---------------------------------------------------------------- wired into the dashboard
for f in os.listdir(HS):
    os.remove(os.path.join(HS, f))
T._slow.clear()
write("GoodOne_aabbccddee01.pcapng", pcap(M1, M2))
write("Empty_aabbccddee02.pcapng", b"nothing" * 10)
rows = {r["file"]: r for r in T.crack_rows()}
ok("crack_rows carries the quality through", rows["GoodOne_aabbccddee01.pcapng"]["quality"] == "handshake"
   and rows["Empty_aabbccddee02.pcapng"]["quality"] == "empty")
summary = T.crack_summary()
ok("the summary counts junk captures", summary["junk"] == 1, summary)
ok("the on-screen summary mentions it", "junk" in T._crack_summary_text(summary))
ok("...but only when there is any, and the wording stays plain otherwise", "junk" not in T._crack_summary_text(dict(summary, junk=0)))

finish()
