import csv
import json
import tempfile
import unittest
from pathlib import Path

from historical_ratings.archetypes import archetype_support, load_archetypes
from historical_ratings.baseline import Baseline, BaselineError
from historical_ratings.convert import METHODS, Evidence, Override, convert, load_evidence, load_overrides
from historical_ratings.diagnostics import run_diagnostics, spearman
from historical_ratings.export import write_outputs
from historical_ratings.m06_schema import PPOS_CONVENTION, RATING_FIELDS, TARGET_TAGS, clamp_rating
from historical_ratings.source import SchemaError, load_roster, load_schema

from synthetic import make_schema, write_fixture_files

REPO = Path(__file__).resolve().parents[1]

EDITOR_VERIFIED_TAGS = ("PSPD", "PACC", "PSTR", "PAGI", "PAWR", "PTHP", "PTHA", "PCTH", "PTAK", "PCAR",
                        "PJMP", "PBTK", "PPBK", "PRBK", "PKPR", "PKAC", "PKRT", "PIMP", "PSTA", "PINJ", "PTGH")


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.files = write_fixture_files(cls.tmp)
        cls.baseline = Baseline.from_play_export(cls.files["play"])
        cls.schema = load_schema(cls.files["schema"])
        cls.roster = load_roster(cls.files["source"], cls.schema)
        cls.result = convert(cls.schema, cls.roster, cls.baseline)

    def player(self, sid, result=None):
        return next(p for p in (result or self.result).players if p.source_id == sid)


class TargetSchemaTests(unittest.TestCase):
    def test_exactly_the_21_editor_verified_tags_in_editor_order(self):
        self.assertEqual(TARGET_TAGS, EDITOR_VERIFIED_TAGS)
        self.assertEqual(len(RATING_FIELDS), 21)

    def test_clamp_bounds(self):
        self.assertEqual(clamp_rating(-5), 0)
        self.assertEqual(clamp_rating(150), 99)
        self.assertEqual(clamp_rating(70.5), 71)


class BaselineTests(Fixture):
    def test_free_agents_without_team_excluded_and_reported(self):
        self.assertEqual(self.baseline.meta["excluded"], {"TGID 1009 (no team record)": 5})

    def test_position_convention_checked_against_data(self):
        scrambled = dict(PPOS_CONVENTION)
        scrambled[0], scrambled[19] = scrambled[19], scrambled[0]  # swap QB and K
        with self.assertRaises(BaselineError):
            Baseline.from_play_export(self.files["play"], convention=scrambled)

    def test_overall_model_recovers_linear_formula(self):
        for g, m in self.baseline.overall_models.items():
            self.assertGreater(m.r2, 0.99, g)
            self.assertLessEqual(m.max_abs_error, 1.0, g)
            self.assertIn(m.status, ("engine_consistent", "approximate"))

    def test_save_load_roundtrip(self):
        path = self.tmp / "b.json"
        self.baseline.save(path)
        again = Baseline.load(path)
        self.assertEqual(again.groups, self.baseline.groups)
        self.assertEqual(again.report()["groups"], self.baseline.report()["groups"])


