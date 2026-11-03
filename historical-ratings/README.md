# Historical ratings converter (Madden '95 → Madden NFL 06 PS2)

Converts limited Madden '95 player ratings into complete, position-aware Madden 06
rating records (the 21 ratings the Madden06Editor has verified), with provenance and
confidence for every value. It is a companion to the Madden06Editor and reuses its
reader. **It never writes a DAT, save or ISO.** Applying results is a later
milestone that will go through the editor's own `editing.patch_player` on a separate
working copy.

Status: Milestone 1 (mapping) done, Milestone 2 engine implemented and tested on
synthetic data. **No real conversion has been run yet**: it needs the Madden '95
source and a Madden 06 roster export (see `docs/MILESTONE-1-MAPPING.md` §8).
No in-game validation has occurred.

## Install

Copy this folder's `historical_ratings/`, `schemas/`, `tools/`, `tests/`, `review/`
and `docs/` into `D:\Madden 06` (next to `game_formats.py`), or keep them anywhere and
pass `--editor-src`. Python 3.12+, standard library only.

## Workflow (Windows, from `D:\Madden 06`)

```bat
:: 1. Read-only export of TEMPLATE.DAT member 1 using the editor's load_players
python tools\export_m06_play_table.py --iso "<your SLUS-21213 ISO>" --out local_data\m06_play_member1.json

:: 2. Learn Madden 06 baselines; review the report (position-code checks, team sizes, Overall fit)
python -m historical_ratings baseline --play-export local_data\m06_play_member1.json --out local_data\baseline.json --report local_data\baseline_report.json

:: 3. Copy schemas\madden95_source_schema.TEMPLATE.json, then profile the source to verify column meanings
python -m historical_ratings profile-source --source local_data\m95.csv --schema local_data\m95_schema.json

:: 4. Test archetype priors against the real roster
python -m historical_ratings archetype-check --baseline local_data\baseline.json --archetypes schemas\archetypes.v1.json

:: 5. Convert (percentiles always use the whole league; --only limits the output)
python -m historical_ratings convert --source local_data\m95.csv --schema local_data\m95_schema.json ^
    --baseline local_data\baseline.json --archetypes schemas\archetypes.v1.json --assign local_data\assign.json ^
    --only ID1,ID2 --out-dir local_data\test_group
```

`match --source … --schema … --reference roster.csv [--manual decisions.json]` checks
source identities against a reference list (id, name, team, position, jersey, season).

## Outputs

| File | Content |
|---|---|
| `conversion.json` | Everything: input hashes, source row verbatim, used/ignored source fields with percentiles, tier, 21 ratings each with `method`, `confidence`, `basis`, notes; estimated Overall with model status; diagnostics |
| `ratings.csv` | One row per player, 21 values + estimated Overall |
| `provenance.csv` | One row per player × rating: value, method, confidence, basis, source row |
| `diagnostics.csv` | Errors / warnings / info (bounds, order preservation, distribution shift, Overall inflation, key ratings below Madden 06 5th percentile, unverified fields, clamps) |
| `skipped.csv` | Players not converted and why |

Outputs are deterministic (no timestamps, sorted keys): same inputs ⇒ identical bytes.

## Provenance methods

| Method | Meaning |
|---|---|
| `source_direct` | Verified Madden '95 field, percentile-mapped onto the Madden 06 distribution for that tag and position |
| `source_partial` | Verified field that only partly describes the tag; blended with the distribution estimate |
| `source_unverified` | Field meaning not verified; used only with `--allow-unverified-fields`, always low confidence |
| `historical_evidence` | Cited evidence item (`--evidence`, citation and grade A/B/C required); never overrides source-derived tags |
| `archetype` | Archetype prior (SD units of the Madden 06 residual spread); never changes source-derived tags |
| `position_distribution` | Madden 06 positional trend at the player's tier, conditioned on his direct ratings via the real roster's covariance |
| `manual_override` | Reviewed value (`--overrides`, reason + reviewer required) |

Estimated values are estimates. They are never described as historical Madden ratings.

## Safety rules built in

* Only the 21 editor-verified tags can be targets; values are integers 0–99 and
  within the range Madden 06 actually uses at that position.
* Source values outside the declared range are rejected, not clamped. Source rows
  are preserved verbatim.
* The PPOS position convention is checked against the real roster before use.
* Ambiguous or weak identity matches are never applied; a target claimed by two
  sources becomes ambiguous; archetype assignments that do not resolve stop the run.
* Outputs from the export tool refuse to overwrite existing files.
* `local_data/` (EA-derived data) is git-ignored.

## Tests

```bat
python -m unittest discover -s tests
set MADDEN06_EDITOR_SRC=D:\Madden 06
python -m unittest discover -s tests
```

The second run adds an integration test that drives the export tool through the
editor's real `game_formats.load_players` with a synthetic TEMPLATE.DAT. All test
data is synthetic.
