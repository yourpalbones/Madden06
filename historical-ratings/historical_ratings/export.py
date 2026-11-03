"""Deterministic CSV/JSON export. No timestamps, sorted keys: identical inputs give identical bytes."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from . import __version__
from .convert import METHODS, ConversionResult
from .m06_schema import RATING_FIELDS, SCHEMA_EVIDENCE, TARGET_TAGS


def result_payload(result: ConversionResult, diagnostics: list[dict]) -> dict:
    return {
        "format": "historical_ratings.conversion/1",
        "tool_version": __version__,
        "inputs": result.inputs,
        "target_schema": {"tags": RATING_FIELDS, "bounds": [0, 99], "evidence": SCHEMA_EVIDENCE},
        "methods": METHODS,
        "population": result.population,
        "players": [p.to_dict() for p in result.players],
        "skipped": result.skipped,
        "diagnostics": diagnostics,
        "disclaimer": ("Values other than method 'source_direct' are estimates, not historical Madden ratings. "
                       "No converted record has been validated in-game unless a separate test report says so."),
    }


def write_outputs(result: ConversionResult, diagnostics: list[dict], out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {k: out / v for k, v in {
        "json": "conversion.json", "ratings_csv": "ratings.csv", "provenance_csv": "provenance.csv",
        "diagnostics_csv": "diagnostics.csv", "skipped_csv": "skipped.csv",
    }.items()}
    paths["json"].write_text(json.dumps(result_payload(result, diagnostics), indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    with paths["ratings_csv"].open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["source_id", "name", "team", "source_position", "m06_group", "archetype", "tier_povr",
                    "estimated_overall", "overall_model_status", *TARGET_TAGS])
        for p in result.players:
            w.writerow([p.source_id, p.name, p.team, p.source_position, p.group, p.archetype or "",
                        p.tier["povr"], p.estimated_overall.get("value", ""), p.estimated_overall.get("model_status", ""),
                        *[p.attributes[t].value for t in TARGET_TAGS]])
    with paths["provenance_csv"].open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["source_id", "name", "tag", "label", "value", "method", "confidence", "confidence_label",
                    "basis", "notes", "source_raw"])
        for p in result.players:
            raw = json.dumps(p.source_raw, sort_keys=True)
            for t in TARGET_TAGS:
                a = p.attributes[t]
                w.writerow([p.source_id, p.name, t, RATING_FIELDS[t], a.value, a.method, round(a.confidence, 3),
                            a.confidence_label, json.dumps(a.basis, sort_keys=True), " | ".join(a.notes), raw])
    with paths["diagnostics_csv"].open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["severity", "code", "source_id", "group", "tag", "message"], lineterminator="\n")
        w.writeheader()
        w.writerows(diagnostics)
    with paths["skipped_csv"].open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["source_id", "reason"])
        for s in result.skipped:
            w.writerow([s["source_id"], s["reason"]])
    return paths
