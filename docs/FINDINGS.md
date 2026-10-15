# Madden NFL 06 (PS2): technical findings

Each statement has an evidence level. Nothing moves up a level without evidence from the
actual disc or from the running game.

| Level | Meaning |
|---|---|
| **Verified (disc)** | Observed in the user's Madden NFL 06 (USA) PS2 image |
| **Verified (game)** | Observed in the game running in PCSX2 |
| **Documented** | Stated by an existing tool's source code or a detailed community write-up, usually for a *different* Madden version or platform |
| **Hypothesis** | Plausible, untested |

_Last updated: 2026-10-15 (Phase 0, before any disc data was available)._

## 1. Disc and boot

| Finding | Level | Source |
|---|---|---|
| USA serial is **SLUS-21213** (not 21216) | Documented | Internet Archive box scans "Madden NFL 06 [SLUS 21213]"; CDRomance listing |
| PS2 file names are shortened compared with the PC release (e.g. the PC file `UIS_LIB_PLAYER_PORT.dat` does not exist under that name on PS2) | Documented | FootballIdiot "Madden PS2 modding thread" |
| The disc is ISO9660 (possibly with a UDF bridge) and `SYSTEM.CNF` names the boot ELF | Hypothesis (standard for PS2 DVDs) | The inspector reports this |

## 2. Archive container: EA "TERF" `.DAT` files

| Finding | Level | Source |
|---|---|---|
| Madden `.DAT` files are EA archives officially called **TERF** | Documented | Antdroid Interactive / NCAA NEXT guides |
| Layout: chunks of `[4-char tag][u32 size incl. 8-byte header]`: `TERF` (header; file count = u16 at +14), `DIR1` (per entry: u32 offset, u32 size), `COMP` (per entry: u32 algorithm, u32 uncompressed size), `DATA` (entry offsets are relative to the start of the `DATA` chunk). Endianness is guessed from the first size field | Documented | aluigi, `madden_terf.bms` v0.1.3 (written for Madden PC `UIS_GRP_ALL.dat`) |
| `COMP` algorithm 0 = stored, 1 = QuickBMS `TDCB_silence`, 5 = EA Madden custom compression | Documented (PC) | `madden_terf.bms`; aluigi `ea_madden.c` |
| The algorithm-5 decompressor is only publicly available as **dumped x86 machine code** from the PC executable (`mainapp.exe+45D390`), working in 0x8000-byte blocks. No clean-room specification exists | Documented (PC) | aluigi `ea_madden.c`; ZenHAX thread t=7172 |
| DATs nest: e.g. `UIS_GRP_ALL.dat` holds 30 inner archives, which hold mostly compressed files | Documented (Madden 08 PC) | ZenHAX thread t=7172 |
| The DAT File Replacer (DFR, JDHalfrack) reads and writes TERF. When importing into a compressed archive, the entry must be flagged compressed and given the exact original decompressed size | Documented | FootballIdiot DFR threads |
| PS2 DATs use the same TERF layout and the same compression algorithms as PC | **Hypothesis**, the first thing the inventory will test | |

## 3. Player portraits

| Finding | Level | Source |
|---|---|---|
| On PC (Madden 08), portraits live in `UIS_LIB_PLAYER_PORT.dat` and are replaced per slot with DFR | Documented (PC) | FootballIdiot portrait guides |
| DFR **cannot add** new portrait entries. Getting higher portrait IDs to load required editing template defaults | Documented (PC) | FootballIdiot "Adding more player portraits" (t=15397) |
| On PS2 the portrait archive has a shortened name. `UIS_PLYR.DAT` was suggested on a forum, but that was a guess | Hypothesis | FootballIdiot t=16566 |
| PS2 Madden textures do not open in PC tools. "Some are swizzled and some aren't" | Documented (anecdotal) | FootballIdiot t=16566 |
| No public tool or guide replaces PS2 Madden portraits in the game files. The community uses PCSX2 texture replacement instead | Documented | FootballIdiot / NCAA NEXT threads |
| PS2 portraits are native GS textures (likely 8-bit or 4-bit indexed with a CLUT palette), possibly in EA SSH (`SHPS`) or a Tiburon-specific wrapper | **Hypothesis** | Typical for EA PS2 titles; to be tested on samples |
| Each player record carries a portrait ID that indexes the portrait archive | Hypothesis (true on PC) | |

