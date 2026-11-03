"""Madden 06 positional baselines learned from the real default roster.

Input is a read-only export of TEMPLATE.DAT member 1 ``PLAY`` records produced by
``tools/export_m06_play_table.py`` (which calls the editor's own
``game_formats.load_players``). Everything the converter knows about Madden 06
rating distributions comes from that export; nothing is assumed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .linalg import lstsq
from .m06_schema import (
    GROUPS, MODEL_TAGS, PPOS_CONVENTION, STARTERS_PER_TEAM, TARGET_TAGS,
    check_position_codes, group_for_code,
)

ROW_COLUMNS = ("depth", "TGID", "PGID", "PPOS", "POVR") + MODEL_TAGS
FORMAT = "historical_ratings.baseline/2"


class BaselineError(ValueError):
    pass


def _load_export(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["players"] if isinstance(data, dict) else data
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _count(items) -> dict:
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def quantile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated quantile, p in [0, 1]."""
    if not sorted_values:
        raise BaselineError("Empty distribution")
    p = min(1.0, max(0.0, p))
    pos = p * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _mean_sd(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    return mean, math.sqrt(var)


@dataclass(frozen=True)
class Trend:
    intercept: float
    slope: float
    residual_sd: float
    marginal_sd: float

    def at(self, povr: float) -> float:
        return self.intercept + self.slope * povr


@dataclass(frozen=True)
class OverallModel:
    group: str
    tags: tuple[str, ...]
    coefficients: tuple[float, ...]  # intercept first
    r2: float
    max_abs_error: float
    exact_round_share: float
    n: int
    rounding: str = "round"  # integer rule that best reproduces stored POVR: round | floor

    @property
    def status(self) -> str:
        if self.exact_round_share >= 0.97 and self.max_abs_error <= 1.5:
            return "engine_consistent"
        if self.r2 >= 0.9:
            return "approximate"
        return "unreliable"

    def predict(self, ratings: dict[str, float]) -> float:
        value = self.coefficients[0] + sum(c * ratings[t] for c, t in zip(self.coefficients[1:], self.tags))
        return max(0.0, min(99.0, value))

    def predict_int(self, ratings: dict[str, float]) -> int:
        v = self.predict(ratings)
        return int(math.floor(v + 1e-9)) if self.rounding == "floor" else int(v + 0.5)

    def importance(self, sds: dict[str, float]) -> dict[str, float]:
        """|coefficient x positional SD|: how much each tag moves Overall in practice."""
        return {t: abs(c) * sds.get(t, 0.0) for c, t in zip(self.coefficients[1:], self.tags)}


class Baseline:
    def __init__(self, groups: dict[str, list[dict]], meta: dict):
        self.groups = groups
        self.meta = meta

    # ------------------------------------------------------------------ build
    @classmethod
    def from_play_export(
        cls,
        path: str | Path,
        *,
        position_codes_verified: bool = False,
        convention: dict[int, str] | None = None,
        exclude_tgids: tuple[int, ...] = (),
    ) -> "Baseline":
        path = Path(path)
        raw = _load_export(path)
        convention = convention or PPOS_CONVENTION
        players: list[dict] = []
        excluded: dict[str, int] = {}
        team_names: dict[int, str] = {}
        for r in raw:
            try:
                rec = {k: int(r[k]) for k in ("TGID", "PGID", "PPOS", "POVR") + MODEL_TAGS}
            except (KeyError, TypeError, ValueError) as exc:
                raise BaselineError(f"Export row lacks integer field: {exc}") from exc
            team_val = r.get("_team", "")
            team = team_val.strip() if isinstance(team_val, str) else ("team" if team_val else "")
            if member := r.get("_member"):
                if int(member) != 1:
                    excluded["not member 1"] = excluded.get("not member 1", 0) + 1
                    continue
            if rec["TGID"] in exclude_tgids or not team:
                key = f"TGID {rec['TGID']}" + ("" if team else " (no team record)")
                excluded[key] = excluded.get(key, 0) + 1
                continue
            team_names.setdefault(rec["TGID"], team)
            players.append(rec)
        if not players:
            raise BaselineError("No rostered players in export")
        failures = check_position_codes(players, convention)
        if failures and not position_codes_verified:
            raise BaselineError(
                "PPOS convention failed data checks; supply a verified convention:\n  "
                + "\n  ".join(failures)
            )
        groups: dict[str, list[dict]] = {g: [] for g in GROUPS}
        for rec in players:
            g = group_for_code(rec["PPOS"], convention)
            if g:
                groups[g].append(rec)
        for g, rows in groups.items():
            by_team: dict[int, list[dict]] = {}
            for rec in rows:
                by_team.setdefault(rec["TGID"], []).append(rec)
            for team_rows in by_team.values():
                team_rows.sort(key=lambda r: (-r["POVR"], r["PGID"]))
                for depth, rec in enumerate(team_rows):
                    rec["depth"] = depth
            rows.sort(key=lambda r: (r["TGID"], r["depth"]))
        meta = {
            "source_file": path.name,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rostered_players": len(players),
            "excluded": dict(sorted(excluded.items())),
            "teams": len({p["TGID"] for p in players}),
            "team_sizes": {str(t): {"team": team_names[t], "players": n}
                           for t, n in sorted(_count(p["TGID"] for p in players).items())},
            # NFL teams carry roughly 45-55 players; a much larger "team" is likely a
            # free-agent or other pseudo-team and should be excluded with --exclude-tgid.
            "team_size_warnings": [f"TGID {t} ({team_names[t]}): {n} players"
                                   for t, n in sorted(_count(p["TGID"] for p in players).items())
                                   if n > 65 or n < 35],
            "position_convention": {str(k): v for k, v in sorted(convention.items())},
            "position_checks_failed": failures,
            "position_codes_verified_by_user": position_codes_verified,
        }
        return cls(groups, meta)

    # ------------------------------------------------------------------ persistence
    def save(self, path: str | Path) -> None:
        payload = {
            "format": FORMAT,
            "meta": self.meta,
            "columns": list(ROW_COLUMNS),
            "groups": {g: [[r[c] for c in ROW_COLUMNS] for r in rows] for g, rows in self.groups.items()},
        }
        Path(path).write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Baseline":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != FORMAT:
            raise BaselineError(f"Not a {FORMAT} file; rebuild it with the 'baseline' command")
        cols = payload["columns"]
        groups = {g: [dict(zip(cols, row)) for row in rows] for g, rows in payload["groups"].items()}
        b = cls(groups, payload["meta"])
        b.meta["baseline_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return b

    # ------------------------------------------------------------------ queries
    def teams(self) -> int:
        return int(self.meta.get("teams") or len({r["TGID"] for rows in self.groups.values() for r in rows}))

    def reference(self, group: str, depth_limit: int | None = None) -> list[dict]:
        rows = self.groups[group]
        if depth_limit is None:
            return rows
        limited = [r for r in rows if r["depth"] < max(1, depth_limit)]
        return limited or rows

    def sorted_values(self, group: str, tag: str, depth_limit: int | None = None) -> list[float]:
        return sorted(r[tag] for r in self.reference(group, depth_limit))

    def tag_quantile(self, group: str, tag: str, p: float, depth_limit: int | None = None) -> float:
        return quantile(self.sorted_values(group, tag, depth_limit), p)

    def summary(self, group: str, tag: str, depth_limit: int | None = None) -> dict[str, float]:
        vals = self.sorted_values(group, tag, depth_limit)
        mean, sd = _mean_sd(vals)
        return {"n": len(vals), "min": vals[0], "p10": quantile(vals, .1), "median": quantile(vals, .5),
                "p90": quantile(vals, .9), "max": vals[-1], "mean": round(mean, 2), "sd": round(sd, 2)}

    def tier_summary(self, group: str) -> dict[str, dict[str, float]]:
        starters = STARTERS_PER_TEAM[group]
        out = {}
        for label, pred in (("starter", lambda r: r["depth"] < starters), ("backup", lambda r: r["depth"] >= starters)):
            vals = sorted(r["POVR"] for r in self.groups[group] if pred(r))
            if vals:
                out[label] = {"n": len(vals), "min": vals[0], "median": quantile(vals, .5), "max": vals[-1]}
        return out

    @cached_property
    def _trends(self) -> dict[str, dict[str, Trend]]:
        out: dict[str, dict[str, Trend]] = {}
        for g, rows in self.groups.items():
            out[g] = {}
            if len(rows) < 3:
                continue
            ov = [r["POVR"] for r in rows]
            for t in MODEL_TAGS:
                ys = [r[t] for r in rows]
                _, msd = _mean_sd(ys)
                a, b = lstsq([[1.0, o] for o in ov], ys)
                resid = [y - (a + b * o) for y, o in zip(ys, ov)]
                rsd = math.sqrt(sum(e * e for e in resid) / max(1, len(resid) - 2))
                out[g][t] = Trend(a, b, rsd, msd)
        return out

    def trend(self, group: str, tag: str) -> Trend:
        return self._trends[group][tag]

    @cached_property
    def _residual_cov(self) -> dict[str, list[list[float]]]:
        out = {}
        for g, rows in self.groups.items():
            if len(rows) < 3:
                continue
            tr = self._trends[g]
            res = [[r[t] - tr[t].at(r["POVR"]) for t in MODEL_TAGS] for r in rows]
            n, k = len(res), len(MODEL_TAGS)
            cov = [[0.0] * k for _ in range(k)]
            for row in res:
                for i in range(k):
                    for j in range(i, k):
                        cov[i][j] += row[i] * row[j]
            for i in range(k):
                for j in range(i, k):
                    cov[i][j] /= max(1, n - 1)
                    cov[j][i] = cov[i][j]
            out[g] = cov
        return out

    def residual_cov(self, group: str) -> list[list[float]]:
        return self._residual_cov[group]

    def residual_corr(self, group: str, a: str, b: str) -> float:
        cov = self.residual_cov(group)
        i, j = MODEL_TAGS.index(a), MODEL_TAGS.index(b)
        denom = math.sqrt(cov[i][i] * cov[j][j])
        return cov[i][j] / denom if denom > 1e-9 else 0.0

    # ------------------------------------------------------------------ returners
    def returner_ids(self, tag: str, per_team: int) -> frozenset[int]:
        """PGIDs of each team's top ``per_team`` players by ``tag`` across all groups."""
        key = (tag, per_team)
        cache = self.__dict__.setdefault("_returner_cache", {})
        if key not in cache:
            by_team: dict[int, list[dict]] = {}
            for rows in self.groups.values():
                for r in rows:
                    by_team.setdefault(r["TGID"], []).append(r)
            ids = set()
            for rows in by_team.values():
                rows = sorted(rows, key=lambda r: (-r[tag], r["PGID"]))
                ids.update(r["PGID"] for r in rows[:per_team])
            cache[key] = frozenset(ids)
        return cache[key]

    def returner_values(self, tag: str, per_team: int) -> list[float]:
        ids = self.returner_ids(tag, per_team)
        return sorted(r[tag] for rows in self.groups.values() for r in rows if r["PGID"] in ids)

    def non_returner_values(self, group: str, tag: str, per_team: int, depth_limit: int | None = None) -> list[float]:
        ids = self.returner_ids(tag, per_team)
        vals = sorted(r[tag] for r in self.reference(group, depth_limit) if r["PGID"] not in ids)
        return vals or self.sorted_values(group, tag, depth_limit)

    @cached_property
    def overall_models(self) -> dict[str, OverallModel]:
        models = {}
        for g, rows in self.groups.items():
            if len(rows) < len(TARGET_TAGS) + 5:
                continue
            tags = tuple(t for t in TARGET_TAGS if _mean_sd([r[t] for r in rows])[1] > 0)
            xs = [[1.0] + [float(r[t]) for t in tags] for r in rows]
            ys = [float(r["POVR"]) for r in rows]
            coef = lstsq(xs, ys)
            preds = [sum(c * x for c, x in zip(coef, row)) for row in xs]
            mean_y = sum(ys) / len(ys)
            ss_tot = sum((y - mean_y) ** 2 for y in ys) or 1.0
            ss_res = sum((y - p) ** 2 for y, p in zip(ys, preds))
            clipped = [max(0.0, min(99.0, p)) for p in preds]
            errs = [abs(y - p) for y, p in zip(ys, clipped)]
            shares = {
                "round": sum(1 for y, p in zip(ys, clipped) if int(p + 0.5) == int(y)) / len(ys),
                "floor": sum(1 for y, p in zip(ys, clipped) if int(math.floor(p + 1e-9)) == int(y)) / len(ys),
            }
            rule = max(shares, key=lambda k: (shares[k], k == "round"))
            models[g] = OverallModel(g, tags, tuple(coef), 1 - ss_res / ss_tot, max(errs), shares[rule], len(ys), rule)
        return models

    def report(self) -> dict:
        """Human-reviewable summary: distributions, tiers, overall-formula fit."""
        out = {"meta": self.meta, "groups": {}}
        for g in GROUPS:
            if not self.groups.get(g):
                continue
            m = self.overall_models.get(g)
            out["groups"][g] = {
                "players": len(self.groups[g]),
                "tiers": self.tier_summary(g),
                "overall_model": None if m is None else {
                    "status": m.status, "r2": round(m.r2, 4), "max_abs_error": round(m.max_abs_error, 2),
                    "exact_round_share": round(m.exact_round_share, 4), "rounding": m.rounding, "n": m.n,
                    "weights": {t: round(c, 4) for t, c in zip(m.tags, m.coefficients[1:]) if abs(c) >= 0.005},
                    "intercept": round(m.coefficients[0], 3),
                },
                "ratings": {t: self.summary(g, t) for t in MODEL_TAGS},
            }
        return out
