"""Identity matching: real names here are identity strings only -- no ratings are attached."""

import unittest

from historical_ratings.matching import canonical_team, match_records, normalize_name

REF = [
    {"id": "r1", "name": "Barry Sanders", "team": "Detroit Lions", "position": "RB", "jersey": "20"},
    {"id": "r2", "name": "Emmitt Smith", "team": "Dallas Cowboys", "position": "RB", "jersey": "22"},
    {"id": "r3", "name": "Kevin Smith", "team": "Dallas Cowboys", "position": "CB", "jersey": "26"},
    {"id": "r4", "name": "Steve Young", "team": "San Francisco 49ers", "position": "QB", "jersey": "8"},
    {"id": "r5", "name": "Warren Moon", "team": "Minnesota Vikings", "position": "QB", "jersey": "1"},
    {"id": "r6", "name": "Jerome Bettis", "team": "Los Angeles Rams", "position": "RB", "jersey": "36"},
]


def one(src, **kw):
    return match_records([src], REF, **kw)[0]


class MatchingTests(unittest.TestCase):
    def test_initial_abbreviation_matches(self):
        r = one({"id": "s", "name": "B. Sanders", "team": "DET", "position": "HB", "jersey": "20"})
        self.assertEqual((r.status, r.target_id), ("matched", "r1"))

    def test_nickname_equivalent(self):
        r = one({"id": "s", "name": "Steven Young", "team": "SF", "position": "QB"})
        self.assertEqual((r.status, r.target_id), ("matched", "r4"))

    def test_last_name_only_with_two_candidates_is_ambiguous(self):
        r = one({"id": "s", "name": "Smith", "team": "Dallas", "position": ""})
        self.assertEqual(r.status, "ambiguous")
        self.assertIsNone(r.target_id)
        self.assertFalse(r.applicable)

    def test_position_and_jersey_disambiguate(self):
        r = one({"id": "s", "name": "Smith", "team": "Dallas", "position": "HB", "jersey": "22"})
        self.assertEqual((r.status, r.target_id), ("matched", "r2"))

    def test_wrong_team_never_matches(self):
        r = one({"id": "s", "name": "Warren Moon", "team": "Houston Oilers", "position": "QB"})
        self.assertEqual(r.status, "unmatched")

    def test_conflicting_first_name_not_matched(self):
        r = one({"id": "s", "name": "Ricky Sanders", "team": "DET", "position": "WR"})
        self.assertNotEqual(r.status, "matched")

    def test_slot_only_identity_never_auto_matched(self):
        r = one({"id": "s", "name": "", "team": "DET", "position": "HB", "jersey": "20"})
        self.assertIn(r.status, ("weak", "unmatched", "ambiguous"))

    def test_manual_decisions_win(self):
        r = one({"id": "s", "name": "Smith", "team": "DAL"}, manual={"s": "r3"})
        self.assertEqual((r.status, r.target_id), ("manual", "r3"))
        r = one({"id": "s", "name": "Barry Sanders", "team": "DET"}, manual={"s": None})
        self.assertEqual(r.status, "manual_rejected")
        self.assertFalse(r.applicable)

    def test_target_claimed_twice_becomes_ambiguous(self):
        srcs = [{"id": "a", "name": "Barry Sanders", "team": "DET", "position": "RB"},
                {"id": "b", "name": "B. Sanders", "team": "DET", "position": "RB"}]
        res = match_records(srcs, REF)
        self.assertEqual({r.status for r in res}, {"ambiguous"})

    def test_1994_team_aliases(self):
        self.assertEqual(canonical_team("Phoenix Cardinals"), canonical_team("ARI"))
        self.assertEqual(canonical_team("L.A. Rams"), canonical_team("Rams"))
        self.assertNotEqual(canonical_team("LA Raiders"), canonical_team("LA Rams"))

    def test_name_normalization(self):
        self.assertEqual(normalize_name("Ken O'Brien Jr."), ["ken", "obrien"])
        self.assertEqual(normalize_name("B.Sanders"), ["b", "sanders"])


if __name__ == "__main__":
    unittest.main()