class ConversionTests(Fixture):
    def test_every_player_gets_all_21_bounded_ratings_with_provenance(self):
        self.assertEqual(len(self.result.players) + len(self.result.skipped), len(self.roster.players))
        self.assertEqual([s["source_id"] for s in self.result.skipped], ["T00-KR"])
        self.assertIn("return-only", self.result.skipped[0]["reason"])
        for p in self.result.players:
            self.assertEqual(tuple(p.attributes), TARGET_TAGS)
            rows = self.baseline.groups[p.group]
            for tag, a in p.attributes.items():
                self.assertIsInstance(a.value, int)
                self.assertTrue(0 <= a.value <= 99)
                self.assertTrue(min(r[tag] for r in rows) <= a.value <= max(r[tag] for r in rows))
                self.assertIn(a.method, METHODS)
                self.assertTrue(0.0 <= a.confidence <= 1.0)
                self.assertIn(a.confidence_label, ("high", "medium", "low"))

    def test_source_values_preserved_verbatim(self):
        with self.files["source"].open(newline="", encoding="utf-8") as fh:
            rows = {r["id"]: r for r in csv.DictReader(fh)}
        for p in self.result.players:
            self.assertEqual(p.source_raw, rows[p.source_id])
            for col, v in p.source_ratings.items():
                self.assertEqual(str(v), rows[p.source_id][col])

    def test_not_a_constant_multiplier(self):
        # Same fake-speed source value maps differently at different positions.
        by_val = {}
        for p in self.result.players:
            v = p.source_ratings["r1"]
            by_val.setdefault(v, {}).setdefault(p.group, set()).add(p.attributes["PSPD"].value)
        differing = [v for v, groups in by_val.items()
                     if len({min(s) for s in groups.values()}) > 1]
        self.assertTrue(differing)
        ratios = {p.attributes["PSPD"].value / p.source_ratings["r1"] for p in self.result.players
                  if p.group == "WR" and p.source_ratings["r1"]}
        self.assertGreater(len(ratios), 3)

    def test_order_and_ties_preserved_for_direct_ratings(self):
        for g in ("QB", "WR", "T", "K"):
            players = [p for p in self.result.players if p.group == g]
            pairs = sorted((p.source_ratings["r1"], p.attributes["PSPD"].value) for p in players)
            for (s1, v1), (s2, v2) in zip(pairs, pairs[1:]):
                self.assertLessEqual(v1, v2, g)
                if s1 == s2:
                    self.assertEqual(v1, v2, g)
            self.assertGreater(spearman([a for a, _ in pairs], [b for _, b in pairs]), 0.95)

    def test_direct_fields_marked_source_direct(self):
        qb = next(p for p in self.result.players if p.group == "QB")
        for tag in ("PSPD", "PAGI", "PTHP", "PTHA"):
            self.assertEqual(qb.attributes[tag].method, "source_direct")
        self.assertEqual(qb.attributes["PAWR"].method, "position_distribution")
        hb = next(p for p in self.result.players if p.group == "HB")
        self.assertEqual(hb.attributes["PSTR"].method, "source_partial")

    def test_elite_vs_backup_separation(self):
        qbs = sorted((p for p in self.result.players if p.group == "QB"), key=lambda p: p.tier["percentile"])
        low, high = qbs[0], qbs[-1]
        self.assertGreater(high.estimated_overall["value"], low.estimated_overall["value"] + 10)
        self.assertLess(high.estimated_overall["value"], 100)

    def test_repeatable_byte_identical_outputs(self):
        outs = []
        for i in range(2):
            res = convert(self.schema, self.roster, self.baseline)
            paths = write_outputs(res, run_diagnostics(res, self.baseline), self.tmp / f"run{i}")
            outs.append({k: p.read_bytes() for k, p in paths.items()})
        self.assertEqual(outs[0], outs[1])

    def test_clean_fixture_has_no_diagnostic_errors(self):
        diags = run_diagnostics(self.result, self.baseline)
        self.assertEqual([d for d in diags if d["severity"] == "error"], [])


