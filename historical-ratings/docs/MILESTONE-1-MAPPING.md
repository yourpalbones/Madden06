# Milestone 1 — research and mapping

Status as of 2026-11-03. "Verified" means checked against a primary artifact
named here. Anything else is labelled as a convention, hypothesis or unknown.

## 1. What was inspected

| Source | What it contains | Relevance |
|---|---|---|
| `yourpalbones/Madden-06-Editor` (GitHub) | README + `Madden06Editor-v0.1.0-alpha-windows-x64.zip` only | Python source is **not** in the repo; it lives in the local `D:\Madden 06` project |
| Release ZIP → `Madden06Editor.exe` (PyInstaller, Python 3.12) | 17 app modules as bytecode: `editing`, `game_formats`, `iso_mod`, `roster_session`, `resource_viewer`, … | Field tables, write guards and reader layout were read from this bytecode |
| `yourpalbones/Madden06` (GitHub) | Phase-0 ISO inspector, `docs/FINDINGS.md` desk research | Older; superseded by the editor |
| Both repos, full text search | No Madden '95 data of any kind | **The Madden '95 source must come from you** |

## 2. Madden 06 target fields — verified

Source of truth: `editing.RATING_FIELDS == editing.VERIFIED_RATING_FIELDS` in the
shipped editor. `patch_player` rejects any rating field whose width is not 7 bits
and any value outside 0–99. RELEASE_VALIDATION.md records the 21 labels compared
against game screens in PCSX2 and a speed edit (58→59) observed in-game.

| Tag | Label | Bits | Range | Tag | Label | Bits | Range |
|---|---|---|---|---|---|---|---|
| PSPD | Speed | 7 | 0–99 | PJMP | Jumping | 7 | 0–99 |
| PACC | Acceleration | 7 | 0–99 | PBTK | Break tackle | 7 | 0–99 |
| PSTR | Strength | 7 | 0–99 | PPBK | Pass blocking | 7 | 0–99 |
| PAGI | Agility | 7 | 0–99 | PRBK | Run blocking | 7 | 0–99 |
| PAWR | Awareness | 7 | 0–99 | PKPR | Kick power | 7 | 0–99 |
| PTHP | Throw power | 7 | 0–99 | PKAC | Kick accuracy | 7 | 0–99 |
| PTHA | Throw accuracy | 7 | 0–99 | PKRT | Kick return | 7 | 0–99 |
| PCTH | Catching | 7 | 0–99 | PIMP | Importance | 7 | 0–99 |
| PTAK | Tackling | 7 | 0–99 | PSTA | Stamina | 7 | 0–99 |
| PCAR | Carrying | 7 | 0–99 | PINJ | Injury | 7 | 0–99 |
| | | | | PTGH | Toughness | 7 | 0–99 |

Other facts read from the editor:

* **Where:** `/DATA/TEMPLATE.DAT` is a TERF archive. Member **1** holds the active
  default roster ("verified in PCSX2"), a TDB (`DB\0\x08`) with tables `PLAY` and
  `TEAM`. Other members/alternate rosters did not change the observed default roster.
* **Reader:** `game_formats.load_players(data, member_indices)` returns PLAY rows
  plus `_member`, `_row`, `_offset`, `_team` (= `TLNA + " " + TDNA` from TEAM, empty
  if the TGID has no TEAM row).
* **Writer:** `editing.patch_player(archive_data, member_index, row, tag, value)`:
  copy-only, recomputes EA CRCs, verifies byte-level round trip. `iso_mod.build_iso`
  accepts only DB_TEAMS.DAT, TEMPLATE.DAT member 1 and UIS_PLYR.DAT, refuses to
  overwrite, requires the hash-verified original (SHA-256 `b5480cc1…690d`) as source.
* **Overall (`POVR`):** read and displayed, **never recalculated** by the editor.
  Whether the *game* recalculates it is unknown (see §6).
