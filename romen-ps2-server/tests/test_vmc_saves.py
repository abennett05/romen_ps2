"""
Tests for reading saves off a VMC and for the PCSX2 bridge.

Run from the romen-ps2-server directory:

    python tests/test_vmc_saves.py

Phase 2 of VMC support is read-only: ISObe walks a card's filesystem and
converts whole cards between formats, but never writes into a card that holds
saves. These tests cover both halves of that.

The save-writing helpers below exist only to build fixtures. They are
deliberately kept in the test rather than in vmc.py, so the shipped code has no
path that can write into a card at all.
"""

import os
import random
import shutil
import struct
import sys
import tempfile
from array import array

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ps2_ecc
import system
import vmc

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, expected {want!r}")
        FAILURES.append(label)


def section(name):
    print(f"\n{name}")


# - - - FIXTURE BUILDING (test only) - - -

class _CardWriter:
    """Minimal write access to a formatted card, for building fixtures."""

    def __init__(self, path):
        self.f = open(path, 'r+b')
        sb = vmc._SUPERBLOCK.unpack(self.f.read(vmc._SUPERBLOCK.size))
        self.page_size = sb[2]
        self.cluster_size = self.page_size * sb[3]
        self.entries_per_cluster = self.cluster_size // 4
        self.alloc_offset = sb[7]
        self.alloc_end = sb[8]
        self.rootdir = sb[9]
        self.ifc_list = array('I')
        self.ifc_list.frombytes(sb[12])

    def close(self):
        self.f.close()

    def _fat_position(self, n):
        per = self.entries_per_cluster
        fat_index, offset = divmod(n, per)
        ifc_index, indirect_offset = divmod(fat_index, per)
        self.f.seek(self.ifc_list[ifc_index] * self.cluster_size + indirect_offset * 4)
        fat_cluster = struct.unpack("<L", self.f.read(4))[0]
        return fat_cluster * self.cluster_size + offset * 4

    def get_fat(self, n):
        self.f.seek(self._fat_position(n))
        return struct.unpack("<L", self.f.read(4))[0]

    def set_fat(self, n, value):
        self.f.seek(self._fat_position(n))
        self.f.write(struct.pack("<L", value))

    def alloc(self, count):
        """Claim `count` free clusters and chain them together."""
        found = []
        n = 1
        while len(found) < count and n < self.alloc_end:
            if self.get_fat(n) == vmc.FAT_FREE:
                found.append(n)
            n += 1
        if len(found) < count:
            raise RuntimeError("card is full")
        for i, c in enumerate(found):
            nxt = 0x80000000 | found[i + 1] if i + 1 < len(found) else vmc.FAT_CHAIN_END
            self.set_fat(c, nxt)
        return found

    def write_cluster(self, n, data):
        self.f.seek((self.alloc_offset + n) * self.cluster_size)
        self.f.write(data.ljust(self.cluster_size, b"\x00"))

    def add_save(self, folder, files):
        """Add a save directory holding `files` ({name: bytes}) to the root."""
        entry_count = 2 + len(files)
        dir_clusters = self.alloc((entry_count + 1) // 2)
        dir_cluster = dir_clusters[0]

        body = vmc._pack_dirent(
            vmc.DF_RWX | vmc.DF_DIR | vmc.DF_0400 | vmc.DF_EXISTS,
            entry_count, dir_cluster, 0, ".")
        body += vmc._pack_dirent(
            vmc.DF_WRITE | vmc.DF_EXECUTE | vmc.DF_DIR | vmc.DF_0400
            | vmc.DF_HIDDEN | vmc.DF_EXISTS, 0, 0, 0, "..")

        for name, data in files.items():
            needed = max(1, (len(data) + self.cluster_size - 1) // self.cluster_size)
            data_clusters = self.alloc(needed)
            for i, c in enumerate(data_clusters):
                self.write_cluster(c, data[i * self.cluster_size:(i + 1) * self.cluster_size])
            body += vmc._pack_dirent(
                vmc.DF_RWX | vmc.DF_0400 | vmc.DF_EXISTS,
                len(data), data_clusters[0], 0, name)

        for i, c in enumerate(dir_clusters):
            self.write_cluster(c, body[i * self.cluster_size:(i + 1) * self.cluster_size])

        self._append_to_root(folder, dir_cluster, entry_count)

    def _append_to_root(self, name, cluster, entry_count):
        # Read the root's own "." record to find how many entries it has.
        self.f.seek((self.alloc_offset + self.rootdir) * self.cluster_size)
        dot = bytearray(self.f.read(512))
        current = struct.unpack_from("<L", dot, 4)[0]

        # Walk to the cluster the new entry belongs in, extending the chain.
        index = current
        cluster_index, slot = divmod(index, 2)
        chain = [self.rootdir]
        while len(chain) <= cluster_index:
            entry = self.get_fat(chain[-1])
            if entry == vmc.FAT_CHAIN_END:
                new = self.alloc(1)[0]
                self.set_fat(chain[-1], 0x80000000 | new)
                chain.append(new)
            else:
                chain.append(entry & 0x7FFFFFFF)

        record = vmc._pack_dirent(
            vmc.DF_RWX | vmc.DF_DIR | vmc.DF_0400 | vmc.DF_EXISTS,
            entry_count, cluster, 0, name)
        self.f.seek((self.alloc_offset + chain[cluster_index]) * self.cluster_size
                    + slot * 512)
        self.f.write(record)

        # Bump the root's entry count.
        struct.pack_into("<L", dot, 4, current + 1)
        self.f.seek((self.alloc_offset + self.rootdir) * self.cluster_size)
        self.f.write(bytes(dot))


def make_icon_sys(title, break_at=0):
    """A minimal but structurally correct icon.sys."""
    data = bytearray(964)
    data[0:4] = b"PS2D"
    struct.pack_into("<H", data, 0x06, break_at)
    encoded = title.encode('shift_jis')
    data[0xC0:0xC0 + len(encoded)] = encoded
    data[0x104:0x104 + 8] = b"icon.icn"
    return bytes(data)


# - - - ECC - - -

def _reference_ecc(chunk):
    """
    The algorithm transcribed straight from public domain mymc, kept here as an
    oracle so the shipped version's caching can't quietly diverge from it.
    """
    column_parity = 0x77
    line_parity_0 = 0x7F
    line_parity_1 = 0x7F
    for i in range(len(chunk)):
        b = chunk[i]
        column_parity ^= ps2_ecc._COLUMN_PARITY_MASKS[b]
        if ps2_ecc._PARITY_TABLE[b]:
            line_parity_0 ^= ~i
            line_parity_1 ^= i
    return bytes((column_parity, line_parity_0 & 0x7F, line_parity_1 & 0x7F))


def test_ecc():
    section("ECC matches the reference and corrects single bit errors")
    rng = random.Random(20020304)

    mismatched = 0
    for _ in range(200):
        chunk = bytes(rng.getrandbits(8) for _ in range(128))
        if ps2_ecc.ecc_calculate(chunk) != _reference_ecc(chunk):
            mismatched += 1
    check("random chunks match reference", mismatched, 0)

    # Uniform chunks take the cached path, so check them explicitly.
    uniform_bad = [b for b in range(256)
                   if ps2_ecc.ecc_calculate(bytes([b]) * 128) != _reference_ecc(bytes([b]) * 128)]
    check("all uniform chunks match reference", uniform_bad, [])

    # An erased page's code is a published constant; getting it wrong would
    # make every card ISObe exports look corrupt to PCSX2.
    check("erased page spare", ps2_ecc.spare_for_page(b"\x00" * 512).hex(),
          "777f7f777f7f777f7f777f7f00000000")

    uncorrected = 0
    for _ in range(200):
        chunk = bytes(rng.getrandbits(8) for _ in range(128))
        ecc = ps2_ecc.ecc_calculate(chunk)
        damaged = bytearray(chunk)
        damaged[rng.randrange(128)] ^= 1 << rng.randrange(8)
        status, fixed, _ = ps2_ecc.ecc_check(bytes(damaged), ecc)
        if status != ps2_ecc.ECC_CHECK_CORRECTED or fixed != chunk:
            uncorrected += 1
    check("every single bit error corrected", uncorrected, 0)

    # Two bad bits in one chunk is beyond a Hamming code; it must say so
    # rather than "correcting" the data into something else.
    chunk = bytes(rng.getrandbits(8) for _ in range(128))
    ecc = ps2_ecc.ecc_calculate(chunk)
    damaged = bytearray(chunk)
    damaged[10] ^= 0x01
    damaged[80] ^= 0x40
    status, _, _ = ps2_ecc.ecc_check(bytes(damaged), ecc)
    check("two bit error reported, not guessed", status, ps2_ecc.ECC_CHECK_FAILED)


# - - - PCSX2 CONVERSION - - -

def test_pcsx2_roundtrip(tmp):
    section("cards survive a round trip through the PCSX2 format")
    raw = os.path.join(tmp, "bridge.bin")
    vmc._write_formatted_card(raw, 8)

    writer = _CardWriter(raw)
    writer.add_save("BASLUS-20552", {
        "icon.sys": make_icon_sys("SAVE TEST"),
        "game.dat": bytes(range(256)) * 8,
    })
    writer.close()

    ps2 = os.path.join(tmp, "bridge.ps2")
    pages = vmc.convert_to_pcsx2(raw, ps2)
    check("page count", pages, 8 * 1024 * 1024 // 512)
    check("ECC card size", os.path.getsize(ps2), 8650752)
    check("detected as PCSX2", vmc.detect_format(ps2), vmc.FORMAT_PCSX2)
    check("original still detected as raw", vmc.detect_format(raw), vmc.FORMAT_RAW)

    back = os.path.join(tmp, "back.bin")
    corrected, failed = vmc.convert_from_pcsx2(ps2, back)
    check("no pages needed repair", (corrected, failed), (0, 0))

    with open(raw, 'rb') as a, open(back, 'rb') as b:
        check("round trip is byte identical", a.read() == b.read(), True)

    # Flip one bit in a data page and confirm the ECC puts it back.
    with open(ps2, 'r+b') as f:
        f.seek(41 * 1024 + 3)
        original = f.read(1)[0]
        f.seek(41 * 1024 + 3)
        f.write(bytes([original ^ 0x08]))

    repaired = os.path.join(tmp, "repaired.bin")
    corrected, failed = vmc.convert_from_pcsx2(ps2, repaired)
    check("bit rot repaired on import", (corrected >= 1, failed), (True, 0))
    with open(raw, 'rb') as a, open(repaired, 'rb') as b:
        check("repaired card matches the original", a.read() == b.read(), True)


def test_export(tmp):
    section("export serves the right file in each format")
    vmc.create_vmc("EXPORTME", 8)

    raw = vmc.export_vmc("EXPORTME", vmc.FORMAT_RAW)
    check("raw export succeeds", raw["status"], "success")
    check("raw filename", raw["filename"], "EXPORTME.bin")
    check("raw serves the card in place", raw["temporary"], False)
    check("raw path is the real card", raw["path"],
          os.path.join(tmp, "VMC", "EXPORTME.bin"))

    conv = vmc.export_vmc("EXPORTME", vmc.FORMAT_PCSX2, workdir=tmp)
    check("pcsx2 export succeeds", conv["status"], "success")
    check("pcsx2 filename", conv["filename"], "EXPORTME.ps2")
    check("pcsx2 is a temp file", conv["temporary"], True)
    check("pcsx2 size", os.path.getsize(conv["path"]), 8650752)
    os.remove(conv["path"])

    check("unknown format refused",
          vmc.export_vmc("EXPORTME", "zip")["status"], "error")
    check("missing card refused",
          vmc.export_vmc("NOTHERE", vmc.FORMAT_RAW)["status"], "error")


def test_import(tmp):
    section("import accepts both formats and protects existing cards")
    source = os.path.join(tmp, "incoming.bin")
    vmc._write_formatted_card(source, 8)
    writer = _CardWriter(source)
    writer.add_save("BASLUS-21274", {"icon.sys": make_icon_sys("IMPORTED")})
    writer.close()

    result = vmc.import_vmc(source, "FROMRAW")
    check("raw import succeeds", result["status"], "success")
    check("source format reported", result["source_format"], vmc.FORMAT_RAW)
    check("imported card is valid", result["vmc"]["valid"], True)
    check("saves came across",
          [s["folder"] for s in vmc.browse_vmc("FROMRAW")["saves"]], ["BASLUS-21274"])

    ps2 = os.path.join(tmp, "incoming.ps2")
    vmc.convert_to_pcsx2(source, ps2)
    result = vmc.import_vmc(ps2, "FROMPCSX2")
    check("pcsx2 import succeeds", result["status"], "success")
    check("pcsx2 format detected", result["source_format"], vmc.FORMAT_PCSX2)
    check("stored as a raw OPL card",
          os.path.getsize(os.path.join(tmp, "VMC", "FROMPCSX2.bin")), 8388608)
    check("saves survived the conversion",
          [s["folder"] for s in vmc.browse_vmc("FROMPCSX2")["saves"]], ["BASLUS-21274"])

    # An existing card must not be replaced by accident.
    check("overwrite refused by default",
          vmc.import_vmc(source, "FROMRAW")["status"], "error")
    check("overwrite allowed when asked",
          vmc.import_vmc(source, "FROMRAW", overwrite=True)["status"], "success")

    junk = os.path.join(tmp, "notacard.bin")
    with open(junk, 'wb') as f:
        f.write(b"this is not a memory card" * 100)
    check("junk file refused", vmc.import_vmc(junk, "JUNK")["status"], "error")
    check("nothing written for a refused import",
          os.path.exists(os.path.join(tmp, "VMC", "JUNK.bin")), False)

    # A card whose size doesn't match its own superblock is refused.
    truncated = os.path.join(tmp, "short.bin")
    shutil.copyfile(source, truncated)
    with open(truncated, 'r+b') as f:
        f.truncate(8388608 - 1024)
    check("truncated card refused", vmc.import_vmc(truncated, "SHORT")["status"], "error")

    # A failed import must leave no scratch files behind on the drive.
    leftovers = [n for n in os.listdir(os.path.join(tmp, "VMC"))
                 if n.startswith(".isobe-import")]
    check("no temp files left in the VMC folder", leftovers, [])


# - - - SAVE BROWSER - - -

def test_icon_sys():
    section("icon.sys titles decode the way the PS2 shows them")
    check("plain title", vmc.parse_icon_sys(make_icon_sys("METAL GEAR SOLID 2")),
          "METAL GEAR SOLID 2")
    check("two line title joined",
          vmc.parse_icon_sys(make_icon_sys("GRAN TURISMO 4SAVE DATA", break_at=14)),
          "GRAN TURISMO 4 SAVE DATA")
    check("shift-jis decoded",
          vmc.parse_icon_sys(make_icon_sys("ドラゴンクエスト")), "ドラゴンクエスト")
    check("not an icon.sys", vmc.parse_icon_sys(b"\x00" * 964), None)
    check("truncated file", vmc.parse_icon_sys(b"PS2D"), None)


def test_serial_from_save_name():
    section("save folders map back to game serials")
    check("US save", vmc.serial_from_save_name("BASLUS-20552"), "SLUS-20552")
    check("EU save", vmc.serial_from_save_name("BESLES-50457"), "SLES-50457")
    check("JP save", vmc.serial_from_save_name("BISLPM-65001"), "SLPM-65001")
    check("Sony published", vmc.serial_from_save_name("BASCUS-97328"), "SCUS-97328")
    check("already clean", vmc.serial_from_save_name("SLUS-20552"), "SLUS-20552")
    check("system folder ignored", vmc.serial_from_save_name("SYS-CONF"), None)
    check("empty name", vmc.serial_from_save_name(""), None)


def test_save_browser(tmp):
    section("the save browser reads what is actually on the card")
    path = os.path.join(tmp, "VMC", "SAVES.bin")
    vmc.create_vmc("SAVES", 8)

    before = vmc.inspect_vmc(path)["free_bytes"]

    writer = _CardWriter(path)
    writer.add_save("BASLUS-20552", {
        "icon.sys": make_icon_sys("METAL GEAR SOLID 2"),
        "game.sys": b"\x01" * 2048,
        "save.bin": b"\x02" * 5000,
    })
    writer.add_save("BASCUS-97328", {
        "icon.sys": make_icon_sys("JAK AND DAXTER"),
        "progress.dat": b"\x03" * 900,
    })
    writer.close()

    result = vmc.browse_vmc("SAVES")
    check("browse succeeds", result["status"], "success")

    saves = {s["folder"]: s for s in result["saves"]}
    check("both saves found", sorted(saves), ["BASCUS-97328", "BASLUS-20552"])

    mgs = saves["BASLUS-20552"]
    check("serial resolved", mgs["serial"], "SLUS-20552")
    check("icon.sys title read", mgs["icon_title"], "METAL GEAR SOLID 2")
    check("file count excludes . and ..", mgs["file_count"], 3)
    check("size is the sum of the files", mgs["size"], 964 + 2048 + 5000)
    check("files listed in order", [f["name"] for f in mgs["files"]],
          ["game.sys", "icon.sys", "save.bin"])
    check("cover url built from the serial",
          mgs["cover_url"].endswith("/SLUS-20552.jpg"), True)
    check("modified date decoded", isinstance(mgs["modified"], str), True)

    jak = saves["BASCUS-97328"]
    check("second save's title", jak["icon_title"], "JAK AND DAXTER")
    check("second save's size", jak["size"], 964 + 900)

    # Free space must have dropped by roughly what the saves occupy; this is
    # the cross-check that the writer and the FAT reader agree.
    after = vmc.inspect_vmc(path)["free_bytes"]
    check("free space fell", after < before, True)
    check("free space fell by whole clusters", (before - after) % 1024, 0)

    # An empty card reports no saves rather than failing.
    vmc.create_vmc("EMPTY", 8)
    check("empty card browses cleanly", vmc.browse_vmc("EMPTY")["saves"], [])

    check("missing card refused", vmc.browse_vmc("GHOST")["status"], "error")


def test_names_cannot_escape_the_vmc_folder(tmp):
    section("download and browse names stay inside the VMC folder")
    # Export serves a file straight to the browser, so a name that walks up the
    # tree would hand out arbitrary files off the drive.
    secret = os.path.join(tmp, "secret.bin")
    with open(secret, 'wb') as f:
        f.write(b"not for download")

    for name in ("../secret", "../../etc/passwd", "..\\..\\secret",
                 "VMC/../secret", "/etc/passwd"):
        result = vmc.export_vmc(name, vmc.FORMAT_RAW)
        served = result.get("path")
        escaped = served is not None and not os.path.abspath(served).startswith(
            os.path.abspath(os.path.join(tmp, "VMC")) + os.sep)
        check(f"export {name!r} stays inside VMC", escaped, False)
        check(f"browse {name!r} refused", vmc.browse_vmc(name)["status"], "error")

    check("secret file untouched", os.path.exists(secret), True)


def test_reader_rejects_bad_cards(tmp):
    section("the reader refuses files that aren't cards")
    junk = os.path.join(tmp, "junk.bin")
    with open(junk, 'wb') as f:
        f.write(b"\x00" * 8388608)

    try:
        vmc.CardReader(junk)
        check("zeroed file rejected", "opened", "ValueError")
    except ValueError:
        check("zeroed file rejected", "ValueError", "ValueError")

    tiny = os.path.join(tmp, "tiny.bin")
    with open(tiny, 'wb') as f:
        f.write(b"Sony PS2 Memory Card Format 1.2.0.0")
    try:
        vmc.CardReader(tiny)
        check("truncated file rejected", "opened", "ValueError")
    except ValueError:
        check("truncated file rejected", "ValueError", "ValueError")


def main():
    tmp = tempfile.mkdtemp(prefix="isobe-saves-test-")
    system.CONFIG.LIB_PATH = tmp
    system.CONFIG.COVERS_URL = "https://covers.example/covers"
    print(f"Using temporary library at {tmp}")
    try:
        test_ecc()
        test_icon_sys()
        test_serial_from_save_name()
        test_pcsx2_roundtrip(tmp)
        test_export(tmp)
        test_import(tmp)
        test_save_browser(tmp)
        test_names_cannot_escape_the_vmc_folder(tmp)
        test_reader_rejects_bad_cards(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("All VMC save/export checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
