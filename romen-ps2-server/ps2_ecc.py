"""
Hamming codes for PS2 memory card pages.

A real PS2 memory card stores 512 bytes of data plus a 16 byte spare area per
page. The spare holds four 3 byte Hamming codes, one per 128 byte chunk, and
the remaining 4 bytes are unused. OPL's VMC files drop the spare area entirely
(512 byte pages); PCSX2's .ps2 files keep it (528 byte pages). Converting
between the two formats is therefore just adding or removing this spare.

The algorithm is ported from the public domain `ps2mc_ecc.py` by Ross Ridge
(https://github.com/ps2dev/mymc). The GPLv3 forks of mymc were deliberately not
used: this project ships under MIT.
"""

PAGE_SIZE = 512
CHUNK_SIZE = 128
SPARE_SIZE = 16
ECC_BYTES_PER_CHUNK = 3

ECC_CHECK_OK = 0
ECC_CHECK_CORRECTED = 1
ECC_CHECK_FAILED = 2


def _parity(b):
    b ^= b >> 1
    b ^= b >> 2
    b ^= b >> 4
    return b & 1


def _make_tables():
    parity_table = [_parity(b) for b in range(256)]
    # Each mask picks out one column of the 8 bit wide chunk. Index 3 is 0x00
    # because that bit of the column parity is never used.
    cpmasks = (0x55, 0x33, 0x0F, 0x00, 0xAA, 0xCC, 0xF0)
    column_parity_masks = []
    for b in range(256):
        mask = 0
        for i, cpmask in enumerate(cpmasks):
            mask |= parity_table[b & cpmask] << i
        column_parity_masks.append(mask)
    return parity_table, column_parity_masks


_PARITY_TABLE, _COLUMN_PARITY_MASKS = _make_tables()

# A freshly formatted card is overwhelmingly runs of one repeated byte, and the
# code for such a chunk only depends on that byte. Caching them turns most of
# an export into dictionary hits instead of 128 iterations each.
_uniform_cache = {}


def ecc_calculate(chunk):
    """The 3 byte Hamming code for one 128 byte chunk."""
    if chunk and chunk.count(chunk[0]) == len(chunk):
        key = (chunk[0], len(chunk))
        cached = _uniform_cache.get(key)
        if cached is None:
            cached = _ecc_calculate(chunk)
            _uniform_cache[key] = cached
        return cached
    return _ecc_calculate(chunk)


def _ecc_calculate(chunk):
    column_parity = 0x77
    line_parity_0 = 0x7F
    line_parity_1 = 0x7F
    cpm = _COLUMN_PARITY_MASKS
    par = _PARITY_TABLE
    for i, b in enumerate(chunk):
        column_parity ^= cpm[b]
        if par[b]:
            line_parity_0 ^= ~i
            line_parity_1 ^= i
    return bytes((column_parity, line_parity_0 & 0x7F, line_parity_1 & 0x7F))


def ecc_check(chunk, ecc):
    """
    Detect and correct a single bit error in one chunk.

    Returns (status, chunk, ecc) with the corrected values. Used when reading a
    PCSX2 card, where the spare area is the only evidence that a page survived
    whatever the file has been through.
    """
    computed = ecc_calculate(chunk)
    if computed == ecc:
        return ECC_CHECK_OK, chunk, ecc

    cp_diff = (computed[0] ^ ecc[0]) & 0x77
    lp0_diff = (computed[1] ^ ecc[1]) & 0x7F
    lp1_diff = (computed[2] ^ ecc[2]) & 0x7F
    lp_comp = lp0_diff ^ lp1_diff
    cp_comp = (cp_diff >> 4) ^ (cp_diff & 0x07)

    if lp_comp == 0x7F and cp_comp == 0x07:
        # One bit in the data is wrong, and the codes say exactly which.
        fixed = bytearray(chunk)
        fixed[lp1_diff] ^= 1 << (cp_diff >> 4)
        return ECC_CHECK_CORRECTED, bytes(fixed), ecc

    if (cp_diff == 0 and lp0_diff == 0 and lp1_diff == 0) or \
            (bin(lp_comp).count('1') + bin(cp_comp).count('1')) == 1:
        # The data is fine; the stored code itself was corrupted.
        return ECC_CHECK_CORRECTED, chunk, computed

    return ECC_CHECK_FAILED, chunk, ecc


def spare_for_page(page):
    """
    The 16 byte spare area for a 512 byte page: four Hamming codes followed by
    four unused bytes, which real cards leave zeroed.
    """
    ecc = bytearray()
    for i in range(0, len(page), CHUNK_SIZE):
        ecc += ecc_calculate(page[i:i + CHUNK_SIZE])
    return bytes(ecc) + b"\x00" * (SPARE_SIZE - len(ecc))


def check_page(page, spare):
    """
    Verify a page against its spare area.

    Returns (status, page). A page whose spare is entirely zero is treated as
    unchecked rather than corrupt: some tools write cards without ever
    computing the codes, and refusing to import those would be unhelpful.
    """
    if not any(spare[:ECC_BYTES_PER_CHUNK * (len(page) // CHUNK_SIZE)]):
        return ECC_CHECK_OK, page

    result = ECC_CHECK_OK
    out = bytearray()
    for i in range(len(page) // CHUNK_SIZE):
        chunk = page[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        ecc = spare[i * ECC_BYTES_PER_CHUNK:(i + 1) * ECC_BYTES_PER_CHUNK]
        status, chunk, _ = ecc_check(chunk, ecc)
        if status == ECC_CHECK_FAILED:
            result = ECC_CHECK_FAILED
        elif status == ECC_CHECK_CORRECTED and result == ECC_CHECK_OK:
            result = ECC_CHECK_CORRECTED
        out += chunk
    return result, bytes(out)
