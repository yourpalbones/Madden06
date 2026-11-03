"""Build SYNTHETIC TERF/TDB bytes in the layout game_formats.Terf/Database/Table read.

Used only to test the export tool against the editor's real reader. Contains no
game data. Layout (as read by Madden06Editor game_formats):

TERF: b'TERF', u32 directory @4, u16 member count @14; DIR1 @directory with u32
length and (u32 relative, u32 size) per member; DATA chunk whose u32 size runs to EOF.
DB:   b'DB\\x00\\x08', u32 total length @8, u32 table count @16, (tag, u32 rel) at 24+8i.
Table: u32 record_size @8, <HH capacity,count @20, u32 field count @28, 16-byte
field defs <II4sI (kind, bit, tag, width) @40; records follow. kind 0 = string, 3 = unsigned.
"""

from __future__ import annotations

import struct


def _table(fields: list[tuple[str, int, int]], records: list[dict]) -> bytes:
    """fields: (tag, kind, width_bits). Fields are packed in order from bit 0."""
    defs, bit = [], 0
    for tag, kind, width in fields:
        if kind == 0:  # the editor's reader requires byte-aligned strings
            bit = (bit + 7) // 8 * 8
        defs.append((kind, bit, tag.encode("ascii"), width))
        bit += width
    record_size = (bit + 7) // 8
    head = bytearray(40)
    struct.pack_into("<I", head, 8, record_size)
    struct.pack_into("<HH", head, 20, len(records), len(records))
    struct.pack_into("<I", head, 28, len(defs))
    body = bytearray(head)
    for kind, b, tag, width in defs:
        body += struct.pack("<II4sI", kind, b, tag, width)
    for rec in records:
        packed = 0
        for kind, b, tag, width in defs:
            v = rec[tag.decode()]
            if kind == 0:
                raw = v.encode("ascii")[: width // 8].ljust(width // 8, b"\x00")
                v = int.from_bytes(raw, "little")
            packed |= (v & ((1 << width) - 1)) << b
        body += packed.to_bytes(record_size, "little")
    return bytes(body)


def database(tables: dict[str, bytes]) -> bytes:
    count = len(tables)
    base = 24 + 8 * count
    directory, blobs, rel = bytearray(), bytearray(), 0
    for tag, blob in tables.items():
        directory += tag.encode("ascii") + struct.pack("<I", rel)
        blobs += blob
        rel += len(blob)
    head = bytearray(24)
    head[0:4] = b"DB\x00\x08"
    struct.pack_into("<I", head, 16, count)
    data = bytearray(head + directory + blobs)
    struct.pack_into("<I", data, 8, len(data))
    return bytes(data)


def terf(members: list[bytes]) -> bytes:
    directory = 16
    dir_len = 8 + 8 * len(members)
    head = bytearray(16)
    head[0:4] = b"TERF"
    struct.pack_into("<I", head, 4, directory)
    struct.pack_into("<H", head, 14, len(members))
    dir1 = bytearray(b"DIR1" + struct.pack("<I", dir_len))
    rel = 8
    for m in members:
        dir1 += struct.pack("<II", rel, len(m))
        rel += len(m)
    data_chunk = b"DATA" + struct.pack("<I", 8 + sum(len(m) for m in members)) + b"".join(members)
    return bytes(head + dir1 + data_chunk)


RATING_TAGS = ("PSPD", "PACC", "PSTR", "PAGI", "PAWR", "PTHP", "PTHA", "PCTH", "PTAK", "PCAR", "PJMP",
               "PBTK", "PPBK", "PRBK", "PKPR", "PKAC", "PKRT", "PIMP", "PSTA", "PINJ", "PTGH")


def template_dat(players: list[dict], teams: list[dict]) -> bytes:
    play_fields = [("PFNA", 0, 96), ("PLNA", 0, 128), ("PGID", 3, 13), ("TGID", 3, 10), ("PPOS", 3, 5),
                   ("POVR", 3, 7), ("PJEN", 3, 7), ("PWGT", 3, 8)] + [(t, 3, 7) for t in RATING_TAGS]
    team_fields = [("TGID", 3, 10), ("TLNA", 0, 96), ("TDNA", 0, 96)]
    member1 = database({"PLAY": _table(play_fields, players), "TEAM": _table(team_fields, teams)})
    member0 = database({"MISC": _table([("XXXX", 3, 8)], [{"XXXX": 1}])})
    return terf([member0, member1])
