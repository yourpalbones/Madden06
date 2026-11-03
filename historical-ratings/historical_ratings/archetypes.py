"""Position archetypes: reviewable priors expressed in Madden 06 residual SD units.

An archetype offset of +0.8 on PAGI means "0.8 of the Madden 06 positional
residual SD above what the player's tier and source ratings imply". Offsets are
scaled by the real roster's spread, so they adapt to the baseline instead of
adding fixed points. They apply only to ratings that the source cannot supply;
source-derived ratings are never changed by an archetype.

The shipped definitions are priors (status ``prior``). ``archetype_support``
tests each prior against residual correlations in the actual Madden 06 roster
so a prior that contradicts the game's own data is flagged during calibration.

Caveat for reading that report: residuals are taken *after* removing the trend on
Overall (POVR). Ratings that feed the Overall formula at a position therefore
co-vary negatively by construction (at a fixed Overall, more of one means less of
another). A "conflict" between two high-weight Overall ingredients is weak
evidence against a prior; a conflict between low-weight tags is stronger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from .m06_schema import GROUPS, TARGET_TAGS


@dataclass(frozen=True)
class Archetype:
    group: str
    name: str
    offsets: dict[str, float]
    description: str
    status: str  # prior | calibrated


def load_archetypes(path: str | Path) -> dict[tuple[str, str], Archetype]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[tuple[str, str], Archetype] = {}
    for a in data["archetypes"]:
        groups = a["groups"] if "groups" in a else [a["group"]]
        for g in groups:
            if g not in GROUPS:
                raise ValueError(f"Archetype {a['name']}: unknown group {g}")
            for tag, off in a["offsets"].items():
                if tag not in TARGET_TAGS:
                    raise ValueError(f"Archetype {a['name']}: unknown tag {tag}")
                if not -2.0 <= float(off) <= 2.0:
                    raise ValueError(f"Archetype {a['name']}: offset {off} for {tag} outside +-2 SD")
            out[(g, a["name"])] = Archetype(g, a["name"], {k: float(v) for k, v in a["offsets"].items()},
                                            a.get("description", ""), a.get("status", "prior"))
    return out


def archetype_support(baseline, archetypes: dict[tuple[str, str], Archetype], min_abs_corr: float = 0.05) -> list[dict]:
    """For each archetype, compare offset-sign pairs with Madden 06 residual correlations.

    Two tags pushed in the same direction should co-vary positively in the real
    roster (after removing overall quality); opposite pushes should co-vary
    negatively. Returns agreement statistics per archetype for review.
    """
    report = []
    for (g, name), arch in sorted(archetypes.items()):
        if g not in baseline.groups or len(baseline.groups[g]) < 10:
            continue
        agree = disagree = neutral = 0
        conflicts = []
        for a, b in combinations(sorted(arch.offsets), 2):
            oa, ob = arch.offsets[a], arch.offsets[b]
            if oa == 0 or ob == 0:
                continue
            r = baseline.residual_corr(g, a, b)
            if abs(r) < min_abs_corr:
                neutral += 1
            elif (oa * ob > 0) == (r > 0):
                agree += 1
            else:
                disagree += 1
                conflicts.append({"tags": [a, b], "offset_signs": [oa > 0, ob > 0], "residual_corr": round(r, 3)})
        total = agree + disagree
        report.append({"group": g, "archetype": name, "status": arch.status, "agree": agree,
                       "disagree": disagree, "neutral": neutral,
                       "agreement": None if total == 0 else round(agree / total, 3), "conflicts": conflicts})
    return report
