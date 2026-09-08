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
import struct
import time
from array import array

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
