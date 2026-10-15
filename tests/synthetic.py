"""Builders for synthetic, PS2-like test data.

Nothing here is game data: every file is generated from scratch so the tools can be tested
without the commercial disc. Layouts follow the documented formats (see docs/FINDINGS.md):

* TERF: chunks [tag][u32 size incl. 8-byte header]; TERF header holds the entry count (u16 at +14);
  DIR1 = (offset, size) per entry, offsets relative to the start of the DATA chunk;
  COMP = (algorithm, uncompressed size) per entry.
"""
from __future__ import annotations

import hashlib
import io
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path


def u16(v: int, be: bool = False) -> bytes:
    return struct.pack(">H" if be else "<H", v)


def u32(v: int, be: bool = False) -> bytes:
    return struct.pack(">I" if be else "<I", v)


def pad_to(data: bytes, align: int) -> bytes:
    rem = len(data) % align
    return data if rem == 0 else data + b"\0" * (align - rem)


def build_terf(entries: list[bytes], algos: list[int] | None = None, xsizes: list[int] | None = None,
               align: int = 16, big_endian: bool = False) -> bytes:
    n = len(entries)
    algos = algos or [0] * n
    xsizes = xsizes or [len(e) for e in entries]
    be = big_endian
    header = b"TERF" + u32(16, be) + u32(0, be) + u16(0, be) + u16(n, be)
    data = bytearray(b"DATA" + b"\0\0\0\0")
    data = bytearray(pad_to(bytes(data), align))
    dir1 = b""
    for e in entries:
        off = len(data)
        dir1 += u32(off, be) + u32(len(e), be)
        data += e
        data = bytearray(pad_to(bytes(data), align))
    data[4:8] = u32(len(data), be)
    dir_chunk = b"DIR1" + u32(8 + 8 * n, be) + dir1
    comp_chunk = b"COMP" + u32(8 + 8 * n, be) + b"".join(u32(a, be) + u32(x, be) for a, x in zip(algos, xsizes))
    return header + dir_chunk + comp_chunk + bytes(data)


