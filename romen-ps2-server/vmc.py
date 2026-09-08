"""
Virtual Memory Card (VMC) support for Open PS2 Loader.

A VMC is a raw PS2 memory card image with 512 byte pages and no ECC spare
bytes. OPL validates one in sysCheckVMC() by checking the superblock magic,
that mc_type is 2, and that the file size is exactly

    pages_per_cluster * clusters_per_card * page_size

which for an 8MB card is 2 * 8192 * 512 = 8388608 bytes. Sizes must also be a
whole number of megabytes.

Cards live in <library>/VMC/<name>.bin and are bound to a game through the
$VMC_0 (slot 1) and $VMC_1 (slot 2) keys in <library>/CFG/<serial>.cfg. OPL
stores the name there without the .bin extension.

The memory card filesystem layout written here follows the public domain
`mymc` utility by Ross Ridge (https://github.com/ps2dev/mymc).
"""

import os
import re
import shutil
import struct
import tempfile
import time
from array import array

import ps2_ecc
import system

# - - - FORMAT CONSTANTS - - -

MAGIC = b"Sony PS2 Memory Card Format "
VERSION = b"1.2.0.0"

PAGE_SIZE = 512
CLUSTER_SIZE = 1024
PAGES_PER_ERASE_BLOCK = 16
INDIRECT_FAT_OFFSET = 0x2000
MAX_INDIRECT_FAT_CLUSTERS = 32

# FAT entry values. Bit 31 marks a cluster as allocated; the low 31 bits are
# the next cluster in the chain, or 0x7FFFFFFF to end it.
FAT_FREE = 0x7FFFFFFF
FAT_CHAIN_END = 0xFFFFFFFF

CARD_TYPE_PS2 = 2
CARD_FLAGS = 0x2B

# Directory entry mode bits.
DF_READ = 0x0001
DF_WRITE = 0x0002
DF_EXECUTE = 0x0004
DF_RWX = DF_READ | DF_WRITE | DF_EXECUTE
DF_DIR = 0x0020
DF_0400 = 0x0400
DF_HIDDEN = 0x2000
DF_EXISTS = 0x8000

_SUPERBLOCK = struct.Struct("<28s12sHHHHLLLLLL8x128s128sbbxx")
_DIRENT = struct.Struct("<HHL8sLL8sL28x448s")
_TOD = struct.Struct("<xBBBBBH")

# Sizes OPL offers. Anything else is rejected rather than silently rounded.
VALID_SIZES_MB = (8, 16, 32, 64)
DEFAULT_SIZE_MB = 8

# OPL's VMC name entry field tops out at 32 characters.
MAX_NAME_LENGTH = 32


def _div_round_up(a, b):
    return (a + b - 1) // b


def _tod_now():
    """Current time as a PS2 ToD tuple. The PS2 clock runs on JST."""
    tm = time.gmtime(time.time() + 9 * 3600)
    return (tm.tm_sec, tm.tm_min, tm.tm_hour, tm.tm_mday, tm.tm_mon, tm.tm_year)


def _pack_dirent(mode, length, cluster, parent_entry, name):
    tod = _TOD.pack(*_tod_now())
    return _DIRENT.pack(mode, 0, length, tod, cluster, parent_entry, tod, 0,
                        name.encode('ascii'))


# - - - PATHS - - -

def get_vmc_dir():
    """The VMC folder on the library drive, or None if no drive is set."""
    if not system.CONFIG.LIB_PATH:
        return None
    return os.path.join(system.CONFIG.LIB_PATH, 'VMC')


def get_cfg_dir():
    if not system.CONFIG.LIB_PATH:
        return None
    return os.path.join(system.CONFIG.LIB_PATH, 'CFG')


def sanitize_name(name):
    """
    Reduce a name to something safe for exFAT and accepted by OPL.
    Returns an empty string if nothing usable is left.
    """
    if not name:
        return ""
    # Strip anything that is a path separator or illegal on exFAT, plus dots
    # so the name can never grow a second extension.
    clean = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', '', name).strip()
    return clean[:MAX_NAME_LENGTH]


def name_for_serial(serial):
    """
    The auto-generated VMC name for a game. Uses the same cleaned serial form
    as the artwork files (SLUS_200.02 -> SLUS-20002) so the VMC sorts next to
    the game it belongs to.
    """
    import database as db
    return db.clean_serial(serial)


# - - - CREATE - - -

