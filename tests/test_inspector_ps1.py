"""End-to-end tests of tools/windows/Inspect-MaddenIso.ps1 against synthetic discs.

Requires PowerShell (pwsh) and pycdlib; skipped otherwise.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from synthetic import make_disc, to_raw_2352, write_iso

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "windows" / "Inspect-MaddenIso.ps1"
PWSH = shutil.which("pwsh") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell not installed")
pycdlib = pytest.importorskip("pycdlib")


def run_inspector(iso: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    cmd = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
           "-IsoPath", str(iso), "-OutputRoot", str(out), "-Offline", *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise AssertionError(f"inspector failed ({proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def disc():
    return make_disc()


@pytest.fixture(scope="module")
def iso2048(tmp_path_factory, disc):
    path = tmp_path_factory.mktemp("iso") / "Madden Test (USA).iso"
    write_iso(disc, path)
    return path


@pytest.fixture(scope="module")
def result(tmp_path_factory, iso2048):
    out = tmp_path_factory.mktemp("research")
    before = (iso2048.stat().st_size, iso2048.stat().st_mtime_ns, hashlib.sha256(iso2048.read_bytes()).hexdigest())
    proc = run_inspector(iso2048, out, "-Extract", "UIS_*.DAT,/DATA/ARCH.VIV", "-HashIso")
    after = (iso2048.stat().st_size, iso2048.stat().st_mtime_ns, hashlib.sha256(iso2048.read_bytes()).hexdigest())
    return {"out": out, "proc": proc, "before": before, "after": after}


def test_iso_untouched(result):
    assert result["before"] == result["after"]
    assert "OK - size and last-modified time are identical" in result["proc"].stdout


def test_inventory_lists_every_file_with_correct_hash(result, disc):
    rows = {r["Path"]: r for r in read_csv(result["out"] / "inventory" / "files.csv")}
    assert set(rows) == set(disc.files)
    for path, digest in disc.sha256().items():
        assert rows[path]["Sha256"] == digest, path
        assert int(rows[path]["Size"]) == len(disc.files[path])


def test_formats_detected(result):
    rows = {r["Path"]: r for r in read_csv(result["out"] / "inventory" / "files.csv")}
    assert rows["/DATA/UIS_PLYR.DAT"]["Format"] == "TERF"
    assert rows["/DATA/BIGEND.DAT"]["Format"] == "TERF"
    assert rows["/DATA/ROSTER.DB"]["Format"] == "TDB"
    assert rows["/DATA/ARCH.VIV"]["Format"] == "BIGF"
    assert rows["/MOVIES/INTRO.PSS"]["Format"] == "MPEG-PS"
    assert rows["/IOP/SIO2MAN.IRX"]["Format"] == "IRX"
    assert rows["/SLUS_212.13"]["Format"] == "ELF"
    assert rows["/SYSTEM.CNF"]["Format"] == "text"
    assert rows["/EMPTY.TXT"]["Format"] == "empty"
    assert "portrait" in rows["/DATA/UIS_PLYR.DAT"]["Hints"]


def test_terf_and_nested_entries(result):
    entries = read_csv(result["out"] / "inventory" / "archive_entries.csv")
    top = [e for e in entries if e["Container"] == "/DATA/UIS_PLYR.DAT"]
    assert [int(e["Algorithm"]) for e in top] == [0, 5, 0, 0]
    assert [e["Tag"] for e in top] == ["TIM2", "unknown", "TERF", "TDB"]
    assert int(top[1]["UncompressedSize"]) == 16384
    nested = [e for e in entries if e["Container"] == "/DATA/UIS_PLYR.DAT#0002"]
    assert [e["Tag"] for e in nested] == ["SHPS", "text"]
    assert all(e["Problem"] == "" for e in entries)
    be = [e for e in entries if e["Container"] == "/DATA/BIGEND.DAT"]
    assert [e["Format"] for e in be] == ["TERF-BE", "TERF-BE"]
    assert [int(e["StoredSize"]) for e in be] == [100, 200]
    big = [e for e in entries if e["Container"] == "/DATA/ARCH.VIV"]
    assert [e["Name"] for e in big] == ["a.tm2", "b.txt"]


def test_textures_listed(result):
    tex = read_csv(result["out"] / "inventory" / "textures.csv")
    dims = {(t["Container"], t["Name"], int(t["Width"]), int(t["Height"])) for t in tex}
    assert ("SHPS", "pl01", 64, 64) in dims
    assert ("SHPS", "pl02", 32, 32) in dims
    assert ("TIM2", "", 128, 128) in dims
    assert ("TIM2", "", 16, 16) in dims


def test_extraction_is_byte_exact(result, disc):
    out = result["out"] / "extracted"
    for p in ["/SYSTEM.CNF", "/SLUS_212.13", "/DATA/UIS_PLYR.DAT", "/DATA/ARCH.VIV"]:
        assert (out / p.strip("/")).read_bytes() == disc.files[p], p
    assert not (out / "DATA" / "ROSTER.DB").exists()


def test_heads_and_disc_json(result, disc):
    head = result["out"] / "samples" / "heads" / "DATA" / "LARGE.BIN.head"
    assert head.read_bytes() == disc.files["/DATA/LARGE.BIN"][:4096]
    info = json.loads((result["out"] / "inventory" / "disc.json").read_text(encoding="utf-8-sig"))
    assert info["bootFile"] == "/SLUS_212.13"
    assert info["volumeId"] == "MADDEN06TEST"
    assert info["fileCount"] == len(disc.files)
    assert len(info["isoSha256"]) == 64


def test_lba_map_consistent(result):
    rows = read_csv(result["out"] / "inventory" / "lba_map.csv")
    files = [r for r in rows if r["Kind"] == "file" and int(r["Size"]) > 0]
    files.sort(key=lambda r: int(r["Lba"]))
    for a, b in zip(files, files[1:]):
        assert int(a["EndLba"]) <= int(b["Lba"]), (a["Path"], b["Path"])


def test_packages_and_manifest(result):
    pk = result["out"] / "packages"
    manifest = json.loads((pk / "drop-001.manifest.json").read_text(encoding="utf-8-sig"))
    names = {p["file"]: p for p in manifest["packages"]}
    assert set(names) == {"drop-001-metadata.zip", "drop-001-gamedata.zip"}
    for name, info in names.items():
        data = (pk / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == info["sha256"]
    meta = zipfile.ZipFile(pk / "drop-001-metadata.zip").namelist()
    assert "inventory/files.csv" in meta and "reports/research_report.md" in meta
    assert not any(n.startswith(("extracted/", "samples/")) for n in meta)
    game = zipfile.ZipFile(pk / "drop-001-gamedata.zip").namelist()
    assert "extracted/DATA/UIS_PLYR.DAT" in game
    assert "samples/heads/SLUS_212.13.head" in game


def test_report_mentions_key_sections(result):
    report = (result["out"] / "reports" / "research_report.md").read_text(encoding="utf-8-sig")
    for heading in ["## Disc", "## Totals", "## Candidate files", "## Archive contents", "## Disc layout", "## Integrity"]:
        assert heading in report
    assert "BOOT2 = cdrom0:\\SLUS_212.13;1" in report


@pytest.mark.parametrize("mode2", [False, True])
def test_raw_2352_images(tmp_path, iso2048, disc, mode2):
    raw = tmp_path / "disc.bin"
    to_raw_2352(iso2048, raw, mode2=mode2)
    out = tmp_path / "out"
    run_inspector(raw, out, "-NoPackage", "-HeadBytes", "0")
    rows = {r["Path"]: r for r in read_csv(out / "inventory" / "files.csv")}
    for path, digest in disc.sha256().items():
        assert rows[path]["Sha256"] == digest, path
    assert (out / "extracted" / "SLUS_212.13").read_bytes() == disc.files["/SLUS_212.13"]


def test_second_run_increments_drop(tmp_path, iso2048):
    out = tmp_path / "out"
    run_inspector(iso2048, out, "-SkipHashes", "-HeadBytes", "16")
    run_inspector(iso2048, out, "-SkipHashes", "-HeadBytes", "16", "-Extract", "ROSTER.DB")
    pk = out / "packages"
    assert (pk / "drop-001.manifest.json").exists()
    assert (pk / "drop-002.manifest.json").exists()
    game = zipfile.ZipFile(pk / "drop-002-gamedata.zip").namelist()
    assert "extracted/DATA/ROSTER.DB" in game


def test_missing_iso_fails_cleanly(tmp_path):
    cmd = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
           "-IsoPath", str(tmp_path / "nope.iso"), "-OutputRoot", str(tmp_path / "o"), "-Offline"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "was not found" in proc.stdout