def build_tim2(width: int, height: int, colors: int = 256) -> bytes:
    image = bytes((x * 7 + y) & 0xFF for y in range(height) for x in range(width))
    clut = bytes(range(256)) * (colors * 4 // 256)
    header_size = 48
    total = header_size + len(image) + len(clut)
    pic = (u32(total) + u32(len(clut)) + u32(len(image)) + u16(header_size) + u16(colors)
           + bytes([0, 1, 0x03, 0x05]) + u16(width) + u16(height) + b"\0" * 24)
    return b"TIM2" + bytes([4, 0]) + u16(1) + b"\0" * 8 + pic + image + clut


def build_shps(images: list[tuple[str, int, int]]) -> bytes:
    count = len(images)
    dir_size = 16 + 8 * count
    blocks = b""
    directory = b""
    for name, w, h in images:
        off = dir_size + len(blocks)
        pixels = bytes((i * 13) & 0xFF for i in range(w * h))
        block = bytes([0x02]) + b"\0\0\0" + u16(w) + u16(h) + b"\0" * 8 + pixels
        directory += name.encode("ascii")[:4].ljust(4, b"\0") + u32(off)
        blocks += block
    body = directory + blocks
    return b"SHPS" + u32(16 + len(body)) + u32(count) + b"G357" + body


def build_bigf(files: list[tuple[str, bytes]]) -> bytes:
    toc_len = 16 + sum(8 + len(n) + 1 for n, _ in files)
    toc_len = (toc_len + 15) // 16 * 16
    data = b""
    toc = b""
    for name, content in files:
        off = toc_len + len(data)
        toc += struct.pack(">II", off, len(content)) + name.encode() + b"\0"
        data += pad_to(content, 16)
    header = b"BIGF" + u32(toc_len + len(data)) + struct.pack(">II", len(files), toc_len)
    return pad_to(header + toc, 16)[:toc_len].ljust(toc_len, b"\0") + data


def build_tdb_header(num_tables: int = 3) -> bytes:
    # "DB", version 8, little-endian flag, then size / table count. Header-only stub.
    return b"DB" + b"\x00\x08" + b"\x00\x00\x00\x00" + u32(0x24) + u32(0) + u32(num_tables) + u32(0) + b"\0" * 12


def fake_elf(size: int = 300_000, seed: int = 1) -> bytes:
    rnd = random.Random(seed)
    head = b"\x7fELF\x01\x01\x01" + b"\0" * 9 + u16(2) + u16(8)
    return head + bytes(rnd.getrandbits(8) for _ in range(size - len(head)))


@dataclass
class SyntheticDisc:
    files: dict[str, bytes] = field(default_factory=dict)  # ISO path ("/DATA/X.DAT") -> content

    def sha256(self) -> dict[str, str]:
        return {p: hashlib.sha256(c).hexdigest() for p, c in self.files.items()}


def make_disc() -> SyntheticDisc:
    rnd = random.Random(42)
    compressed = bytes(rnd.getrandbits(8) for _ in range(5000))
    inner = build_terf([build_shps([("pl01", 64, 64), ("pl02", 32, 32)]), b"hello inner"])
    portrait_dat = build_terf(
        [build_tim2(128, 128), compressed, inner, build_tdb_header()],
        algos=[0, 5, 0, 0], xsizes=[0, 16384, 0, 0])
    portrait_dat_fixed = portrait_dat  # keep identical reference
    big_terf = build_terf([b"x" * 100, b"y" * 200], big_endian=True)
    disc = SyntheticDisc()
    disc.files = {
        "/SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_212.13;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n",
        "/SLUS_212.13": fake_elf(),
        "/DATA/UIS_PLYR.DAT": portrait_dat_fixed,
        "/DATA/BIGEND.DAT": big_terf,
        "/DATA/ROSTER.DB": build_tdb_header() + b"\0" * 4000,
        "/DATA/ARCH.VIV": build_bigf([("a.tm2", build_tim2(16, 16)), ("b.txt", b"plain text file\n")]),
        "/DATA/LARGE.BIN": bytes(rnd.getrandbits(8) for _ in range(3 * 1024 * 1024 + 123)),
        "/MOVIES/INTRO.PSS": b"\x00\x00\x01\xba" + b"\0" * 5000,
        "/IOP/SIO2MAN.IRX": b"\x7fELF" + b"\0" * 1000,
        "/EMPTY.TXT": b"",
    }
    return disc


def write_iso(disc: SyntheticDisc, path: Path) -> None:
    import pycdlib  # test-only dependency

    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1, sys_ident="PLAYSTATION", vol_ident="MADDEN06TEST")
    made = set()
    for p in sorted(disc.files):
        parts = p.strip("/").split("/")
        for i in range(1, len(parts)):
            d = "/" + "/".join(parts[:i])
            if d not in made:
                iso.add_directory(d)
                made.add(d)
    for p, content in sorted(disc.files.items()):
        name = p if "." in p.rsplit("/", 1)[-1] else p + "."
        iso.add_fp(io.BytesIO(content), len(content), name + ";1")
    iso.write(str(path))
    iso.close()


def to_raw_2352(iso_2048: Path, out: Path, mode2: bool = False) -> None:
    """Wraps a 2048-byte-sector image into raw 2352-byte sectors (sync + header + data + zeroed EDC/ECC)."""
    data = iso_2048.read_bytes()
    sync = b"\x00" + b"\xff" * 10 + b"\x00"
    with out.open("wb") as f:
        for lba in range(len(data) // 2048):
            block = data[lba * 2048:(lba + 1) * 2048]
            if mode2:
                sector = sync + b"\0\0\0\x02" + b"\0" * 8 + block + b"\0" * 280
            else:
                sector = sync + b"\0\0\0\x01" + block + b"\0" * 288
            assert len(sector) == 2352
            f.write(sector)