def create_vmc(name, size_mb=DEFAULT_SIZE_MB, overwrite=False):
    """
    Create and format a new VMC. Returns a status dict.
    """
    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    clean = sanitize_name(name)
    if not clean:
        return {"status": "error", "message": "Invalid VMC name."}

    if size_mb not in VALID_SIZES_MB:
        sizes = ", ".join(f"{s}MB" for s in VALID_SIZES_MB)
        return {"status": "error", "message": f"Size must be one of: {sizes}."}

    os.makedirs(vmc_dir, exist_ok=True)
    path = os.path.join(vmc_dir, f"{clean}.bin")

    if os.path.exists(path) and not overwrite:
        return {"status": "error", "message": f"A VMC named '{clean}' already exists."}

    try:
        _write_formatted_card(path, size_mb)
    except Exception as e:
        # Never leave a half written card behind; OPL would try to use it.
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        print(f"[VMC] Failed to create {clean}: {e}")
        return {"status": "error", "message": f"Failed to create VMC: {e}"}

    print(f"[VMC] Created {size_mb}MB card at {path}")
    return {
        "status": "success",
        "message": f"Created {clean} ({size_mb}MB)",
        "vmc": describe_vmc(path),
    }


def _write_formatted_card(path, size_mb):
    """
    Write a freshly formatted memory card image to `path`.

    The full image is written in one sequential pass before any region is
    patched, so the file lands contiguously on an otherwise healthy drive.
    OPL requires unfragmented VMC files.
    """
    pages_per_card = size_mb * 1024 * 1024 // PAGE_SIZE
    pages_per_cluster = CLUSTER_SIZE // PAGE_SIZE
    clusters_per_card = pages_per_card // pages_per_cluster
    clusters_per_erase_block = PAGES_PER_ERASE_BLOCK // pages_per_cluster
    erase_blocks_per_card = pages_per_card // PAGES_PER_ERASE_BLOCK
    entries_per_cluster = CLUSTER_SIZE // 4

    good_block1 = erase_blocks_per_card - 1
    good_block2 = erase_blocks_per_card - 2
    first_ifc = _div_round_up(INDIRECT_FAT_OFFSET, CLUSTER_SIZE)

    # Size the FAT to cover everything that is left after the reserved area.
    allocatable = clusters_per_card - (first_ifc + 2)
    fat_clusters = _div_round_up(allocatable, entries_per_cluster)
    indirect_fat_clusters = _div_round_up(fat_clusters, entries_per_cluster)
    if indirect_fat_clusters > MAX_INDIRECT_FAT_CLUSTERS:
        indirect_fat_clusters = MAX_INDIRECT_FAT_CLUSTERS
        fat_clusters = indirect_fat_clusters * entries_per_cluster
    allocatable = fat_clusters * entries_per_cluster

    alloc_offset = first_ifc + indirect_fat_clusters + fat_clusters
    alloc_end = good_block2 * clusters_per_erase_block - alloc_offset
    if alloc_end < 1:
        raise ValueError("Card size too small to format.")

    first_fat_cluster = first_ifc + indirect_fat_clusters

    with open(path, 'wb') as f:
        # 1. Erase the whole card.
        blank = b"\x00" * (1024 * 1024)
        remaining = pages_per_card * PAGE_SIZE
        while remaining > 0:
            chunk = min(remaining, len(blank))
            f.write(blank[:chunk])
            remaining -= chunk

        # 2. Superblock on page 0.
        ifc_list = array('I', [0] * MAX_INDIRECT_FAT_CLUSTERS)
        for i in range(indirect_fat_clusters):
            ifc_list[i] = first_ifc + i
        bad_blocks = array('I', [0xFFFFFFFF] * 32)

        superblock = _SUPERBLOCK.pack(
            MAGIC,
            VERSION,
            PAGE_SIZE,
            pages_per_cluster,
            PAGES_PER_ERASE_BLOCK,
            0xFF00,
            clusters_per_card,
            alloc_offset,
            alloc_end,
            0,              # root directory is allocatable cluster 0
            good_block1,
            good_block2,
            ifc_list.tobytes(),
            bad_blocks.tobytes(),
            CARD_TYPE_PS2,
            CARD_FLAGS,
        )
        f.seek(0)
        f.write(superblock)

        # 3. Indirect FAT clusters: each entry points at one FAT cluster.
        remainder = fat_clusters % entries_per_cluster
        for i in range(indirect_fat_clusters):
            base = first_fat_cluster + i * entries_per_cluster
            buf = array('I', range(base, base + entries_per_cluster))
            if i == indirect_fat_clusters - 1 and remainder != 0:
                for j in range(remainder, entries_per_cluster):
                    buf[j] = 0xFFFFFFFF
            _write_cluster(f, ifc_list[i], buf.tobytes())

        # 4. FAT. Everything is free except cluster 0 (the root directory) and
        #    the tail that falls outside the usable area.
        fat = array('I', [FAT_FREE]) * allocatable
        for i in range(alloc_end, allocatable):
            fat[i] = FAT_CHAIN_END
        fat[0] = FAT_CHAIN_END

        fat_bytes = fat.tobytes()
        for i in range(fat_clusters):
            start = i * CLUSTER_SIZE
            _write_cluster(f, first_fat_cluster + i,
                           fat_bytes[start:start + CLUSTER_SIZE])

        # 5. Root directory: "." and ".." in the first allocatable cluster.
        root = _pack_dirent(DF_RWX | DF_DIR | DF_0400 | DF_EXISTS, 2, 0, 0, ".")
        root += _pack_dirent(
            DF_WRITE | DF_EXECUTE | DF_DIR | DF_0400 | DF_HIDDEN | DF_EXISTS,
            0, 0, 0, "..")
        _write_cluster(f, alloc_offset, root)

        # 6. The spare erase block is left erased to 0xFF.
        f.seek(good_block2 * PAGES_PER_ERASE_BLOCK * PAGE_SIZE)
        f.write(b"\xFF" * (PAGES_PER_ERASE_BLOCK * PAGE_SIZE))

        f.flush()
        os.fsync(f.fileno())


