"""Prepare as-printed Madden '95 book tables for conversion.

Input: one or more CSVs transcribed *exactly as printed* (one row per printed row;
columns named after the printed headers). Output: one row per player, with

* ``position`` / ``depth`` / ``alt_position`` normalised from the printed slot
  (``WR5`` -> WR, depth 5; ``DRT(NT)`` -> DRT, alternate NT);
* KR/PR rows from the special-teams table attached to the player's position row as
  ``kr_*`` / ``pr_*`` columns (linked by team + jersey + surname, never by name alone);
* return-only players (no position row) kept as their own row so nothing is lost;
* review flags: missing names, surnames shared on a team, return-only, reading notes.

Printed values are copied as text; range checks happen when the schema loads them.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .matching import normalize_name

IDENTITY = ("team", "table", "no", "name", "slot", "reading_note")
RATING_COLUMNS = ("speed", "scrambling", "pass_accuracy", "pass_range", "agility", "hands", "break_tackles",
                  "weight", "pass_blocking", "run_blocking", "pursuit", "tackling", "awareness",
                  "pass_coverage", "interceptions", "distance", "accuracy")
RETURN_FIELDS = ("speed", "agility", "break_tackles")
RETURN_COLUMNS = tuple(f"{p}_{f}" for p in ("kr", "pr") for f in RETURN_FIELDS)
RETURN_ROLES = ("KR", "PR")
OUTPUT_COLUMNS = ("id", "team", "position", "slot", "depth", "alt_position", "jersey", "name",
                  *RATING_COLUMNS, *RETURN_COLUMNS, "return_roles", "printed_rows", "flags")


class BookError(ValueError):
    pass


def normalize_slot(slot: str) -> tuple[str, str, int, str]:
    """Return (slot without alternate, position, depth, alternate) e.g. 'DRT(NT)' -> ('DRT','DRT',1,'NT')."""
    s = slot.strip().upper()
    alt = re.search(r"\(([^)]*)\)", s)
    base = re.sub(r"\([^)]*\)", "", s).strip()
    m = re.fullmatch(r"([A-Z]+?)(\d*)", base)
    if not m:
        raise BookError(f"Unrecognised slot {slot!r}")
    return base, m.group(1), int(m.group(2) or 1), alt.group(1) if alt else ""


def _surname(name: str) -> str:
    tokens = normalize_name(name)
    return tokens[-1] if tokens else ""


def read_printed(paths: list[str | Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with Path(path).open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            unknown = set(reader.fieldnames or ()) - set(IDENTITY) - set(RATING_COLUMNS)
            if unknown:
                raise BookError(f"{Path(path).name}: unknown printed columns {sorted(unknown)}; "
                                "a different table layout must be reviewed before use")
            for r in reader:
                rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def prepare(printed: list[dict]) -> tuple[list[dict], dict]:
    players: list[dict] = []
    by_id: dict[str, dict] = {}
    returns: list[dict] = []
    for n, r in enumerate(printed, start=1):
        slot, pos, depth, alt = normalize_slot(r["slot"])
        source = f"{r['table']}:{r['slot']}"
        if pos in RETURN_ROLES and r["table"].upper().startswith("SPECIAL"):
            returns.append({**r, "_role": pos, "_slot": slot, "_source": source})
            continue
        pid = f"{r['team']}-{slot}"
        if pid in by_id:
            raise BookError(f"Printed row {n}: slot {slot} appears twice for {r['team']}")
        out = {c: "" for c in OUTPUT_COLUMNS}
        out.update(id=pid, team=r["team"], position=pos, slot=slot, depth=str(depth), alt_position=alt,
                   jersey=r["no"], name=r["name"], printed_rows=source)
        for c in RATING_COLUMNS:
            out[c] = r.get(c, "")
        flags = []
        if not r["name"]:
            flags.append("name_missing")
        elif len(normalize_name(r["name"])) == 1:
            flags.append("no_initial")
        if r.get("reading_note"):
            flags.append(f"reading_note: {r['reading_note']}")
        out["_flags"] = flags
        players.append(out)
        by_id[pid] = out

    links, return_only = [], []
    orphan: dict[tuple, dict] = {}
    for r in returns:
        prefix = r["_role"].lower()
        cands = [p for p in players if p["id"] not in return_only and p["team"] == r["team"]
                 and p["jersey"] == r["no"] and _surname(p["name"]) == _surname(r["name"]) and _surname(r["name"])]
        if len(cands) > 1:
            raise BookError(f"{r['team']} {r['_slot']} #{r['no']} {r['name']}: several position rows match")
        if cands:
            target = cands[0]
            links.append({"return_row": r["_source"], "team": r["team"], "player": target["id"]})
        else:
            key = (r["team"], r["no"], _surname(r["name"]))
            target = orphan.get(key)
            if target is None:
                target = {c: "" for c in OUTPUT_COLUMNS}
                target.update(id=f"{r['team']}-RET{r['no']}", team=r["team"], position=r["_role"], slot=r["_slot"],
                              depth="", jersey=r["no"], name=r["name"], printed_rows="")
                target["_flags"] = ["return_only: no position row on this page; assign a Madden 06 position"]
                orphan[key] = target
                players.append(target)
                return_only.append(target["id"])
            elif r["_role"] == "KR" and target["position"] == "PR":
                target["position"] = "KR"
        if any(target[f"{prefix}_{f}"] for f in RETURN_FIELDS):
            raise BookError(f"{target['id']}: two {r['_role']} rows")
        for f in RETURN_FIELDS:
            target[f"{prefix}_{f}"] = r.get(f, "")
        target["return_roles"] = ";".join(filter(None, [target["return_roles"], r["_slot"]]))
        target["printed_rows"] = ";".join(filter(None, [target["printed_rows"], r["_source"]]))
        note = f"reading_note: {r['reading_note']}" if r.get("reading_note") else ""
        if note and note not in target["_flags"]:
            target["_flags"].append(note)

    # Surnames shared within a team where printed initials do not tell them apart:
    # position + jersey are then required to identify each player.
    by_team_surname: dict[tuple, list[dict]] = {}
    for p in players:
        if _surname(p["name"]):
            by_team_surname.setdefault((p["team"], _surname(p["name"])), []).append(p)
    def initial(p):
        tokens = normalize_name(p["name"])
        return tokens[0][0] if len(tokens) > 1 else ""

    for group in by_team_surname.values():
        for p in group:
            clash = [q for q in group if q is not p and q["jersey"] != p["jersey"]
                     and (not initial(p) or not initial(q) or initial(p) == initial(q))]
            if clash:
                p["_flags"].append("shared_surname: " + ",".join(q["id"] for q in clash))

    flags = {}
    for p in players:
        p["flags"] = " | ".join(p["_flags"])
        if p["_flags"]:
            flags[p["id"]] = p.pop("_flags")
        else:
            p.pop("_flags")
    review = {"printed_rows": len(printed), "players": len(players), "return_links": links,
              "return_only": return_only, "flags": flags}
    return players, review


def write_prepared(players: list[dict], path: str | Path) -> None:
    with Path(path).open("x", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, OUTPUT_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(players)