* **Position (`PPOS`):** the editor shows only the raw number. The usual TDB
  convention (0 QB, 1 HB, 2 FB, 3 WR, 4 TE, 5–9 LT/LG/C/RG/RT, 10 LE, 11 RE, 12 DT,
  13 LOLB, 14 MLB, 15 ROLB, 16 CB, 17 FS, 18 SS, 19 K, 20 P) is **not verified** for
  this disc. The baseline builder tests it against the real roster (QBs have the
  highest median throw power, K/P the highest kick power, linemen the highest pass
  blocking, etc.) and refuses to proceed if the data disagree.
* **Existing exports:** per-player "Export selected record JSON", ISO manifest JSON
  and `.changes.json` sidecars. There is **no bulk roster export**, so
  `tools/export_m06_play_table.py` was added (read-only, calls `load_players`).
* Any other PLAY fields are outside the verified set; the converter never writes them.

## 3. Madden '95 source — what is known

**We do not yet have the source data.** Nothing in the repositories contains it.
Until it is supplied, no Madden '95 field meaning is treated as verified.

| Question | Finding | Status |
|---|---|---|
| Platform | Genesis Madden '95 carried the NFLPA licence (real player names); SNES had team licensing only, so players are identified by number/position. A source with "Warren Moon" by name is therefore Genesis, or a third-party transcription. | Documented (Wikipedia, retail/review sources); **your file must confirm** |
| Rating storage | Adjacent Genesis/SNES titles (Madden '93/'94) store ratings as 0–15 values; an editor for them converts 0–99 ↔ 0–15 and uses depth-chart slots (QB1, LILB, LCB2, KR, PR…). | Documented for '93/'94 only (Goldglv editor). **Not verified for '95** |
| Rating scale | Third-party archive says Madden 92–95 printed ratings on a 1–15 scale. | Unverified claim |
| Attribute list | Not established by any accessible primary source. Classic Madden reused rating slots per position, so a column may mean different things for a QB and a guard. | **Unknown** |
| Warren Moon 7 / 4 / 13 / 12 | Four values, field names not visible. | **Not interpreted.** We need the screen labels or a second screen |
| Roster basis | Madden '95 shipped in 1994 for the 1994 season. Whether a given file is the shipped preseason roster or an updated one must be tested with the markers below. | To verify against your file |

### Roster-season markers (check these players' teams in the source)

| Marker | Shipped 1994 preseason roster would show | A later/updated roster might show |
|---|---|---|
| Warren Moon | Minnesota (traded from Houston, April 1994) | — (Houston ⇒ a 1993-basis roster) |
| Deion Sanders | Atlanta | San Francisco (signed September 1994) |
| Cardinals | **Arizona** Cardinals (renamed for 1994) | "Phoenix" ⇒ 1993 naming |
| Rams, Raiders | Los Angeles (both moved in 1995) | St. Louis / Oakland ⇒ 1995 data |
| League size | 28 teams, no Jacksonville/Carolina | 30 teams ⇒ 1995+ |

### nfldraftbuzz.com archive (reference only)

* The site **blocks automated access** (HTTP 403), so its tables could not be read
  directly. These points come from its own published methodology, via search results.
* Its 0–99 values for 1–15-era games are a **linear conversion** (≈6.6 per point,
  i.e. 99/15) of the printed value, not reconstructed attributes.
* Its `OVR*` for those years is its own calculation: the average of the player's
  two best ratings. EA published no overall in those games.