def _write_cluster(f, cluster, data):
    f.seek(cluster * CLUSTER_SIZE)
    f.write(data)


# - - - INSPECT / LIST - - -

def inspect_vmc(path):
    """
    Parse a VMC superblock and apply the same validity test OPL does.
    Returns a dict, with "valid" False if OPL would reject the file.
    """
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            raw = f.read(_SUPERBLOCK.size)

        if len(raw) < _SUPERBLOCK.size:
            return {"valid": False, "size": size, "reason": "File too small to hold a superblock."}

        (magic, version, page_size, pages_per_cluster, pages_per_block, _unused,
         clusters_per_card, alloc_offset, alloc_end, rootdir, _gb1, _gb2,
         _ifc, _bad, card_type, card_flags) = _SUPERBLOCK.unpack(raw)

        info = {
            "size": size,
            "size_mb": size // (1024 * 1024),
            "page_size": page_size,
            "clusters_per_card": clusters_per_card,
            "card_type": card_type,
            "version": version.split(b"\x00")[0].decode('ascii', 'ignore'),
        }

        # OPL compares the first 27 bytes only.
        if not magic.startswith(MAGIC[:27]):
            info.update(valid=False, reason="Not a PS2 memory card image.")
            return info
        if card_type != CARD_TYPE_PS2:
            info.update(valid=False, reason=f"Card type is {card_type}, expected 2.")
            return info

        expected = pages_per_cluster * clusters_per_card * page_size
        if size != expected:
            info.update(valid=False,
                        reason=f"Size is {size} bytes, superblock describes {expected}.")
            return info
        if size % (1024 * 1024):
            info.update(valid=False, reason="Size is not a whole number of megabytes.")
            return info

        # Free space, counted straight out of the FAT.
        info["free_bytes"] = _count_free_space(path, page_size, pages_per_cluster,
                                               alloc_offset, alloc_end, rootdir)
        info["valid"] = True
        return info
    except Exception as e:
        return {"valid": False, "reason": str(e)}


def _count_free_space(path, page_size, pages_per_cluster, alloc_offset, alloc_end, rootdir):
    """Walk the FAT and total up the unallocated clusters."""
    cluster_size = page_size * pages_per_cluster
    entries_per_cluster = cluster_size // 4
    try:
        with open(path, 'rb') as f:
            # Re-read the indirect FAT list from the superblock.
            f.seek(0)
            sb = _SUPERBLOCK.unpack(f.read(_SUPERBLOCK.size))
            ifc_list = array('I')
            ifc_list.frombytes(sb[12])

            free = 0
            checked = 0
            for ifc in ifc_list:
                if checked >= alloc_end or ifc == 0 or ifc == 0xFFFFFFFF:
                    break
                f.seek(ifc * cluster_size)
                fat_clusters = array('I')
                fat_clusters.frombytes(f.read(cluster_size))
                for fc in fat_clusters:
                    if checked >= alloc_end or fc == 0xFFFFFFFF:
                        break
                    f.seek(fc * cluster_size)
                    entries = array('I')
                    entries.frombytes(f.read(cluster_size))
                    for entry in entries:
                        if checked >= alloc_end:
                            break
                        if not (entry & 0x80000000):
                            free += 1
                        checked += 1
            return free * cluster_size
    except Exception:
        return None


def describe_vmc(path):
    """Summary of a single VMC file for the API."""
    name = os.path.splitext(os.path.basename(path))[0]
    info = inspect_vmc(path)
    return {
        "name": name,
        "filename": os.path.basename(path),
        "path": path,
        "size": info.get("size"),
        "size_mb": info.get("size_mb"),
        "free_bytes": info.get("free_bytes"),
        "valid": info.get("valid", False),
        "reason": info.get("reason"),
    }