class SourceSafetyTests(Fixture):
    def test_unverified_fields_are_not_used_by_default(self):
        path = self.tmp / "unverified.json"
        path.write_text(json.dumps(make_schema(verified=False)))
        schema = load_schema(path)
        roster = load_roster(self.files["source"], schema)
        res = convert(schema, roster, self.baseline)
        self.assertEqual(res.players, [])
        self.assertEqual(len(res.skipped), len(roster.players))

    def test_unverified_fields_allowed_only_explicitly_and_labelled(self):
        path = self.tmp / "unverified2.json"
        path.write_text(json.dumps(make_schema(verified=False)))
        schema = load_schema(path)
        res = convert(schema, load_roster(self.files["source"], schema), self.baseline, allow_unverified=True)
        qb = next(p for p in res.players if p.group == "QB")
        self.assertEqual(qb.attributes["PTHP"].method, "source_unverified")
        self.assertEqual(qb.attributes["PTHP"].confidence_label, "low")
        codes = {d["code"] for d in run_diagnostics(res, self.baseline)}
        self.assertIn("unverified_source_field", codes)

    def test_unverified_supporting_field_never_labelled_source_partial(self):
        path = self.tmp / "unverified3.json"
        path.write_text(json.dumps(make_schema(verified=False)))
        schema = load_schema(path)
        res = convert(schema, load_roster(self.files["source"], schema), self.baseline, allow_unverified=True)
        hb = next(p for p in res.players if p.group == "HB")
        self.assertEqual(hb.attributes["PSTR"].method, "source_unverified")
        self.assertLessEqual(hb.attributes["PSTR"].confidence, 0.3)
        self.assertNotIn("source_partial", {a.method for p in res.players for a in p.attributes.values()})

    def test_out_of_range_source_rejected_not_clamped(self):
        bad = self.tmp / "bad.csv"
        text = self.files["source"].read_text().splitlines()
        cols = text[1].split(",")
        cols[-1] = "16"
        bad.write_text("\n".join([text[0], ",".join(cols)] + text[2:]) + "\n")
        with self.assertRaises(SchemaError):
            load_roster(bad, self.schema)

    def test_verified_interpretation_requires_evidence(self):
        data = make_schema()
        data["interpretations"][0]["evidence"] = ""
        path = self.tmp / "noevidence.json"
        path.write_text(json.dumps(data))
        with self.assertRaises(SchemaError):
            load_schema(path)

    def test_unknown_target_tag_rejected(self):
        data = make_schema()
        data["interpretations"][0]["targets"] = [{"tag": "PMCV", "role": "primary"}]
        path = self.tmp / "badtag.json"
        path.write_text(json.dumps(data))
        with self.assertRaises(SchemaError):
            load_schema(path)


class AdjustmentTests(Fixture):
    def test_manual_override_wins_and_keeps_previous(self):
        sid = "T00-QB1"
        before = self.player(sid).attributes["PAWR"].value
        res = convert(self.schema, self.roster, self.baseline,
                      overrides=[Override(sid, "PAWR", 88, "film review", "tester")])
        a = self.player(sid, res).attributes["PAWR"]
        self.assertEqual((a.value, a.method), (88, "manual_override"))
        self.assertEqual(a.basis["previous_value"], before)

    def test_override_and_evidence_files_validated(self):
        p = self.tmp / "ov.json"
        p.write_text(json.dumps([{"source_id": "T00-QB1", "tag": "PAWR", "value": 88}]))
        with self.assertRaises(ValueError):
            load_overrides(p)  # missing reason/reviewer
        e = self.tmp / "ev.json"
        e.write_text(json.dumps([{"source_id": "T00-QB1", "tag": "PAWR", "kind": "shift_sd", "amount": 1}]))
        with self.assertRaises(ValueError):
            load_evidence(e)  # missing citation

    def test_evidence_applies_only_to_estimated_tags(self):
        sid = "T00-HB1"
        ev = [Evidence(sid, "PACC", "shift_sd", 1.0, "test citation", "B"),
              Evidence(sid, "PSPD", "shift_sd", 1.0, "test citation", "A")]
        res = convert(self.schema, self.roster, self.baseline, evidence=ev)
        p, base = self.player(sid, res), self.player(sid)
        self.assertEqual(p.attributes["PACC"].method, "historical_evidence")
        self.assertGreaterEqual(p.attributes["PACC"].value, base.attributes["PACC"].value)
        self.assertEqual(p.attributes["PSPD"].value, base.attributes["PSPD"].value)
        self.assertEqual(p.attributes["PSPD"].method, "source_direct")
        self.assertTrue(any("PSPD" in f for f in p.flags))

    def test_archetype_shifts_estimates_never_direct(self):
        arch = load_archetypes(REPO / "schemas" / "archetypes.v1.json")
        sid = "T01-HB1"
        res = convert(self.schema, self.roster, self.baseline, archetypes=arch, assignments={sid: "power"})
        p, base = self.player(sid, res), self.player(sid)
        self.assertEqual(p.archetype, "power")
        for tag in ("PSPD", "PAGI", "PCTH", "PBTK"):  # source-derived
            self.assertEqual(p.attributes[tag].value, base.attributes[tag].value)
        self.assertEqual(p.attributes["PACC"].method, "archetype")
        self.assertLessEqual(p.attributes["PACC"].confidence, 0.45)
        # PSTR is partly source-derived (supporting field) for HBs: archetype must not touch it.
        self.assertEqual(p.attributes["PSTR"].method, "source_partial")
        self.assertEqual(p.attributes["PSTR"].value, base.attributes["PSTR"].value)

    def test_archetype_support_report_runs_on_baseline(self):
        arch = load_archetypes(REPO / "schemas" / "archetypes.v1.json")
        rep = archetype_support(self.baseline, arch)
        hb_elusive = next(r for r in rep if r["group"] == "HB" and r["archetype"] == "elusive")
        self.assertIsNotNone(hb_elusive["agreement"])
        # The synthetic HB style axis (agility up, strength/break-tackle down) is visible in residuals.
        self.assertLess(self.baseline.residual_corr("HB", "PAGI", "PSTR"), -0.2)
        self.assertLess(self.baseline.residual_corr("HB", "PAGI", "PBTK"), -0.1)
        conflict_pairs = {tuple(c["tags"]) for c in hb_elusive["conflicts"]}
        self.assertNotIn(("PAGI", "PSTR"), conflict_pairs)

    def test_unknown_ids_in_adjustments_rejected(self):
        with self.assertRaises(ValueError):
            convert(self.schema, self.roster, self.baseline, overrides=[Override("nope", "PAWR", 50, "r", "t")])