> **PCSX2 texture replacement** changes what the *emulator* draws. It does not change the game files
> or the ISO. It is not the goal of this project. It may still be useful as a diagnostic, for example
> to confirm which texture the game is drawing.

## 4. Rosters, ratings and statistics: TDB databases

| Finding | Level | Source |
|---|---|---|
| Rosters and franchises use EA's **TDB** format: header `"DB"`, version, endian flag at +4, table count, then tables with 4-character names and bit-packed field definitions (type, bit offset, name, bit width) | Documented | bep713/madden-file-tools `TDBParser.js` (MIT); George Greer's Madden 2003-2004 file-format notes |
| `PLAY` is the player table | Documented | FootballIdiot / Operation Sports roster guides |
| PS2 Madden saves carry 2 extra header bytes that older PC editors don't expect | Documented (anecdotal) | FootballIdiot t=16566 |
| Madden 06 PS2 has a `template.dat` on the disc, edited with DFR for template changes | Documented | FootballIdiot "Need help modding PS2 rosters and franchise" |
| The default roster (and any career-history tables) are a TDB inside a disc DAT, possibly compressed | Hypothesis | |
| Which tables hold prior-season and career statistics, and whether the history screens read them | Open question | Phase 4 |

## 5. ISO rebuilding

| Finding | Level | Source |
|---|---|---|
| Community workflow: replace files with DFR, then rebuild the ISO with ImgBurn | Documented | FootballIdiot |
| Whether the game finds files by name (ISO9660 directory) or by hard-coded sector numbers | Open question | Decides whether files may move. The inventory's `lba_map.csv` and the boot ELF answer this |
| Safest strategy: patch files **in place** when the new data fits in the original sectors, and only update the directory record's size | Plan | Phase 7 |

## Open questions, in priority order

1. Which DAT(s) hold the player portraits, and what is the inner image format (dimensions, bit depth, palette, swizzle)?
2. Which compression algorithm IDs appear in the PS2 DATs, and can each be decompressed **and recompressed**? Storing an entry with algorithm 0 is a possible fallback if the game accepts it.
3. How is a player's portrait ID stored, and how does it map to an archive entry?
4. Does the game locate files by name or by sector number?
5. Where are career and season statistics stored, and which of them do the in-game history screens show?

## Sources

* aluigi, *Madden NFL TERF* QuickBMS script: https://aluigi.altervista.org/bms/madden_terf.bms
* aluigi, *EA Madden decompression*: https://aluigi.altervista.org/papers/ea_madden.c
* ZenHAX, "Need help with figuring out decompression algorithm for Madden NFL 08 dats": https://www.zenhax.com/viewtopic.php@t=7172.html
* FootballIdiot, "Madden PS2 modding thread": https://www.footballidiot.com/forum/viewtopic.php?t=16566
* FootballIdiot, "Adding more player portraits": https://www.footballidiot.com/forum/viewtopic.php?t=15397
* FootballIdiot, "Madden DAT File Replacer (DFR) 5.0": http://www.footballidiot.com/forum/viewtopic.php?t=14663
* FootballIdiot, "Need Help Modding PS2 Rosters and Franchise for Madden": https://footballidiot.com/forum/viewtopic.php?p=154516
* bep713, madden-file-tools (MIT): https://github.com/bep713/madden-file-tools
* George Greer, Madden NFL 2003-2004 database file format: http://www.m-l.org/~greerga/madden/file-format.html
* Antdroid Interactive modding guides: https://www.antdroid.dev/p/guides.html
* Internet Archive, Madden NFL 06 [SLUS 21213] box scans: https://archive.org/details/madden-nfl-06-ps2-hiresscans
* Operation Sports, "Madden 06 NEXT - Updated PS2 Mod for PCSX2/AetherSX2": https://forums.operationsports.com/forums/forum/football/madden-nfl-football/madden-nfl-old-gen/924806-madden-06-next-updated-ps2-mod-for-pcsx2-aethersx2
