"""Read-only export of the Madden 06 active roster (TEMPLATE.DAT member 1, PLAY table).

Uses the existing editor modules -- game_formats.load_players and iso9660.Disc --
so the export reads records exactly the way the verified editor does. Nothing is
written except the new output file(s), which must not already exist.

Run from the Madden 06 editor source folder (or pass --editor-src):

  python tools/export_m06_play_table.py --iso "D:\\Madden 06\\Madden NFL 06 (USA).iso" ^
      --out local_data\\m06_play_member1.json --csv local_data\\m06_play_member1.csv

or with a TEMPLATE.DAT extracted by the editor's ISO explorer:

  python tools/export_m06_play_table.py --template-dat TEMPLATE.DAT --out local_data\\m06_play_member1.json

The output contains EA game data. Keep it local (local_data/ is git-ignored).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

TEMPLATE_PATH = "/DATA/TEMPLATE.DAT"
ACTIVE_MEMBER = 1  # "Active default roster; member 1 (verified in PCSX2)" per the editor


def _import_editor(editor_src: Path):
    if not any((editor_src / f"game_formats.{ext}").exists() for ext in ("py", "pyc")):
        raise SystemExit(f"game_formats.py not found in {editor_src}; pass --editor-src <Madden 06 editor source>")
    sys.path.insert(0, str(editor_src))
    import game_formats  # noqa: E402  (the user's verified module)
    return game_formats


def _read_template_from_iso(editor_src: Path, iso: Path, verify_hash: bool) -> tuple[bytes, dict]:
    import iso9660  # noqa: E402
    info: dict = {"iso": iso.name}
    if verify_hash:
        import iso_mod  # noqa: E402
        digest = iso_mod.file_hash(iso)
        info["iso_sha256"] = digest
        info["iso_is_verified_original"] = digest == iso_mod.SOURCE_SHA256
    disc = iso9660.Disc(iso)
    entry = next((e for e in disc.entries if getattr(e, "path", "").upper() == TEMPLATE_PATH), None)
    if entry is None:
        raise SystemExit(f"{TEMPLATE_PATH} not found on disc")
    return disc.read(entry.offset, entry.size), info


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--editor-src", default=".", help="folder containing game_formats.py (default: current)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--iso", help="Madden NFL 06 USA ISO (opened read-only)")
    src.add_argument("--template-dat", help="TEMPLATE.DAT extracted with the editor")
    ap.add_argument("--verify-iso-hash", action="store_true", help="hash the full ISO against the verified original")
    ap.add_argument("--out", required=True, help="new JSON file")
    ap.add_argument("--csv", help="optional new CSV file")
    args = ap.parse_args(argv)

    editor_src = Path(args.editor_src).resolve()
    game_formats = _import_editor(editor_src)
    outputs = [Path(args.out)] + ([Path(args.csv)] if args.csv else [])
    for o in outputs:
        if o.exists():
            raise SystemExit(f"Refusing to overwrite existing {o}")

    if args.iso:
        data, source = _read_template_from_iso(editor_src, Path(args.iso), args.verify_iso_hash)
    else:
        p = Path(args.template_dat)
        data, source = p.read_bytes(), {"template_dat": p.name}
    source["template_sha256"] = hashlib.sha256(data).hexdigest()
    source["template_bytes"] = len(data)

    players = game_formats.load_players(data, {ACTIVE_MEMBER})
    bad = [p for p in players if p.get("_member") != ACTIVE_MEMBER]
    if bad:
        raise SystemExit(f"load_players returned {len(bad)} records outside member {ACTIVE_MEMBER}")
    rows = [{k: _jsonable(v) for k, v in p.items()} for p in players]
    payload = {
        "format": "m06_play_export/1",
        "source": source,
        "member": ACTIVE_MEMBER,
        "reader": "game_formats.load_players (Madden06Editor)",
        "record_count": len(rows),
        "players": rows,
    }
    for o in outputs:
        o.parent.mkdir(parents=True, exist_ok=True)
    with Path(args.out).open("x", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    if args.csv:
        keys = sorted({k for r in rows for k in r})
        front = [k for k in ("_member", "_row", "PGID", "TGID", "_team", "PFNA", "PLNA", "PPOS", "POVR") if k in keys]
        cols = front + [k for k in keys if k not in front]
        with Path(args.csv).open("x", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, cols, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()})
    print(f"Exported {len(rows)} member-{ACTIVE_MEMBER} PLAY records; TEMPLATE.DAT sha256 {source['template_sha256']}")
    if "iso_is_verified_original" in source:
        print(f"ISO matches verified original: {source['iso_is_verified_original']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