class SourceFeatureTests(Fixture):
    def test_listed_returners_get_returner_level_kick_return(self):
        wr = [p for p in self.result.players if p.group == "WR"]
        ret = [p for p in wr if p.source_id.endswith("-WR3")]
        non = [p for p in wr if not p.source_id.endswith("-WR3")]
        for p in ret:
            a = p.attributes["PKRT"]
            self.assertEqual((a.method, a.basis["population"]), ("source_direct", "returners"))
            self.assertEqual(a.confidence_label, "medium")  # approximate mapping
        for p in non:
            self.assertEqual(p.attributes["PKRT"].basis["population"], "non-returners")
        mean = lambda ps: sum(p.attributes["PKRT"].value for p in ps) / len(ps)
        self.assertGreater(mean(ret), mean(non) + 25)
        self.assertEqual(self.result.population["returners"]["per_team"], 2)

    def test_return_ability_does_not_change_tier(self):
        p = self.player("T05-WR3")
        self.assertNotIn("PKRT", [u["column"] for u in p.used_source_fields if u["population"] == "position"])
        # Tier composite uses only position-scope fields (r1..r3 for WR).
        self.assertEqual({u["column"] for u in p.used_source_fields if u["population"] == "position"},
                         {"r1", "r2", "r3"})

    def _with_weight(self, sid, weight):
        with self.files["source"].open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            if r["id"] == sid:
                r["weight"] = str(weight)
        path = self.tmp / f"w_{weight}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        res = convert(self.schema, load_roster(path, self.schema), self.baseline)
        return self.player(sid, res)

    def test_lineman_weight_conditions_strength_but_not_tier_or_blocking(self):
        light, heavy = self._with_weight("T04-LG", 255), self._with_weight("T04-LG", 345)
        self.assertGreater(heavy.attributes["PSTR"].value, light.attributes["PSTR"].value)
        self.assertIn("PWGT", heavy.attributes["PSTR"].basis["conditioned_on"])
        self.assertEqual(heavy.tier, {**light.tier, "conditioning": heavy.tier["conditioning"]})
        for tag in ("PPBK", "PRBK"):
            self.assertEqual(heavy.attributes[tag].value, light.attributes[tag].value)
        self.assertNotIn("PWGT", heavy.attributes)  # never an output

    def test_condition_role_restricted_to_auxiliary_fields(self):
        data = make_schema()
        data["interpretations"][0]["targets"] = [{"tag": "PSTR", "role": "condition"}]
        path = self.tmp / "badcond.json"
        path.write_text(json.dumps(data))
        with self.assertRaises(SchemaError):
            load_schema(path)
        data = make_schema()
        data["interpretations"][0]["targets"] = [{"tag": "PWGT", "role": "primary"}]
        path.write_text(json.dumps(data))
        with self.assertRaises(SchemaError):
            load_schema(path)


if __name__ == "__main__":
    unittest.main()
