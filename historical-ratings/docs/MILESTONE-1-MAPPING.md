# Milestone 1 — research and mapping

Status as of 2026-11-03 (updated after the Vikings book page was supplied). "Verified" means checked against a primary artifact
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

## 3. Madden '95 source — verified from the printed book

Source: Madden NFL '95 printed team ratings, "NFC Central Player Ratings",
**Minnesota Vikings** page (image supplied by the project owner, 758×507 px). The
table headers below were read directly from it. The transcription is kept in the
git-ignored `local_data/` folder because it is game content.

### Ratings printed per position table

| Table (slots on the Vikings page) | Ratings printed |
|---|---|
| Quarterbacks (QB1–QB3) | Speed, Scrambling, Pass Accuracy, Pass Range |
| Running backs (HB1–HB3, FB, FB2) | Speed, Agility, Hands, Break Tackles |
| Receivers (WR1–WR6, TE1–TE3) | Speed, Agility, Hands, Break Tackles |
| Offensive line (LT, LG, C, RG, RT, T2, G2, C2) | Weight (lb), Pass Blocking, Run Blocking |
| Defensive line (LE, DLT, DRT(NT), RE, DE2, DT2) | Speed, Agility, Pursuit, Tackling |
| Linebackers (LOLB, ILB, ROLB, ILB2, ILB3, OLB2, OLB3) | Speed, Agility, Awareness, Tackling |
| Defensive backs (LCB1, LCB2, RCB1, RCB2, FS, SS, FS2, SS2) | Speed, Pass Coverage, Interceptions, Tackling |
| Special teams: K, P | Distance, Accuracy |
| Special teams: KR, KR2, PR | Speed, Agility, Break Tackles (return-specific) |

* **Warren Moon (QB1, #1): Speed 7, Scrambling 4, Pass Accuracy 13, Pass Range 12.**
  This resolves the earlier unlabelled example.
* **Scale:** every printed rating on the page is 1–15; weight is in pounds.
* **Not consistent across positions:** each table prints 3–4 ratings, and some
  Madden 06 essentials have no printed counterpart at some positions: no strength
  for any lineman, no awareness for quarterbacks, no agility for defensive backs.
* The same concept can carry different values in different tables: Q. Ismail is
  WR5 with agility 8 and KR with agility 14. Return ratings are kept separate.

### Identity patterns on the page

* Names are initial + surname or surname only; two different Vikings are printed
  just as "McDaniel" (LG #64 and ROLB #58).
* One row (#36, LCB2) has a blank name cell.
* D. Palmer (#22) appears only as KR2 and PR, with no position row.
* Depth-chart slots are printed (QB3, WR6, ILB3…); one slot is "DRT(NT)".

### Roster basis and platform

* Vikings page: Moon is on Minnesota (April 1994 trade), and 1994 draft picks
  DeWayne Washington (RCB1), Todd Steussie (G2) and David Palmer (KR2/PR) are
  listed. That is a **post-April-1994-draft roster**, i.e. the shipped 1994 roster.
  Confirm on each team page with the markers below.
* The book names players, which is consistent with the Genesis release (NFLPA
  licence). Which box/manual it came from is still to be confirmed.

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

## 4. Source → target mapping (implemented)

`schemas/madden95_book_schema.v1.json`. Labels are verified; each mapping is marked
**equivalent** (the Madden 06 rating governs the same on-field outcome; confidence
0.8, high) or **approximate** (closest Madden 06 counterpart to a concept Madden 06
does not rate; confidence 0.6, medium).

| Book rating | Positions | Madden 06 | Mapping | Note |
|---|---|---|---|---|
| Speed | all except OL, K, P | PSPD | equivalent | |
| Scrambling | QB | PAGI | approximate | no Madden 06 scrambling rating |
| Pass Accuracy | QB | PTHA | equivalent | |
| Pass Range | QB | PTHP | equivalent | throw power governs distance |
| Agility | RB, WR, TE, DL, LB | PAGI | equivalent | |
| Hands | RB, WR, TE | PCTH | equivalent | |
| Break Tackles | RB, WR, TE | PBTK | equivalent | |
| Weight | OL | PWGT (conditioning only) | — | not a rating; informs the strength estimate; never written |
| Pass / Run Blocking | OL | PPBK / PRBK | equivalent | |
| Pursuit | DL | PAWR | approximate | no Madden 06 pursuit rating; acceleration is the alternative; revisit in calibration |
| Tackling | DL, LB, DB | PTAK | equivalent | |
| Awareness | LB | PAWR | equivalent | |
| Pass Coverage | DB | PAWR | approximate | no Madden 06 coverage rating |
| Interceptions | DB | PCTH | approximate | Madden 06 resolves defensive interceptions mainly through catching |
| Distance / Accuracy | K, P | PKPR / PKAC | equivalent | |
| KR/PR Speed, Agility, Break Tackles | listed returners | PKRT | approximate | ranked among league returners and mapped onto each Madden 06 team's top returners; does not affect the player's tier |

### What each position gets from the book and what must be estimated

| Group | From the book | Estimated (Madden 06 correlations, then archetype / evidence / review) |
|---|---|---|
| QB | PSPD, PAGI, PTHA, PTHP | PAWR, PACC, PSTR and the rest |
| HB, FB, WR, TE | PSPD, PAGI, PCTH, PBTK | PACC, PSTR, PCAR, PAWR, PJMP; blocking for TE/FB |
| OL | PPBK, PRBK (+ weight) | **PSTR** (conditioned on weight), PAWR, PAGI, PSPD, PACC |
| DL | PSPD, PAGI, PAWR (pursuit), PTAK | **PSTR**, PACC |
| LB | PSPD, PAGI, PAWR, PTAK | PSTR, PACC, PCTH, PJMP |
| DB | PSPD, PAWR (coverage), PCTH (interceptions), PTAK | PAGI, PACC, PJMP, PSTR |
| K, P | PKPR, PKAC | the rest (low impact) |
| Listed returners | PKRT | — |
| Everyone | — | PIMP, PSTA, PINJ, PTGH (no '95 counterpart) |

Non-returners get PKRT from Madden 06 players at their position who are *not*
among their team's top returners, so starters do not inherit returner values.

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
2. Transcribe each team page as printed (same columns as the Vikings file), then
   `prepare-book` → one row per player plus a review file (return links,
   return-only players, missing names, surnames initials cannot separate).
   `profile-source` gives per-position column statistics as a transcription check.
3. `match` the test group against the source (name, team, position, jersey);
   resolve any `ambiguous`/`weak` result by hand.
4. `archetype-check` → revise priors that contradict the Madden 06 data.
5. `convert --only <test ids>` (percentiles still use the whole league) → review
   `ratings.csv`, `provenance.csv`, `diagnostics.csv` together.

## 8. Inputs needed from you

1. **The other 27 team pages** of the book, scanned or photographed at higher
   resolution (300 dpi or ≥ 2000 px wide). The Vikings image was readable, but a few
   initials are uncertain at 758×507 (flagged in the transcription). Percentiles need
   the whole league: one team cannot say whether Moon's 13 accuracy is elite in 1994.
2. **Madden 06 roster export** (read-only, on your PC; keep it local):
   `python tools\export_m06_play_table.py --editor-src "D:\Madden 06" --iso "<your SLUS-21213 ISO>" --out local_data\m06_play_member1.json`
3. Which box/manual the book came from (Genesis or SNES).
4. Review decisions the book cannot make: a Madden 06 position for return-only
   players such as D. Palmer, and the identity of the unnamed #36 LCB2.
5. Optional: saved nfldraftbuzz Madden '95 pages to cross-check the transcription.
