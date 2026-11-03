"""Position-aware conversion of Madden '95 ratings into complete Madden 06 profiles.

Method (per Madden 06 position group):

1. **Source percentiles.** Each usable source rating becomes a mid-rank percentile
   among 1994 players at the same position group. Ties stay tied; ordering is
   preserved exactly. No constant multiplier is used anywhere.
2. **Comparable population.** Madden 06 reference players are restricted to the
   same depth per team as the source roster holds (e.g. if the source keeps ~2
   QBs per team, compare with the top 2 QBs of each Madden 06 team by POVR).
3. **Direct ratings** (``source_direct``): a verified primary source field is
   mapped through the Madden 06 quantile function for that tag and group.
4. **Tier.** An importance-weighted composite of the player's source percentiles
   (weights = how much each tag moves the fitted Madden 06 Overall at that
   position) is re-ranked and mapped to the Madden 06 POVR distribution.
5. **Missing ratings** (``position_distribution``): Madden 06 rating-vs-POVR
   trends give an expectation at the player's tier; residual covariance from the
   real roster then conditions every missing tag on the player's direct ratings
   (Gaussian conditional expectation). Confidence falls with the remaining SD.
6. **Archetype** priors, cited **historical evidence** and reviewed **manual
   overrides** are applied last, each recorded as its own provenance.

Every output rating carries method, numeric confidence, label and basis.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .archetypes import Archetype
from .baseline import Baseline, quantile
from .linalg import conditional_gaussian
from .m06_schema import RATING_MAX, RATING_MIN, TARGET_TAGS, clamp_rating
from .source import Interpretation, SourcePlayer, SourceRoster, SourceSchema

METHODS = {
    "source_direct": "Directly supported by a verified Madden '95 rating (percentile-mapped)",
    "source_partial": "Partly supported by a verified Madden '95 rating (blended with distribution estimate)",
    "source_unverified": "From a Madden '95 column whose meaning is NOT verified (explicitly allowed)",
    "historical_evidence": "Adjusted by cited historical evidence",
    "archetype": "Derived from the assigned player archetype prior",
    "position_distribution": "Estimated from Madden 06 positional distributions and correlations",
    "manual_override": "Manually set following review",
}
EVIDENCE_GRADE_CONFIDENCE = {"A": 0.7, "B": 0.55, "C": 0.4}


def confidence_label(c: float) -> str:
    return "high" if c >= 0.75 else "medium" if c >= 0.5 else "low"


@dataclass
class Evidence:
    source_id: str
    tag: str
    kind: str  # shift_sd | min | max
    amount: float
    citation: str
    grade: str
    note: str = ""


@dataclass
class Override:
    source_id: str
    tag: str
    value: int
    reason: str
    reviewer: str
    confidence: float = 0.7


def load_evidence(path: str | Path) -> list[Evidence]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for e in items:
        ev = Evidence(str(e["source_id"]), e["tag"], e["kind"], float(e["amount"]),
                      str(e.get("citation", "")).strip(), str(e.get("grade", "C")).upper(), e.get("note", ""))
        if ev.tag not in TARGET_TAGS or ev.kind not in ("shift_sd", "min", "max"):
            raise ValueError(f"Invalid evidence item {e}")
        if not ev.citation:
            raise ValueError(f"Evidence for {ev.source_id}/{ev.tag} has no citation")
        if ev.grade not in EVIDENCE_GRADE_CONFIDENCE:
            raise ValueError(f"Evidence grade must be A, B or C: {e}")
        out.append(ev)
    return out


def load_overrides(path: str | Path) -> list[Override]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for o in items:
        ov = Override(str(o["source_id"]), o["tag"], int(o["value"]), str(o.get("reason", "")).strip(),
                      str(o.get("reviewer", "")).strip(), float(o.get("confidence", 0.7)))
        if ov.tag not in TARGET_TAGS:
            raise ValueError(f"Override uses unknown tag {ov.tag}")
        if not RATING_MIN <= ov.value <= RATING_MAX:
            raise ValueError(f"Override {ov.source_id}/{ov.tag}={ov.value} outside {RATING_MIN}..{RATING_MAX}")
        if not ov.reason or not ov.reviewer:
            raise ValueError(f"Override {ov.source_id}/{ov.tag} needs reason and reviewer")
        out.append(ov)
    return out


@dataclass
class AttributeResult:
    value: int
    method: str
    confidence: float
    confidence_label: str
    basis: dict
    notes: list[str] = field(default_factory=list)


@dataclass
class PlayerResult:
    source_id: str
    name: str
    team: str
    source_position: str
    group: str
    source_raw: dict
    source_ratings: dict
    used_source_fields: list[dict]
    ignored_source_fields: list[dict]
    archetype: str | None
    tier: dict
    attributes: dict[str, AttributeResult]
    estimated_overall: dict
    flags: list[str] = field(default_factory=list)

    def values(self) -> dict[str, int]:
        return {t: a.value for t, a in self.attributes.items()}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["attributes"] = {t: asdict(a) for t, a in self.attributes.items()}
        return d


@dataclass
class ConversionResult:
    players: list[PlayerResult]
    skipped: list[dict]
    inputs: dict
    population: dict


def _midrank(values: list[float], v: float) -> float:
    less = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    return (less + 0.5 * equal) / len(values)


def _usable(interp: Interpretation, allow_unverified: bool) -> bool:
    return interp.verified or allow_unverified


def convert(
    schema: SourceSchema,
    roster: SourceRoster,
    baseline: Baseline,
    *,
    allow_unverified: bool = False,
    archetypes: dict[tuple[str, str], Archetype] | None = None,
    assignments: dict[str, str] | None = None,
    evidence: list[Evidence] | None = None,
    overrides: list[Override] | None = None,
) -> ConversionResult:
    archetypes, assignments = archetypes or {}, assignments or {}
    evidence, overrides = evidence or [], overrides or []
    skipped: list[dict] = []
    known_ids = {p.source_id for p in roster.players}
    for item in [*evidence, *overrides]:
        if item.source_id not in known_ids:
            raise ValueError(f"Evidence/override refers to unknown source id {item.source_id}")
    for sid in assignments:
        if sid not in known_ids:
            raise ValueError(f"Archetype assignment refers to unknown source id {sid}")

    # 1. group players
    by_group: dict[str, list[SourcePlayer]] = {}
    for p in roster.players:
        g = schema.position_map.get(p.position)
        if g is None:
            skipped.append({"source_id": p.source_id, "reason": f"source position {p.position!r} has no Madden 06 group"})
            continue
        if g not in baseline.groups or len(baseline.groups[g]) < 10:
            skipped.append({"source_id": p.source_id, "reason": f"baseline has too few {g} players"})
            continue
        by_group.setdefault(g, []).append(p)
    source_teams = max(1, len({p.team for p in roster.players}))

    results: list[PlayerResult] = []
    population: dict[str, dict] = {}
    for g in sorted(by_group):
        players = sorted(by_group[g], key=lambda p: p.source_id)
        depth_limit = max(1, round(len(players) / source_teams))
        ref = baseline.reference(g, depth_limit)
        population[g] = {"source_players": len(players), "depth_limit": depth_limit, "m06_reference_players": len(ref)}
        model = baseline.overall_models.get(g)
        sds = {t: baseline.trend(g, t).marginal_sd for t in TARGET_TAGS}
        importance = model.importance(sds) if model and model.status != "unreliable" else {}

        # 2. percentiles per interpretation (same column + same meaning)
        interp_values: dict[int, list[float]] = {}
        for p in players:
            for interp in schema.interpretations_for(p.position):
                if interp.column in p.ratings and _usable(interp, allow_unverified):
                    interp_values.setdefault(id(interp), []).append(p.ratings[interp.column])

        composites: dict[str, float] = {}
        per_player: dict[str, dict] = {}
        for p in players:
            used, ignored, tag_inputs = [], [], {}
            num = den = 0.0
            for interp in schema.interpretations_for(p.position):
                if interp.column not in p.ratings:
                    continue
                if not _usable(interp, allow_unverified):
                    ignored.append({"column": interp.column, "meaning": interp.meaning, "reason": "meaning not verified"})
                    continue
                pct = _midrank(interp_values[id(interp)], p.ratings[interp.column])
                used.append({"column": interp.column, "meaning": interp.meaning, "value": p.ratings[interp.column],
                             "percentile": round(pct, 4), "verified": interp.verified, "evidence": interp.evidence})
                w_int = 0.0
                for tag, role, weight in interp.targets:
                    tag_inputs.setdefault(tag, []).append((pct, weight, role, interp))
                    if role == "primary":
                        w_int += importance.get(tag, 1.0) * weight
                w_int = w_int or 0.25  # fields with no primary target still inform tier, lightly
                num += w_int * pct
                den += w_int
            interpreted_cols = {i.column for i in schema.interpretations_for(p.position)}
            for col in sorted(set(p.ratings) - interpreted_cols):
                ignored.append({"column": col, "reason": f"no interpretation for position {p.position}"})
            per_player[p.source_id] = {"used": used, "ignored": ignored, "tag_inputs": tag_inputs}
            if den > 0:
                composites[p.source_id] = num / den
        comp_values = sorted(composites.values())
        povr_sorted = sorted(r["POVR"] for r in ref)

        for p in players:
            info = per_player[p.source_id]
            if p.source_id not in composites:
                skipped.append({"source_id": p.source_id, "reason": "no usable source ratings (unverified or uninterpreted)",
                                "ignored": info["ignored"]})
                continue
            tier_p = _midrank(comp_values, composites[p.source_id])
            tier_povr = quantile(povr_sorted, tier_p)
            results.append(_convert_player(
                p, g, baseline, depth_limit, tier_p, tier_povr, composites[p.source_id], info,
                archetypes.get((g, assignments[p.source_id])) if p.source_id in assignments else None,
                assignments.get(p.source_id),
                [e for e in evidence if e.source_id == p.source_id],
                [o for o in overrides if o.source_id == p.source_id],
                model,
            ))
    inputs = {
        "source_sha256": roster.sha256, "schema_sha256": schema.sha256,
        "baseline_source_sha256": baseline.meta.get("source_sha256"),
        "baseline_sha256": baseline.meta.get("baseline_sha256"),
        "allow_unverified": allow_unverified,
        "source_platform": schema.platform, "source_roster_basis": schema.roster_basis,
    }
    results.sort(key=lambda r: r.source_id)
    skipped.sort(key=lambda s: s["source_id"])
    return ConversionResult(results, skipped, inputs, population)


def _convert_player(p, g, baseline, depth_limit, tier_p, tier_povr, composite, info,
                    archetype, archetype_name, evidence, overrides, model) -> PlayerResult:
    flags: list[str] = []
    attrs: dict[str, AttributeResult] = {}
    raw_est: dict[str, float] = {}

    # direct + partial source tags
    partial: dict[str, tuple[float, float, list]] = {}
    for tag, inputs in info["tag_inputs"].items():
        primaries = [x for x in inputs if x[2] == "primary"]
        chosen = primaries or inputs
        w = sum(x[1] for x in chosen)
        pct = sum(x[0] * x[1] for x in chosen) / w
        q = baseline.tag_quantile(g, tag, pct, depth_limit)
        verified = all(x[3].verified for x in chosen)
        fields_used = [{"column": x[3].column, "meaning": x[3].meaning, "percentile": round(x[0], 4)} for x in chosen]
        if primaries:
            distinct = len({r[tag] for r in baseline.reference(g, depth_limit)})
            conf = 0.8 if verified else 0.3
            if verified and distinct < 4:
                conf = 0.65
            method = "source_direct" if verified else "source_unverified"
            raw_est[tag] = q
            attrs[tag] = AttributeResult(0, method, conf, confidence_label(conf),
                                         {"percentile": round(pct, 4), "m06_quantile": round(q, 2), "source_fields": fields_used})
        else:
            partial[tag] = (q, min(0.6, max(x[1] for x in chosen)), fields_used, verified)

    direct = [t for t in TARGET_TAGS if t in attrs]
    missing = [t for t in TARGET_TAGS if t not in attrs]
    trends = {t: baseline.trend(g, t) for t in TARGET_TAGS}
    cov = baseline.residual_cov(g)
    idx = {t: i for i, t in enumerate(TARGET_TAGS)}
    known_dev = [raw_est[t] - trends[t].at(tier_povr) for t in direct]
    shifts, variances = conditional_gaussian(cov, [idx[t] for t in direct], [idx[t] for t in missing], known_dev)
    for tag, shift, var in zip(missing, shifts, variances):
        mu = trends[tag].at(tier_povr)
        est = mu + shift
        cond_sd = math.sqrt(var)
        msd = trends[tag].marginal_sd
        conf = 0.6 if msd < 0.5 else 0.15 + 0.45 * max(0.0, 1 - cond_sd / msd)
        basis = {"tier_povr": round(tier_povr, 2), "trend_expectation": round(mu, 2),
                 "conditional_shift": round(shift, 2), "conditional_sd": round(cond_sd, 2),
                 "positional_sd": round(msd, 2), "conditioned_on": direct}
        method = "position_distribution"
        notes = []
        if tag in partial:
            q, w, fields_used, verified = partial[tag]
            est = w * q + (1 - w) * est
            if verified:
                method, conf = "source_partial", max(conf, 0.55)
            else:
                method, conf = "source_unverified", min(conf, 0.3)
            basis.update({"source_quantile": round(q, 2), "source_weight": w, "source_fields": fields_used})
        raw_est[tag] = est
        attrs[tag] = AttributeResult(0, method, conf, confidence_label(conf), basis, notes)

    source_derived = set(direct) | set(partial)

    # archetype priors (purely estimated tags only)
    if archetype:
        for tag, off in sorted(archetype.offsets.items()):
            if tag in source_derived:
                continue
            unit = math.sqrt(cov[idx[tag]][idx[tag]])
            before = raw_est[tag]
            raw_est[tag] += off * unit
            a = attrs[tag]
            a.method = "archetype"
            a.confidence = min(a.confidence, 0.45)
            a.confidence_label = confidence_label(a.confidence)
            a.basis.update({"archetype": archetype.name, "archetype_status": archetype.status,
                            "offset_sd": off, "before_archetype": round(before, 2)})
    elif archetype_name:
        flags.append(f"archetype {archetype_name!r} not defined for group {g}")

    # cited historical evidence (purely estimated tags only)
    for ev in evidence:
        if ev.tag in source_derived:
            flags.append(f"evidence for {ev.tag} not applied: tag is source-derived; use a reviewed override")
            continue
        before = raw_est[ev.tag]
        if ev.kind == "shift_sd":
            raw_est[ev.tag] += ev.amount * math.sqrt(cov[idx[ev.tag]][idx[ev.tag]])
        elif ev.kind == "min":
            raw_est[ev.tag] = max(raw_est[ev.tag], ev.amount)
        else:
            raw_est[ev.tag] = min(raw_est[ev.tag], ev.amount)
        a = attrs[ev.tag]
        a.method = "historical_evidence"
        a.confidence = EVIDENCE_GRADE_CONFIDENCE[ev.grade]
        a.confidence_label = confidence_label(a.confidence)
        a.basis.setdefault("evidence", []).append({"kind": ev.kind, "amount": ev.amount, "citation": ev.citation,
                                                   "grade": ev.grade, "before": round(before, 2), "note": ev.note})

    # clamp to what Madden 06 actually uses at this position, then to 0..99
    group_rows = baseline.groups[g]
    for tag in TARGET_TAGS:
        lo = min(r[tag] for r in group_rows)
        hi = max(r[tag] for r in group_rows)
        v = raw_est[tag]
        if v < lo or v > hi:
            attrs[tag].notes.append(f"clamped {v:.1f} to Madden 06 {g} range {lo}..{hi}")
            v = min(max(v, lo), hi)
        attrs[tag].value = clamp_rating(v)

    for ov in overrides:
        a = attrs[ov.tag]
        a.basis = {"previous_value": a.value, "previous_method": a.method, "reason": ov.reason, "reviewer": ov.reviewer}
        a.value, a.method = ov.value, "manual_override"
        a.confidence = ov.confidence
        a.confidence_label = confidence_label(ov.confidence)

    values = {t: attrs[t].value for t in TARGET_TAGS}
    if model:
        est_ovr = {"value": model.predict_int(values), "model_status": model.status, "rounding": model.rounding,
                   "model_r2": round(model.r2, 4), "model_exact_round_share": round(model.exact_round_share, 4),
                   "tier_povr": round(tier_povr, 2),
                   "note": "Fitted to stored POVR of the real roster; the game is not known to recalculate POVR."}
    else:
        est_ovr = {"value": None, "model_status": "unavailable", "tier_povr": round(tier_povr, 2)}
    return PlayerResult(
        source_id=p.source_id, name=p.name, team=p.team, source_position=p.position, group=g,
        source_raw=dict(p.raw), source_ratings=dict(p.ratings),
        used_source_fields=info["used"], ignored_source_fields=info["ignored"],
        archetype=archetype.name if archetype else None,
        tier={"composite": round(composite, 4), "percentile": round(tier_p, 4), "povr": round(tier_povr, 2),
              "depth_limit": depth_limit},
        attributes={t: attrs[t] for t in TARGET_TAGS}, estimated_overall=est_ovr, flags=flags,
    )