def list_vmcs():
    """Every .bin in the VMC folder, with the games each one is bound to."""
    vmc_dir = get_vmc_dir()
    if not vmc_dir or not os.path.isdir(vmc_dir):
        return []

    assignments = get_all_assignments()

    cards = []
    for entry in sorted(os.listdir(vmc_dir)):
        if not entry.lower().endswith('.bin'):
            continue
        card = describe_vmc(os.path.join(vmc_dir, entry))
        card["assigned_to"] = assignments.get(card["name"], [])
        cards.append(card)
    return cards


def delete_vmc(name):
    """Delete a VMC and clear it from any game config that referenced it."""
    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    clean = sanitize_name(name)
    path = os.path.join(vmc_dir, f"{clean}.bin")
    if not os.path.exists(path):
        return {"status": "error", "message": f"VMC '{clean}' not found."}

    # Unbind first so a failure here can't leave a game pointing at a card
    # that no longer exists.
    freed = []
    for serial, slots in get_all_assignments_by_serial().items():
        for slot, assigned in slots.items():
            if assigned == clean:
                unassign_vmc(serial, slot)
                freed.append(serial)

    try:
        os.remove(path)
    except OSError as e:
        return {"status": "error", "message": f"Failed to delete VMC: {e}"}

    print(f"[VMC] Deleted {path}")
    return {
        "status": "success",
        "message": f"Deleted {clean}",
        "unassigned_from": freed,
    }


# - - - OPL PER-GAME CONFIG - - -
#
# OPL writes these as plain key=value lines with CRLF endings. Order is
# preserved on read/write so the compatibility flags and title that ISObe
# downloads from the community CFG repo survive an edit.

VMC_SLOT_KEYS = {0: "$VMC_0", 1: "$VMC_1"}


def _cfg_path(serial):
    cfg_dir = get_cfg_dir()
    if not cfg_dir:
        return None
    return os.path.join(cfg_dir, f"{serial}.cfg")


def _read_cfg(path):
    """Read an OPL config into an ordered list of (key, value) pairs."""
    if not path or not os.path.exists(path):
        return []
    entries = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line:
                continue
            key, sep, value = line.partition('=')
            if not sep:
                # Keep comments and anything unparseable exactly as found.
                entries.append((line, None))
            else:
                entries.append((key, value))
    return entries


