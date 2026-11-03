"""Checks for suspicious converted ratings, before anything reaches a game file."""

from __future__ import annotations

from .baseline import Baseline, quantile
from .convert import ConversionResult
from .m06_schema import RATING_MAX, RATING_MIN, RATING_FIELDS, TARGET_TAGS


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return 1.0 if va == 0 or vb == 0 else cov / (va * vb)


def _d(severity: str, code: str, message: str, source_id: str = "", group: str = "", tag: str = "") -> dict:
    return {"severity": severity, "code": code, "source_id": source_id, "group": group, "tag": tag, "message": message}


def run_diagnostics(result: ConversionResult, baseline: Baseline) -> list[dict]:
    out: list[dict] = []
    for s in result.skipped:
        out.append(_d("warning", "not_converted", s["reason"], s["source_id"]))
    by_group: dict[str, list] = {}
    for p in result.players:
        by_group.setdefault(p.group, []).append(p)
        model = baseline.overall_models.get(p.group)
        key_tags: list[str] = []
        if model and model.status != "unreliable":
            sds = {t: baseline.trend(p.group, t).marginal_sd for t in TARGET_TAGS}
            imp = model.importance(sds)
            key_tags = [t for t, _ in sorted(imp.items(), key=lambda kv: -kv[1])[:3]]
        low = 0
        for tag, a in p.attributes.items():
            if not RATING_MIN <= a.value <= RATING_MAX:
                out.append(_d("error", "out_of_bounds", f"{tag}={a.value}", p.source_id, p.group, tag))
            if a.confidence_label == "low":
                low += 1
            if a.method == "source_unverified":
                out.append(_d("warning", "unverified_source_field",
                              f"{RATING_FIELDS[tag]} comes from a source column whose meaning is unverified",
                              p.source_id, p.group, tag))
            for note in a.notes:
                out.append(_d("info", "clamped", note, p.source_id, p.group, tag))
        for tag in key_tags:
            p05 = quantile(baseline.sorted_values(p.group, tag), 0.05)
            if p.attributes[tag].value < p05:
                out.append(_d("warning", "key_rating_below_p05",
                              f"{RATING_FIELDS[tag]} {p.attributes[tag].value} is below the Madden 06 {p.group} "
                              f"5th percentile ({p05:.0f}); key rating for Overall at this position",
                              p.source_id, p.group, tag))
        ovr = p.estimated_overall.get("value")
        if ovr is not None and abs(ovr - p.tier["povr"]) > 6:
            out.append(_d("warning", "overall_tier_mismatch",
                          f"estimated Overall {ovr} vs tier {p.tier['povr']:.0f}", p.source_id, p.group))
        if low / len(p.attributes) > 0.6:
            out.append(_d("info", "mostly_low_confidence",
                          f"{low}/{len(p.attributes)} ratings are low confidence", p.source_id, p.group))
        for f in p.flags:
            out.append(_d("warning", "player_flag", f, p.source_id, p.group))

    for g, players in sorted(by_group.items()):
        depth = result.population[g]["depth_limit"]
        # Order preservation for every source-direct tag.
        for tag in TARGET_TAGS:
            pts = [(p.attributes[tag].basis["percentile"], p.attributes[tag].value) for p in players
                   if p.attributes[tag].method == "source_direct"]
            if len(pts) >= 5:
                rho = spearman([a for a, _ in pts], [b for _, b in pts])
                if rho < 0.95:
                    out.append(_d("error", "order_not_preserved",
                                  f"Spearman {rho:.3f} between source percentile and output", group=g, tag=tag))
        # Systematic distribution shift versus comparable Madden 06 players.
        if len(players) >= 10:
            for tag in TARGET_TAGS:
                ref = baseline.summary(g, tag, depth)
                mean = sum(p.attributes[tag].value for p in players) / len(players)
                if ref["sd"] > 0 and abs(mean - ref["mean"]) > 0.5 * ref["sd"]:
                    out.append(_d("warning", "distribution_shift",
                                  f"converted mean {mean:.1f} vs Madden 06 {ref['mean']:.1f} (sd {ref['sd']:.1f})",
                                  group=g, tag=tag))
            # Overall inflation at the top end.
            ref_ovr = [r["POVR"] for r in baseline.reference(g, depth)]
            conv = [p.estimated_overall["value"] for p in players if p.estimated_overall.get("value") is not None]
            if conv:
                expected = sum(1 for v in ref_ovr if v >= 90) / len(ref_ovr) * len(conv)
                actual = sum(1 for v in conv if v >= 90)
                if actual - expected >= 2 and actual > 1.5 * expected:
                    out.append(_d("warning", "overall_inflation",
                                  f"{actual} players at 90+ Overall; comparable Madden 06 share implies ~{expected:.1f}",
                                  group=g))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda d: (order[d["severity"]], d["code"], d["group"], d["source_id"], d["tag"]))
    return out