* Its year labels are offset ("1995" = Madden '95 = 1994 season). Blank cells mean
  EA did not publish that rating. Its own pages acknowledge scraping errors
  (e.g. a tight end's card shown as 22).
* **Use:** cross-check our extracted 1–15 values and attribute names. Do **not** use
  its 0–99 numbers or OVR* as Madden 06 ratings. To use it, save the relevant pages
  (Madden '95 team pages / position lists) from a browser and add them to `local_data/`.

## 4. Source → target mapping (per Madden 06 tag)

No Madden '95 column is mapped yet. The schema file declares mappings **per source
position**, each with `verified` + `evidence`; unverified mappings are ignored unless
`--allow-unverified-fields` is passed, and then are labelled `source_unverified`.

| Madden 06 tag | Expected method | Direct only if the verified '95 schema has… |
|---|---|---|
| PSPD, PAGI, PSTR | source_direct *if present*, else position_distribution | a speed / agility / strength rating for that position |
| PTHP, PTHA | source_direct *if present* (QB) | arm-strength / accuracy ratings |
| PCTH, PCAR, PBTK | source_direct *if present* | hands / ball-security / power-running ratings |
| PPBK, PRBK | source_direct *if present* (OL/TE/FB) | blocking rating(s); a single "blocking" field → primary on one, supporting on the other |
| PTAK | source_direct *if present* (defense) | tackling rating |
| PKPR, PKAC | source_direct *if present* (K/P) | kick power / accuracy |
| PAWR | likely estimated | an intelligence/awareness-type rating |
| PACC, PJMP | likely estimated (correlated with speed/agility in the Madden 06 data) | explicit acceleration/jumping fields |
| PKRT | estimated; returner slot + cited evidence can raise it | a KR/PR rating |
| PIMP, PSTA, PINJ, PTGH | **always estimated** from Madden 06 distributions | (no '95 counterpart expected) |

## 5. Conversion method (implemented)

See `historical_ratings/convert.py` (module docstring) and README. In short:
percentile within 1994 position peers → Madden 06 quantile for the same tag and
position among a comparable depth population; tier from an Overall-importance-weighted
composite; missing tags from Madden 06 rating-vs-POVR trends conditioned on the
player's direct ratings via the real roster's residual covariance; then archetype
priors, cited evidence and reviewed overrides. Every value records method,
confidence (0–1 and high/medium/low) and basis. No constant multiplier is used.

## 6. Overall rating

* `baseline` fits, per position group, a linear model of stored `POVR` on the 21
  ratings across the real roster and reports R², max error, the share reproduced
  exactly and whether rounding or truncation fits better. Status
  `engine_consistent` requires ≥97 % exact reproduction and max error ≤ 1.5.
* That reproduces what is **stored**; it is not proof of the game's formula.
* **Needed PCSX2 test (not yet done):** in a separate working copy change one
  rating that matters for a position (e.g. a QB's PTHA +10) without touching POVR,
  build a separate test ISO, and check the roster-screen Overall in PCSX2, then
  again after starting a franchise. Unchanged ⇒ the game trusts stored POVR and
  the converter must write POVR too (as a separate, verified write). Changed ⇒ the
  game recalculates and our fit is only for review.

## 7. Proposed first test conversion

`review/test_group_proposal.json` lists the players, their expected 1994 team,
role tier and *proposed* archetype with rationale (status `proposed`, not applied
until you approve). Selection covers QB, HB, WR, OL, DL, LB, DB, K and P, and adds a
**data-driven** rule for average starters and backups: per position group, the
median-tier starter and median-tier backup in the source (chosen after the source
is loaded, so no names are guessed).

Run order once inputs exist:

1. `export_m06_play_table.py` → `baseline` (check position-code checks, team-size
   warnings, overall-model status per group).
2. `profile-source` on the full '95 roster → verify each column's meaning per
   position (with the screen labels / manual / archive pages); fill the schema.
3. `match` the test group against the source (name, team, position, jersey);
   resolve any `ambiguous`/`weak` result by hand.
4. `archetype-check` → revise priors that contradict the Madden 06 data.
5. `convert --only <test ids>` (percentiles still use the whole league) → review
   `ratings.csv`, `provenance.csv`, `diagnostics.csv` together.

## 8. Inputs needed from you

1. **Madden '95 source data**: the actual file(s) — ROM extract, save/roster dump,
   spreadsheet, or screenshots — and how they were produced.
2. **Platform and version** (Genesis or SNES; cartridge revision if known).
3. **Field labels**: the Warren Moon screen with its column headers visible, or the
   game manual page / roster screen that names the ratings for each position.
4. **Madden 06 roster export**: run on your PC (read-only):
   `python tools\export_m06_play_table.py --editor-src "D:\Madden 06" --iso "<your SLUS-21213 ISO>" --out local_data\m06_play_member1.json`
   Keep this file local; it contains EA data.
5. Optional: saved nfldraftbuzz Madden '95 pages for cross-checking.
