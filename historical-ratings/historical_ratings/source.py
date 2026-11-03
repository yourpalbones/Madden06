"""Madden NFL '95 source schema and roster loading.

Nothing about Madden '95 field meanings is hard-coded. A schema file declares:

* ``columns``: raw rating columns and their stored range (e.g. 0..15).
* ``interpretations``: what a column means *for given source positions*, which
  Madden 06 tags it informs, whether that meaning is verified and the evidence.
  Classic Madden reused rating slots per position, so the same column may mean
  different things for a QB and a guard.
* ``position_map``: source position/depth slot -> Madden 06 baseline group.

Source rows are kept verbatim (``raw``) next to parsed integers so outputs can
always show exactly what the source said.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .m06_schema import GROUPS, TARGET_TAGS

ROLES = ("primary", "supporting")


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Interpretation:
    column: str
    positions: tuple[str, ...]  # source positions; "*" = all
    meaning: str
    targets: tuple[tuple[str, str, float], ...]  # (tag, role, weight)
    verified: bool
    evidence: str

    def applies_to(self, position: str) -> bool:
        return "*" in self.positions or position in self.positions


@dataclass
class SourceSchema:
    game: str
    platform: str
    roster_basis: str
    columns: dict[str, tuple[int, int]]
    interpretations: list[Interpretation]
    position_map: dict[str, str | None]
    identity_columns: dict[str, str]
    sha256: str = ""
    notes: list[str] = field(default_factory=list)

    def interpretations_for(self, position: str) -> list[Interpretation]:
        return [i for i in self.interpretations if i.applies_to(position)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema(path: str | Path) -> SourceSchema:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise SchemaError("schema_version must be 1")
    columns: dict[str, tuple[int, int]] = {}
    for c in data["columns"]:
        lo, hi = int(c["min"]), int(c["max"])
        if lo > hi:
            raise SchemaError(f"Column {c['name']} has min > max")
        columns[c["name"]] = (lo, hi)
    interps: list[Interpretation] = []
    for i in data.get("interpretations", []):
        if i["column"] not in columns:
            raise SchemaError(f"Interpretation references unknown column {i['column']}")
        targets = []
        for t in i.get("targets", []):
            tag, role = t["tag"], t.get("role", "primary")
            if tag not in TARGET_TAGS:
                raise SchemaError(f"Unknown Madden 06 tag {tag}; only the 21 verified tags are allowed")
            if role not in ROLES:
                raise SchemaError(f"Unknown target role {role}")
            weight = float(t.get("weight", 1.0 if role == "primary" else 0.5))
            if not 0 < weight <= 1:
                raise SchemaError("Target weight must be in (0, 1]")
            targets.append((tag, role, weight))
        verified = bool(i.get("verified", False))
        evidence = str(i.get("evidence", "")).strip()
        if verified and not evidence:
            raise SchemaError(f"Verified interpretation of {i['column']} needs evidence")
        interps.append(Interpretation(
            column=i["column"], positions=tuple(i.get("positions", ["*"])),
            meaning=str(i["meaning"]), targets=tuple(targets),
            verified=verified, evidence=evidence,
        ))
    # Two interpretations may not claim the same column for the same position.
    seen: dict[tuple[str, str], str] = {}
    for interp in interps:
        for pos in interp.positions:
            key = (interp.column, pos)
            if key in seen:
                raise SchemaError(f"Column {interp.column} interpreted twice for position {pos}")
            seen[key] = interp.meaning
    pmap = {}
    for k, v in data.get("position_map", {}).items():
        if v is not None and v not in GROUPS:
            raise SchemaError(f"position_map {k} -> {v}: not a Madden 06 group")
        pmap[k] = v
    ident = data.get("identity_columns", {})
    for need in ("source_id", "team", "position"):
        if need not in ident:
            raise SchemaError(f"identity_columns must name the {need} column")
    return SourceSchema(
        game=data.get("game", ""), platform=data.get("platform", "UNVERIFIED"),
        roster_basis=data.get("roster_basis", "UNVERIFIED"), columns=columns,
        interpretations=interps, position_map=pmap, identity_columns=ident,
        sha256=_sha256(path), notes=list(data.get("notes", [])),
    )


@dataclass
class SourcePlayer:
    source_id: str
    team: str
    position: str
    name: str
    jersey: str
    ratings: dict[str, int]
    raw: dict[str, str]  # exactly as read

    @property
    def key(self) -> str:
        return self.source_id


@dataclass
class SourceRoster:
    players: list[SourcePlayer]
    sha256: str
    path: str


def _read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["players"] if isinstance(data, dict) else data
        return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def load_roster(path: str | Path, schema: SourceSchema) -> SourceRoster:
    """Load a source roster; out-of-range or non-integer ratings are errors, never clamped."""
    path = Path(path)
    rows = _read_rows(path)
    ic = schema.identity_columns
    players: list[SourcePlayer] = []
    seen: set[str] = set()
    errors: list[str] = []
    for n, row in enumerate(rows, start=1):
        sid = row.get(ic["source_id"], "").strip()
        if not sid:
            errors.append(f"row {n}: empty source id")
            continue
        if sid in seen:
            errors.append(f"row {n}: duplicate source id {sid}")
            continue
        seen.add(sid)
        ratings: dict[str, int] = {}
        for col, (lo, hi) in schema.columns.items():
            text = row.get(col, "").strip()
            if text == "":
                continue  # not every position stores every column
            try:
                value = int(text)
            except ValueError:
                errors.append(f"row {n} ({sid}): {col}={text!r} is not an integer")
                continue
            if not lo <= value <= hi:
                errors.append(f"row {n} ({sid}): {col}={value} outside {lo}..{hi}")
                continue
            ratings[col] = value
        players.append(SourcePlayer(
            source_id=sid,
            team=row.get(ic["team"], "").strip(),
            position=row.get(ic["position"], "").strip(),
            name=row.get(ic.get("name", ""), "").strip() if ic.get("name") else "",
            jersey=row.get(ic.get("jersey", ""), "").strip() if ic.get("jersey") else "",
            ratings=ratings,
            raw=dict(row),
        ))
    if errors:
        raise SchemaError("Source roster rejected:\n  " + "\n  ".join(errors[:50]))
    return SourceRoster(players=players, sha256=_sha256(path), path=str(path))


def profile_columns(roster: SourceRoster) -> dict[str, dict[str, dict[str, float]]]:
    """Per source position, per column: n/min/max/mean. Used to help verify field meanings."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for p in roster.players:
        for col, v in p.ratings.items():
            slot = out.setdefault(p.position, {}).setdefault(col, {"n": 0, "min": v, "max": v, "sum": 0})
            slot["n"] += 1
            slot["min"] = min(slot["min"], v)
            slot["max"] = max(slot["max"], v)
            slot["sum"] += v
    for cols in out.values():
        for s in cols.values():
            s["mean"] = round(s.pop("sum") / s["n"], 2)
    return out
