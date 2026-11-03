"""SYNTHETIC fixtures only. No EA data, no real ratings, no real Madden '95 field semantics.

The fake Madden 06 roster follows the PPOS convention and has an exactly linear
POVR formula per group so the overall-model fit can be tested. The fake source
roster uses columns r1..r4 whose "meanings" are invented for tests.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from historical_ratings.m06_schema import PPOS_CONVENTION, POSITION_GROUP, TARGET_TAGS

PER_TEAM = {"QB": 3, "HB": 3, "FB": 1, "WR": 5, "TE": 3, "LT": 1, "LG": 1, "C": 2, "RG": 1, "RT": 1,
            "LE": 2, "RE": 2, "DT": 4, "LOLB": 2, "MLB": 2, "ROLB": 2, "CB": 5, "FS": 2, "SS": 2, "K": 1, "P": 1}

BASE = {t: 40 for t in TARGET_TAGS}
GROUP_MEANS = {
    "QB": {"PTHP": 86, "PTHA": 74, "PAWR": 68, "PSPD": 62, "PAGI": 62, "PACC": 66, "PKPR": 25, "PKAC": 20, "PCTH": 40},
    "HB": {"PSPD": 86, "PACC": 86, "PAGI": 84, "PCAR": 80, "PBTK": 72, "PSTR": 62, "PCTH": 62, "PKRT": 50},
    "FB": {"PSTR": 72, "PRBK": 62, "PCAR": 68, "PBTK": 66, "PSPD": 72, "PCTH": 55},
    "WR": {"PSPD": 88, "PACC": 88, "PAGI": 86, "PCTH": 78, "PJMP": 78, "PKRT": 50},
    "TE": {"PCTH": 68, "PRBK": 58, "PPBK": 50, "PSTR": 66, "PSPD": 72},
    "T": {"PPBK": 76, "PRBK": 76, "PSTR": 86, "PSPD": 48, "PAWR": 66},
    "G": {"PPBK": 74, "PRBK": 78, "PSTR": 88, "PSPD": 48, "PAWR": 66},
    "C": {"PPBK": 74, "PRBK": 74, "PSTR": 84, "PSPD": 48, "PAWR": 70},
    "DE": {"PSTR": 78, "PTAK": 72, "PSPD": 74, "PACC": 76, "PAWR": 62},
    "DT": {"PSTR": 88, "PTAK": 74, "PSPD": 60, "PAWR": 62},
    "OLB": {"PTAK": 76, "PSPD": 78, "PSTR": 70, "PAWR": 64, "PCTH": 45},
    "MLB": {"PTAK": 80, "PSPD": 74, "PSTR": 72, "PAWR": 68},
    "CB": {"PSPD": 90, "PACC": 90, "PAGI": 88, "PCTH": 58, "PJMP": 82, "PTAK": 55, "PSTR": 45},
    "FS": {"PSPD": 86, "PTAK": 66, "PCTH": 55, "PJMP": 78, "PAWR": 66, "PSTR": 52},
    "SS": {"PSPD": 84, "PTAK": 72, "PCTH": 52, "PJMP": 74, "PAWR": 66, "PSTR": 58},
    "K": {"PKPR": 88, "PKAC": 82, "PSPD": 50, "PTHP": 30},
    "P": {"PKPR": 86, "PKAC": 78, "PSPD": 50, "PTHP": 30},
}
# Exactly linear synthetic Overall weights (intercept, {tag: weight}).
OVR = {
    "QB": (-20.0, {"PTHP": 0.4, "PTHA": 0.5, "PAWR": 0.35}),
    "HB": (-25.0, {"PSPD": 0.4, "PAGI": 0.3, "PCAR": 0.25, "PBTK": 0.3}),
    "FB": (-10.0, {"PSTR": 0.3, "PRBK": 0.4, "PCAR": 0.3, "PBTK": 0.2}),
    "WR": (-30.0, {"PSPD": 0.45, "PCTH": 0.5, "PAGI": 0.3}),
    "TE": (-10.0, {"PCTH": 0.4, "PRBK": 0.35, "PSTR": 0.2, "PSPD": 0.2}),
    "T": (-20.0, {"PPBK": 0.45, "PRBK": 0.4, "PSTR": 0.3}),
    "G": (-20.0, {"PPBK": 0.4, "PRBK": 0.45, "PSTR": 0.3}),
    "C": (-20.0, {"PPBK": 0.42, "PRBK": 0.42, "PSTR": 0.3}),
    "DE": (-25.0, {"PSTR": 0.3, "PTAK": 0.35, "PSPD": 0.25, "PACC": 0.25}),
    "DT": (-20.0, {"PSTR": 0.45, "PTAK": 0.4, "PAWR": 0.15}),
    "OLB": (-25.0, {"PTAK": 0.4, "PSPD": 0.35, "PAWR": 0.25, "PSTR": 0.15}),
    "MLB": (-20.0, {"PTAK": 0.45, "PAWR": 0.35, "PSPD": 0.2, "PSTR": 0.15}),
    "CB": (-40.0, {"PSPD": 0.5, "PAGI": 0.3, "PCTH": 0.2, "PJMP": 0.15}),
    "FS": (-25.0, {"PSPD": 0.35, "PTAK": 0.25, "PAWR": 0.3, "PCTH": 0.2}),
    "SS": (-25.0, {"PSPD": 0.3, "PTAK": 0.35, "PAWR": 0.3, "PCTH": 0.15}),
    "K": (-15.0, {"PKPR": 0.55, "PKAC": 0.6}),
    "P": (-15.0, {"PKPR": 0.6, "PKAC": 0.55}),
}
# A style axis creates archetype-like residual structure (e.g. elusive vs power HB).
STYLE = {"HB": {"PAGI": 4, "PACC": 3, "PSTR": -4, "PBTK": -3}, "QB": {"PSPD": 5, "PAGI": 4, "PACC": 4}}


def make_m06_play(seed: int = 6) -> list[dict]:
    rng = random.Random(seed)
    code = {v: k for k, v in PPOS_CONVENTION.items()}
    rows, pgid = [], 0
    for tgid in range(32):
        for pos, count in PER_TEAM.items():
            g = POSITION_GROUP[pos]
            for depth in range(count):
                q = rng.gauss(0.8 if depth == 0 else -0.4, 0.8)
                style = rng.gauss(0, 1)
                rec = {}
                for t in TARGET_TAGS:
                    mean = GROUP_MEANS[g].get(t, BASE[t])
                    load = 6 if t in GROUP_MEANS[g] else 2
                    v = mean + load * q + STYLE.get(g, {}).get(t, 0) * style + rng.gauss(0, 3)
                    rec[t] = max(0, min(99, int(round(v))))
                b0, w = OVR[g]
                ovr = b0 + sum(wt * rec[t] for t, wt in w.items())
                rec.update({"PGID": pgid, "TGID": tgid, "PPOS": code[pos], "POVR": max(0, min(99, int(round(ovr)))),
                            "PFNA": "Synth", "PLNA": f"Player{pgid}", "_member": 1, "_row": pgid, "_team": f"Team {tgid:02d}"})
                rows.append(rec)
                pgid += 1
    # A few free agents without a team record must be excluded.
    for i in range(5):
        rows.append({**rows[i], "PGID": 9000 + i, "TGID": 1009, "_team": ""})
    return rows


SOURCE_SLOTS = ["QB1", "QB2", "HB1", "HB2", "FB1", "WR1", "WR2", "WR3", "TE1", "TE2",
                "LT", "LG", "C", "RG", "RT", "LDE", "RDE", "LDT", "RDT", "LOLB", "LILB", "RILB", "ROLB",
                "LCB1", "RCB1", "LCB2", "SS", "FS", "K", "P"]
SOURCE_GROUP = {"QB": "QB", "HB": "HB", "FB": "FB", "WR": "WR", "TE": "TE", "LT": "T", "RT": "T", "LG": "G",
                "RG": "G", "C": "C", "LDE": "DE", "RDE": "DE", "LDT": "DT", "RDT": "DT", "LOLB": "OLB",
                "ROLB": "OLB", "LILB": "MLB", "RILB": "MLB", "LCB": "CB", "RCB": "CB", "SS": "SS", "FS": "FS",
                "K": "K", "P": "P"}


def slot_position(slot: str) -> str:
    return slot.rstrip("0123456789")


def make_source_rows(seed: int = 95) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for t in range(28):
        for slot in SOURCE_SLOTS:
            starter = not slot.endswith("2") and not slot.endswith("3")
            q = rng.gauss(0.6 if starter else -0.5, 0.9)
            vals = [max(0, min(15, int(round(8 + 2.5 * q + rng.gauss(0, 1.5))))) for _ in range(4)]
            rows.append({"id": f"T{t:02d}-{slot}", "team": f"Old{t:02d}", "slot": slot_position(slot),
                         "name": f"Fake {slot}T{t:02d}", "num": str(10 + len(rows) % 80),
                         "r1": str(vals[0]), "r2": str(vals[1]), "r3": str(vals[2]), "r4": str(vals[3])})
    return rows


def make_schema(verified: bool = True) -> dict:
    ev = "TEST FIXTURE ONLY" if verified else ""
    def interp(col, positions, meaning, targets):
        return {"column": col, "positions": positions, "meaning": meaning, "targets": targets,
                "verified": verified, "evidence": ev}
    P = lambda tag: {"tag": tag, "role": "primary"}
    S = lambda tag, w=0.5: {"tag": tag, "role": "supporting", "weight": w}
    return {
        "schema_version": 1,
        "game": "SYNTHETIC TEST SOURCE (not Madden '95)",
        "platform": "synthetic", "roster_basis": "synthetic",
        "identity_columns": {"source_id": "id", "team": "team", "position": "slot", "name": "name", "jersey": "num"},
        "columns": [{"name": c, "min": 0, "max": 15} for c in ("r1", "r2", "r3", "r4")],
        "interpretations": [
            interp("r1", ["*"], "fake speed", [P("PSPD")]),
            interp("r2", ["QB", "HB", "WR", "CB"], "fake agility", [P("PAGI")]),
            interp("r3", ["QB"], "fake arm", [P("PTHP")]),
            interp("r4", ["QB"], "fake accuracy", [P("PTHA")]),
            interp("r3", ["HB", "FB", "WR", "TE"], "fake hands", [P("PCTH")]),
            interp("r4", ["HB", "FB"], "fake power", [P("PBTK"), S("PSTR")]),
            interp("r3", ["LT", "LG", "C", "RG", "RT"], "fake pass block", [P("PPBK")]),
            interp("r4", ["LT", "LG", "C", "RG", "RT", "TE"], "fake run block", [P("PRBK")]),
            interp("r3", ["LDE", "RDE", "LDT", "RDT", "LOLB", "ROLB", "LILB", "RILB", "SS", "FS"], "fake tackle", [P("PTAK")]),
            interp("r4", ["LDE", "RDE", "LDT", "RDT"], "fake strength", [P("PSTR")]),
            interp("r3", ["LCB", "RCB"], "fake hands", [P("PCTH")]),
            interp("r3", ["K", "P"], "fake kick power", [P("PKPR")]),
            interp("r4", ["K", "P"], "fake kick accuracy", [P("PKAC")]),
        ],
        "position_map": {k: v for k, v in SOURCE_GROUP.items()},
    }


def write_fixture_files(tmp: Path, *, verified: bool = True) -> dict[str, Path]:
    tmp.mkdir(parents=True, exist_ok=True)
    play = tmp / "m06_play.json"
    play.write_text(json.dumps({"players": make_m06_play()}), encoding="utf-8")
    src = tmp / "source.csv"
    rows = make_source_rows()
    with src.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    schema = tmp / "schema.json"
    schema.write_text(json.dumps(make_schema(verified)), encoding="utf-8")
    return {"play": play, "source": src, "schema": schema}
