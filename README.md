# Madden NFL 06 (PS2) Player & Portrait Editor

A research project and editor for **Madden NFL 06 (USA), PlayStation 2**. It works on the game's
real file formats. Goals in priority order:

1. **Replace any player's photo with a new image** (PNG/JPEG), rebuild the ISO and see it in PCSX2.
2. **Edit historical player statistics** so in-game career history matches real NFL history.
3. Edit everything else about a player: biography, ratings, appearance, equipment, contracts.

## Status

| Phase | State |
|---|---|
| 0. ISO inspection & transfer utility | **Written, awaiting first test run.** See [docs/WINDOWS-ISO-INSPECTOR.md](docs/WINDOWS-ISO-INSPECTOR.md) |
| 1. Reverse-engineering formats | Desk research done ([docs/FINDINGS.md](docs/FINDINGS.md)); waiting for disc inventory |
| 2. Portrait extraction | Not started (needs the portrait archive sample) |
| 3. Portrait import / replacement | Not started |
| 4. Historical statistics | Not started |
| 5–6. Full editor / Windows app | Not started |
| 7. ISO rebuild | Not started |
| 8. PCSX2 verification | Not started. Requires runs on your PC |

Nothing is marked working without evidence from the real disc or from PCSX2.

## Quick start (Windows)

1. **Code → Download ZIP** on this repository page, then extract it.
2. Double-click `tools\windows\Run-Inspector.cmd`. It reads `C:\Game Files\Madden NFL 06 (USA).iso`
   **read-only** and writes results to `C:\Game Files\Madden06Research\`.
3. Send the packages from `C:\Game Files\Madden06Research\packages\` as described in
   [docs/TRANSFER-WORKFLOW.md](docs/TRANSFER-WORKFLOW.md).

## Repository layout

```
tools/windows/      Windows PowerShell utilities (no install needed)
docs/               Instructions, findings (confirmed vs hypotheses), transfer workflow
```

Planned: `src/madden06/` (Python core library: ISO9660, TERF archives, decompression, PS2 GS
textures, TDB database), `tests/`, and `app/` (desktop GUI).

## Technology choices

* **Phase 0 utility: PowerShell 5.1 with embedded C#.** It ships with every Windows 10/11 install,
  so there is nothing to install. The C# part reads the ISO9660 structures directly, which gives
  sector numbers that Windows' built-in ISO mounting hides, and is fast enough to hash 4 GB.
* **Core library: Python 3** with NumPy and Pillow. Reverse-engineering iterates quickly in Python, and
  the binary parsers, swizzling and texture encoders can be unit-tested in the cloud development
  environment without Windows.
* **Desktop app (planned): PySide6 (Qt)**, packaged into a single Windows `.exe` with PyInstaller.
  This gives a native-looking three-pane editor (roster / player card / tabbed editor) with
  drag-and-drop, built on the same tested core library.

## Ground rules

* The original ISO is never modified. Every output goes to new files.
* No game content (ISO, DAT, DB, ELF, saves, extracted assets) is ever committed. `.gitignore` enforces this.
* Unknown fields and archive metadata are preserved byte-for-byte. Parsers are round-trip tested.
* Limitations are documented, not hidden.

## Credits / prior art

aluigi (TERF QuickBMS script, Madden decompression research), bep713 / madden-file-tools (TDB
format, MIT), JDHalfrack (DAT File Replacer), George Greer (Madden DB format notes), and the
FootballIdiot, Operation Sports and NCAA NEXT communities. See [docs/FINDINGS.md](docs/FINDINGS.md).