def _write_cfg(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        for key, value in entries:
            if value is None:
                f.write(f"{key}\r\n")
            else:
                f.write(f"{key}={value}\r\n")


def get_assignments(serial):
    """The VMC bound to each slot for one game, e.g. {0: "SLUS-20002", 1: None}."""
    entries = dict(e for e in _read_cfg(_cfg_path(serial)) if e[1] is not None)
    return {slot: entries.get(key) or None for slot, key in VMC_SLOT_KEYS.items()}


def get_all_assignments_by_serial():
    """{serial: {slot: vmc_name}} across every CFG file on the drive."""
    cfg_dir = get_cfg_dir()
    result = {}
    if not cfg_dir or not os.path.isdir(cfg_dir):
        return result
    for entry in os.listdir(cfg_dir):
        if not entry.lower().endswith('.cfg'):
            continue
        serial = os.path.splitext(entry)[0]
        slots = get_assignments(serial)
        if any(slots.values()):
            result[serial] = slots
    return result


def get_all_assignments():
    """Inverted view: {vmc_name: [serial, ...]}."""
    result = {}
    for serial, slots in get_all_assignments_by_serial().items():
        for name in slots.values():
            if name:
                result.setdefault(name, [])
                if serial not in result[name]:
                    result[name].append(serial)
    return result


def assign_vmc(serial, name, slot=0):
    """Bind a VMC to a memory card slot for one game."""
    if slot not in VMC_SLOT_KEYS:
        return {"status": "error", "message": "Slot must be 0 or 1."}

    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    clean = sanitize_name(name)
    path = os.path.join(vmc_dir, f"{clean}.bin")
    if not os.path.exists(path):
        return {"status": "error", "message": f"VMC '{clean}' not found."}

    info = inspect_vmc(path)
    if not info.get("valid"):
        return {"status": "error",
                "message": f"VMC '{clean}' is not a valid card: {info.get('reason')}"}

    cfg = _cfg_path(serial)
    entries = _read_cfg(cfg)
    key = VMC_SLOT_KEYS[slot]

    replaced = False
    for i, (k, v) in enumerate(entries):
        if k == key and v is not None:
            entries[i] = (key, clean)
            replaced = True
            break
    if not replaced:
        entries.append((key, clean))

    _write_cfg(cfg, entries)
    print(f"[VMC] Assigned {clean} to {serial} slot {slot + 1}")
    return {"status": "success", "message": f"{clean} assigned to slot {slot + 1}"}


def unassign_vmc(serial, slot=0):
    """Clear a slot. OPL removes the key entirely rather than blanking it."""
    if slot not in VMC_SLOT_KEYS:
        return {"status": "error", "message": "Slot must be 0 or 1."}

    cfg = _cfg_path(serial)
    if not cfg or not os.path.exists(cfg):
        return {"status": "success", "message": "Nothing assigned."}

    key = VMC_SLOT_KEYS[slot]
    entries = [(k, v) for k, v in _read_cfg(cfg) if not (k == key and v is not None)]
    _write_cfg(cfg, entries)
    print(f"[VMC] Cleared slot {slot + 1} for {serial}")
    return {"status": "success", "message": f"Slot {slot + 1} cleared"}


def provision_for_game(serial, size_mb=DEFAULT_SIZE_MB):
    """
    Give a game its own VMC and bind it to slot 1. Used by the auto-provision
    setting when a game is added. Reuses an existing card of the same name
    rather than overwriting a card that may already hold saves.
    """
    name = name_for_serial(serial)
    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    path = os.path.join(vmc_dir, f"{name}.bin")
    if not os.path.exists(path):
        result = create_vmc(name, size_mb)
        if result["status"] != "success":
            return result

    return assign_vmc(serial, name, slot=0)


# - - - READING A CARD - - -
#
# Everything below this line opens cards 'rb' and never writes into one. A
# save browser that can corrupt saves is worse than no save browser, so the
# read path has no write path to get wrong.

# Directory entries are one per 512 byte page, so two to a cluster.
DIRENTS_PER_CLUSTER = CLUSTER_SIZE // 512

# icon.sys, the file every save carries to describe itself on the PS2's own
# memory card screen. Fixed 964 byte layout; the title is Shift-JIS.
ICON_SYS_MAGIC = b"PS2D"
ICON_SYS_TITLE_OFFSET = 0xC0
ICON_SYS_TITLE_LENGTH = 68
ICON_SYS_LINEBREAK_OFFSET = 0x06

# Save folders are named after the game serial with a region letter glued on
# the front, e.g. BASLUS-20552 for SLUS-20552.
_SERIAL_IN_NAME = re.compile(r'([A-Z]{4})[-_]?(\d{5})')


class CardReader:
    """
    Read-only view of a memory card's filesystem.

    Opens the image, resolves the FAT through the indirect FAT, and walks the
    directory tree. Raises ValueError if the card isn't one OPL would accept,
    so callers never end up parsing garbage as a directory.
    """

    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        try:
            self._read_superblock()
        except Exception:
            self.f.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.f.close()

    def _read_superblock(self):
        raw = self.f.read(_SUPERBLOCK.size)
        if len(raw) < _SUPERBLOCK.size:
            raise ValueError("File is too small to be a memory card.")

        (magic, _version, page_size, pages_per_cluster, _ppb, _unused,
         clusters_per_card, alloc_offset, alloc_end, rootdir, _gb1, _gb2,
         ifc, _bad, card_type, _flags) = _SUPERBLOCK.unpack(raw)

        if not magic.startswith(MAGIC[:27]):
            raise ValueError("Not a PS2 memory card image.")
        if card_type != CARD_TYPE_PS2:
            raise ValueError(f"Card type is {card_type}, expected 2.")

        self.page_size = page_size
        self.cluster_size = page_size * pages_per_cluster
        self.entries_per_cluster = self.cluster_size // 4
        self.clusters_per_card = clusters_per_card
        self.alloc_offset = alloc_offset
        self.alloc_end = alloc_end
        self.rootdir = rootdir

        self.ifc_list = array('I')
        self.ifc_list.frombytes(ifc)

        self._fat_cache = {}

    # - - - cluster / FAT plumbing - - -

    def _read_cluster(self, cluster):
        """Read one physical cluster."""
        if cluster < 0 or cluster >= self.clusters_per_card:
            raise ValueError(f"Cluster {cluster} is outside the card.")
        self.f.seek(cluster * self.cluster_size)
        data = self.f.read(self.cluster_size)
        if len(data) != self.cluster_size:
            raise ValueError(f"Card ends before cluster {cluster}.")
        return data

    def _fat_entry(self, n):
        """
        The FAT entry for allocatable cluster `n`, resolved through the two
        level indirect FAT.
        """
        per = self.entries_per_cluster
        fat_index, offset = divmod(n, per)
        ifc_index, indirect_offset = divmod(fat_index, per)

        if ifc_index >= len(self.ifc_list):
            raise ValueError(f"Cluster {n} is beyond the indirect FAT.")

        indirect_cluster = self.ifc_list[ifc_index]
        table = self._fat_cache.get(indirect_cluster)
        if table is None:
            table = array('I')
            table.frombytes(self._read_cluster(indirect_cluster))
            self._fat_cache[indirect_cluster] = table

        fat_cluster = table[indirect_offset]
        if fat_cluster == 0xFFFFFFFF:
            raise ValueError(f"Cluster {n} has no FAT entry.")

        entries = self._fat_cache.get(('fat', fat_cluster))
        if entries is None:
            entries = array('I')
            entries.frombytes(self._read_cluster(fat_cluster))
            self._fat_cache[('fat', fat_cluster)] = entries

        return entries[offset]

    def _chain(self, first):
        """
        Walk a cluster chain, yielding physical cluster numbers.

        A corrupt card can describe a chain that loops; the visited set turns
        that into a short read rather than a hung request.
        """
        seen = set()
        cluster = first
        while cluster != 0xFFFFFFFF and (cluster & 0x7FFFFFFF) != FAT_FREE:
            n = cluster & 0x7FFFFFFF
            if n in seen or n >= self.alloc_end:
                break
            seen.add(n)
            yield self.alloc_offset + n
            cluster = self._fat_entry(n)

    def read_data(self, first_cluster, length):
        """Read `length` bytes from the chain starting at an allocatable cluster."""
        out = bytearray()
        for cluster in self._chain(first_cluster):
            out += self._read_cluster(cluster)
            if len(out) >= length:
                break
        return bytes(out[:length])

    # - - - directories - - -

    def read_dir(self, first_cluster, count):
        """
        The live entries of a directory. `count` is the entry count stored in
        the directory's own record, capped so a bad value can't spin.
        """
        count = max(0, min(int(count), 4096))
        entries = []
        needed = _div_round_up(count, DIRENTS_PER_CLUSTER)
        for cluster in self._chain(first_cluster):
            if needed <= 0:
                break
            needed -= 1
            raw = self._read_cluster(cluster)
            for i in range(DIRENTS_PER_CLUSTER):
                if len(entries) >= count:
                    break
                chunk = raw[i * 512:(i + 1) * 512]
                if len(chunk) < _DIRENT.size:
                    break
                entry = self._parse_dirent(chunk)
                if entry:
                    entries.append(entry)
        return entries

    def _parse_dirent(self, raw):
        (mode, _unused, length, created, cluster, _parent, modified, _attr,
         name) = _DIRENT.unpack(raw[:_DIRENT.size])

        if not (mode & DF_EXISTS):
            return None

        clean_name = name.split(b"\x00")[0].decode('ascii', 'replace')
        if not clean_name:
            return None

        return {
            "name": clean_name,
            "mode": mode,
            "is_dir": bool(mode & DF_DIR),
            "length": length,
            "cluster": cluster,
            "created": _decode_tod(created),
            "modified": _decode_tod(modified),
        }

    def root_entries(self):
        """
        The root directory's entries.

        How many there are is recorded in the root's own "." entry, which is
        the first record in the root cluster, so that one is read on its own
        before the rest of the directory.
        """
        raw = self._read_cluster(self.alloc_offset + self.rootdir)
        dot = self._parse_dirent(raw[:512])
        return self.read_dir(self.rootdir, dot["length"] if dot else 0)


def _decode_tod(raw):
    """A PS2 ToD stamp as an ISO date string, or None if it was never set."""
    try:
        sec, minute, hour, day, month, year = _TOD.unpack(raw)
    except struct.error:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1980 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{sec:02d}"


def parse_icon_sys(data):
    """
    The display title out of a save's icon.sys.

    Titles are Shift-JIS and usually carry a line break offset so the PS2 can
    render them over two lines; we join them with a space. Returns None for
    anything that isn't a well formed icon.sys.
    """
    if len(data) < ICON_SYS_TITLE_OFFSET + ICON_SYS_TITLE_LENGTH:
        return None
    if not data.startswith(ICON_SYS_MAGIC):
        return None

    raw = data[ICON_SYS_TITLE_OFFSET:ICON_SYS_TITLE_OFFSET + ICON_SYS_TITLE_LENGTH]
    raw = raw.split(b"\x00")[0]

    break_at = struct.unpack_from("<H", data, ICON_SYS_LINEBREAK_OFFSET)[0]
    if 0 < break_at < len(raw):
        parts = [raw[:break_at], raw[break_at:]]
    else:
        parts = [raw]

    lines = []
    for part in parts:
        try:
            text = part.decode('shift_jis', 'replace')
        except LookupError:
            text = part.decode('ascii', 'replace')
        text = text.replace("�", "").strip()
        if text:
            lines.append(text)

    return " ".join(lines) if lines else None


def serial_from_save_name(name):
    """
    The game serial a save folder belongs to, e.g. BASLUS-20552 -> SLUS-20552.
    Returns None for saves that aren't named after a serial, like the system
    configuration folders.
    """
    match = _SERIAL_IN_NAME.search(name.upper())
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def list_saves(path):
    """
    Every save on a card: its folder, the title from icon.sys, the game it
    belongs to and how much of the card it uses.
    """
    import database as db

    with CardReader(path) as card:
        saves = []
        for entry in card.root_entries():
            if not entry["is_dir"] or entry["name"] in (".", ".."):
                continue

            files = []
            icon_title = None
            used = 0
            try:
                for child in card.read_dir(entry["cluster"], entry["length"]):
                    if child["is_dir"] or child["name"] in (".", ".."):
                        continue
                    files.append({"name": child["name"], "size": child["length"]})
                    used += child["length"]
                    if child["name"].lower() == "icon.sys":
                        icon_title = parse_icon_sys(
                            card.read_data(child["cluster"], child["length"]))
            except ValueError as e:
                # One unreadable save shouldn't hide the rest of the card.
                print(f"[VMC] Could not read save {entry['name']}: {e}")

            serial = serial_from_save_name(entry["name"])
            title = db.query_title_by_serial(serial) if serial else None

            saves.append({
                "folder": entry["name"],
                "serial": serial,
                "title": title,
                "icon_title": icon_title,
                "size": used,
                "file_count": len(files),
                "files": sorted(files, key=lambda f: f["name"].lower()),
                "modified": entry["modified"],
                "created": entry["created"],
                "cover_url": (f"{system.CONFIG.COVERS_URL}/{serial}.jpg"
                              if serial and system.CONFIG.COVERS_URL else None),
            })

    saves.sort(key=lambda s: (s["title"] or s["icon_title"] or s["folder"]).lower())
    return saves


def browse_vmc(name):
    """Save browser payload for one card."""
    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    clean = sanitize_name(name)
    path = os.path.join(vmc_dir, f"{clean}.bin")
    if not os.path.exists(path):
        return {"status": "error", "message": f"VMC '{clean}' not found."}

    info = inspect_vmc(path)
    if not info.get("valid"):
        return {"status": "error",
                "message": f"'{clean}' is not a valid memory card: {info.get('reason')}"}

    try:
        saves = list_saves(path)
    except ValueError as e:
        return {"status": "error", "message": f"Could not read '{clean}': {e}"}

    return {
        "status": "success",
        "name": clean,
        "size": info.get("size"),
        "size_mb": info.get("size_mb"),
        "free_bytes": info.get("free_bytes"),
        "saves": saves,
    }


# - - - PCSX2 BRIDGE - - -
#
# OPL writes bare 512 byte pages; PCSX2 writes 528 byte pages, the extra 16
# holding the Hamming codes a real card keeps in its spare area. The two
# formats are otherwise identical, so converting is adding or removing that
# spare area page by page.

ECC_PAGE_SIZE = ps2_ecc.PAGE_SIZE + ps2_ecc.SPARE_SIZE

FORMAT_RAW = "raw"
FORMAT_PCSX2 = "pcsx2"


def _card_geometry(header):
    """(page_count, page_size) from a superblock, or None if it isn't one."""
    if len(header) < _SUPERBLOCK.size:
        return None
    (magic, _v, page_size, pages_per_cluster, _ppb, _u, clusters_per_card,
     *_rest) = _SUPERBLOCK.unpack(header[:_SUPERBLOCK.size])
    if not magic.startswith(MAGIC[:27]):
        return None
    if page_size != ps2_ecc.PAGE_SIZE:
        return None
    return pages_per_cluster * clusters_per_card, page_size


def detect_format(path):
    """
    Work out whether a card file carries ECC, by comparing its size against
    the page count its own superblock declares.
    """
    with open(path, 'rb') as f:
        header = f.read(_SUPERBLOCK.size)

    geometry = _card_geometry(header)
    if not geometry:
        return None
    pages, page_size = geometry
    size = os.path.getsize(path)

    if size == pages * page_size:
        return FORMAT_RAW
    if size == pages * ECC_PAGE_SIZE:
        return FORMAT_PCSX2
    return None


def convert_to_pcsx2(src, dest):
    """
    Write `src` out as a PCSX2 .ps2 card, computing the ECC for every page.
    """
    written = 0
    with open(src, 'rb') as fin, open(dest, 'wb') as fout:
        while True:
            page = fin.read(ps2_ecc.PAGE_SIZE)
            if not page:
                break
            if len(page) < ps2_ecc.PAGE_SIZE:
                page += b"\x00" * (ps2_ecc.PAGE_SIZE - len(page))
            fout.write(page)
            fout.write(ps2_ecc.spare_for_page(page))
            written += 1
        fout.flush()
        os.fsync(fout.fileno())
    return written


def convert_from_pcsx2(src, dest):
    """
    Write a PCSX2 .ps2 card out as an OPL .bin, dropping the spare area.

    Each page is checked against its Hamming codes on the way through, so a
    card that picked up bit rot is either repaired or reported rather than
    silently imported.
    """
    corrected = 0
    failed = 0
    with open(src, 'rb') as fin, open(dest, 'wb') as fout:
        while True:
            raw = fin.read(ECC_PAGE_SIZE)
            if not raw:
                break
            if len(raw) < ECC_PAGE_SIZE:
                raise ValueError("Card ends in the middle of a page.")
            page, spare = raw[:ps2_ecc.PAGE_SIZE], raw[ps2_ecc.PAGE_SIZE:]
            status, page = ps2_ecc.check_page(page, spare)
            if status == ps2_ecc.ECC_CHECK_CORRECTED:
                corrected += 1
            elif status == ps2_ecc.ECC_CHECK_FAILED:
                failed += 1
            fout.write(page)
        fout.flush()
        os.fsync(fout.fileno())
    return corrected, failed


def export_vmc(name, fmt=FORMAT_RAW, workdir=None):
    """
    Resolve a card for download.

    Returns a dict with the path to serve, the filename to offer and whether
    that path is a temporary file the caller has to delete afterwards. The raw
    format serves the card in place; there is nothing to convert.
    """
    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    clean = sanitize_name(name)
    path = os.path.join(vmc_dir, f"{clean}.bin")
    if not os.path.exists(path):
        return {"status": "error", "message": f"VMC '{clean}' not found."}

    info = inspect_vmc(path)
    if not info.get("valid"):
        return {"status": "error",
                "message": f"'{clean}' is not a valid memory card: {info.get('reason')}"}

    if fmt == FORMAT_RAW:
        return {"status": "success", "path": path,
                "filename": f"{clean}.bin", "temporary": False}

    if fmt != FORMAT_PCSX2:
        return {"status": "error", "message": f"Unknown export format '{fmt}'."}

    fd, temp = tempfile.mkstemp(prefix=f"isobe-{clean}-", suffix=".ps2", dir=workdir)
    os.close(fd)
    try:
        convert_to_pcsx2(path, temp)
    except Exception as e:
        try:
            os.remove(temp)
        except OSError:
            pass
        print(f"[VMC] Failed to convert {clean} for PCSX2: {e}")
        return {"status": "error", "message": f"Conversion failed: {e}"}

    print(f"[VMC] Exported {clean} as PCSX2 .ps2")
    return {"status": "success", "path": temp,
            "filename": f"{clean}.ps2", "temporary": True}


def import_vmc(src_path, name, overwrite=False):
    """
    Bring an external card into the library as a new VMC.

    Accepts either format and always lands an OPL-compatible .bin. Refuses to
    replace an existing card unless asked to: cards hold saves, and there is no
    undo once one is overwritten.
    """
    vmc_dir = get_vmc_dir()
    if not vmc_dir:
        return {"status": "error", "message": "No storage device selected."}

    clean = sanitize_name(name)
    if not clean:
        return {"status": "error", "message": "Invalid VMC name."}

    fmt = detect_format(src_path)
    if not fmt:
        return {"status": "error",
                "message": "That file isn't a PS2 memory card, or its size "
                           "doesn't match the card it describes."}

    os.makedirs(vmc_dir, exist_ok=True)
    dest = os.path.join(vmc_dir, f"{clean}.bin")
    if os.path.exists(dest) and not overwrite:
        return {"status": "error",
                "message": f"A VMC named '{clean}' already exists."}

    # Convert beside the destination, then move into place, so an interrupted
    # import can't leave a half written card where OPL will find it.
    fd, temp = tempfile.mkstemp(prefix=f".isobe-import-{clean}-", dir=vmc_dir)
    os.close(fd)
    corrected = failed = 0
    try:
        if fmt == FORMAT_PCSX2:
            corrected, failed = convert_from_pcsx2(src_path, temp)
        else:
            shutil.copyfile(src_path, temp)

        info = inspect_vmc(temp)
        if not info.get("valid"):
            raise ValueError(info.get("reason") or "not a valid memory card")

        os.replace(temp, dest)
    except Exception as e:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass
        print(f"[VMC] Import of {clean} failed: {e}")
        return {"status": "error", "message": f"Import failed: {e}"}

    message = f"Imported {clean}"
    if fmt == FORMAT_PCSX2:
        message += " from PCSX2"
    if corrected:
        message += f" ({corrected} page(s) repaired)"
    if failed:
        message += f" — {failed} page(s) could not be verified"

    print(f"[VMC] {message}")
    return {
        "status": "success",
        "message": message,
        "source_format": fmt,
        "pages_repaired": corrected,
        "pages_failed": failed,
        "vmc": describe_vmc(dest),
    }
