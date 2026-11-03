"""Command line: python -m historical_ratings <command> ...

  prepare-book     Turn as-printed Madden '95 book tables into one row per player.
  baseline         Learn Madden 06 positional baselines from a PLAY export.
  profile-source   Per-position column statistics of a Madden '95 source (field verification aid).
  match            Match source players against a reference roster; writes a review queue.
  archetype-check  Test archetype priors against Madden 06 residual correlations.
  convert          Produce complete Madden 06 rating records with provenance + diagnostics.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .archetypes import archetype_support, load_archetypes
from .baseline import Baseline
from .convert import convert, load_evidence, load_overrides
from .diagnostics import run_diagnostics
from .export import write_outputs
from .matching import match_records
from .source import load_roster, load_schema, profile_columns


def _dump(obj, path: str | None) -> None:
    text = json.dumps(obj, indent=1, sort_keys=True) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    else:
        sys.stdout.write(text)


def _read_records(path: str) -> list[dict]:
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        return data["players"] if isinstance(data, dict) else data
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _source_identity_records(roster) -> list[dict]:
    return [{"id": p.source_id, "name": p.name, "team": p.team, "position": p.position, "jersey": p.jersey}
            for p in roster.players]


def resolve_assignments(path: str, roster) -> dict[str, str]:
    """Archetype assignments by source_id or by name/team/position; ambiguity is an error."""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    problems: list[str] = []
    ids = {p.source_id for p in roster.players}
    for n, item in enumerate(items):
        if item.get("source_id"):
            sid = str(item["source_id"])
            if sid not in ids:
                problems.append(f"assignment {n}: unknown source_id {sid}")
                continue
        else:
            ref = [{"id": f"assign{n}", "name": item["name"], "team": item["team"],
                    "position": item.get("position", ""), "jersey": item.get("jersey", "")}]
            res = match_records(ref, _source_identity_records(roster))[0]
            if not res.applicable:
                problems.append(f"assignment {n} ({item['name']}, {item['team']}): {res.status}; "
                                f"candidates {[c['id'] for c in res.candidates]}")
                continue
            sid = res.target_id
        if sid in out and out[sid] != item["archetype"]:
            problems.append(f"source {sid} assigned two archetypes")
        out[sid] = item["archetype"]
    if problems:
        raise SystemExit("Archetype assignments need review:\n  " + "\n  ".join(problems))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="historical_ratings", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("prepare-book")
    pb.add_argument("--printed", required=True, nargs="+", help="as-printed CSV(s), one or more team pages")
    pb.add_argument("--out", required=True, help="new prepared source CSV")
    pb.add_argument("--review", required=True, help="new review JSON (links, return-only players, flags)")

    b = sub.add_parser("baseline")
    b.add_argument("--play-export", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--report")
    b.add_argument("--position-codes-verified", action="store_true",
                   help="accept the PPOS convention even if data checks fail (only after manual verification)")
    b.add_argument("--exclude-tgid", type=int, action="append", default=[])

    ps = sub.add_parser("profile-source")
    ps.add_argument("--source", required=True)
    ps.add_argument("--schema", required=True)
    ps.add_argument("--out")

    m = sub.add_parser("match")
    m.add_argument("--source", required=True)
    m.add_argument("--schema", required=True)
    m.add_argument("--reference", required=True, help="CSV/JSON with id,name,team,position[,jersey,season]")
    m.add_argument("--manual", help="JSON {source_id: target_id or null}")
    m.add_argument("--out", required=True)

    ac = sub.add_parser("archetype-check")
    ac.add_argument("--baseline", required=True)
    ac.add_argument("--archetypes", required=True)
    ac.add_argument("--out")

    c = sub.add_parser("convert")
    c.add_argument("--source", required=True)
    c.add_argument("--schema", required=True)
    c.add_argument("--baseline", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--allow-unverified-fields", action="store_true")
    c.add_argument("--archetypes")
    c.add_argument("--assign", help="archetype assignments JSON")
    c.add_argument("--evidence")
    c.add_argument("--overrides")
    c.add_argument("--only", help="comma-separated source ids (test group)")

    args = ap.parse_args(argv)

    if args.cmd == "prepare-book":
        from .book import prepare, read_printed, write_prepared
        players, review = prepare(read_printed(args.printed))
        if Path(args.review).exists():
            raise SystemExit(f"Refusing to overwrite {args.review}")
        write_prepared(players, args.out)
        _dump(review, args.review)
        print(f"prepared {review['players']} players from {review['printed_rows']} printed rows; "
              f"{len(review['return_links'])} return rows linked, {len(review['return_only'])} return-only, "
              f"{len(review['flags'])} players flagged for review")
        return 0

    if args.cmd == "baseline":
        base = Baseline.from_play_export(args.play_export, position_codes_verified=args.position_codes_verified,
                                         exclude_tgids=tuple(args.exclude_tgid))
        base.save(args.out)
        print(f"wrote {args.out}: {base.meta['rostered_players']} rostered players, {base.meta['teams']} teams")
        for w in base.meta["team_size_warnings"]:
            print(f"  check team size: {w}")
        for k, n in base.meta["excluded"].items():
            print(f"  excluded {n} players: {k}")
        if args.report:
            _dump(base.report(), args.report)
        return 0

    if args.cmd == "profile-source":
        schema = load_schema(args.schema)
        _dump(profile_columns(load_roster(args.source, schema)), args.out)
        return 0

    if args.cmd == "match":
        schema = load_schema(args.schema)
        roster = load_roster(args.source, schema)
        refs = [{**r, "id": r.get("id") or r.get("ref_id")} for r in _read_records(args.reference)]
        manual = json.loads(Path(args.manual).read_text(encoding="utf-8")) if args.manual else None
        results = match_records(_source_identity_records(roster), refs, manual=manual)
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        _dump({"counts": counts, "results": [asdict(r) for r in results]}, args.out)
        return 0

    if args.cmd == "archetype-check":
        _dump(archetype_support(Baseline.load(args.baseline), load_archetypes(args.archetypes)), args.out)
        return 0

    schema = load_schema(args.schema)
    roster = load_roster(args.source, schema)
    base = Baseline.load(args.baseline)
    archetypes = load_archetypes(args.archetypes) if args.archetypes else {}
    assignments = resolve_assignments(args.assign, roster) if args.assign else {}
    result = convert(
        schema, roster, base, allow_unverified=args.allow_unverified_fields, archetypes=archetypes,
        assignments=assignments,
        evidence=load_evidence(args.evidence) if args.evidence else [],
        overrides=load_overrides(args.overrides) if args.overrides else [],
    )
    if args.only:
        keep = set(args.only.split(","))
        missing = keep - {p.source_id for p in result.players}
        if missing:
            print(f"warning: requested ids not converted: {sorted(missing)}", file=sys.stderr)
        result.players = [p for p in result.players if p.source_id in keep]
        result.skipped = [s for s in result.skipped if s["source_id"] in keep]
    diags = run_diagnostics(result, base)
    paths = write_outputs(result, diags, args.out_dir)
    sev = {k: sum(1 for d in diags if d["severity"] == k) for k in ("error", "warning", "info")}
    print(f"converted {len(result.players)} players, skipped {len(result.skipped)}; diagnostics {sev}")
    for p in paths.values():
        print(f"  {p}")
    return 1 if sev["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
