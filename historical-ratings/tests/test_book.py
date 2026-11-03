"""Book preparation + identity cases. Ratings here are fake; names/jerseys/slots mirror the
real Vikings page only to exercise identity handling."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from historical_ratings.book import BookError, normalize_slot, prepare, read_printed, write_prepared
from historical_ratings.matching import match_records
from historical_ratings.source import load_roster, load_schema

REPO = Path(__file__).resolve().parents[1]
HEADER = ["team", "table", "no", "name", "slot", "speed", "scrambling", "pass_accuracy", "pass_range", "agility",
          "hands", "break_tackles", "weight", "pass_blocking", "run_blocking", "pursuit", "tackling", "awareness",
          "pass_coverage", "interceptions", "distance", "accuracy", "reading_note"]


def row(table, no, name, slot, **vals):
    r = {h: "" for h in HEADER}
    r.update(team="MIN", table=table, no=str(no), name=name, slot=slot, **{k: str(v) for k, v in vals.items()})
    return r


PRINTED = [
    row("QUARTERBACKS", 1, "A. Passer", "QB1", speed=7, scrambling=4, pass_accuracy=13, pass_range=12),
    row("RECEIVERS", 82, "Q. Catcher", "WR5", speed=13, agility=8, hands=6, break_tackles=1),
    row("OFFENSIVE LINE", 64, "McDaniel", "LG", weight=275, pass_blocking=15, run_blocking=15),
    row("DEFENSIVE LINE", 93, "J. Rusher", "DRT(NT)", speed=9, agility=9, pursuit=15, tackling=13),
    row("LINEBACKERS", 58, "McDaniel", "ROLB", speed=10, agility=8, awareness=11, tackling=11),
    row("DEFENSIVE BACKS", 36, "", "LCB2", speed=12, pass_coverage=8, interceptions=5, tackling=9),
    row("SPECIAL TEAMS", 7, "F. Kicker", "K", distance=11, accuracy=8),
    row("SPECIAL TEAMS", 82, "Q. Catcher", "KR", speed=13, agility=14, break_tackles=2),
    row("SPECIAL TEAMS", 22, "D. Returner", "KR2", speed=12, agility=11, break_tackles=2),
    row("SPECIAL TEAMS", 22, "D. Returner", "PR", speed=12, agility=11, break_tackles=3),
]


class BookPrepareTests(unittest.TestCase):
    def setUp(self):
        self.players, self.review = prepare([dict(r) for r in PRINTED])
        self.by_id = {p["id"]: p for p in self.players}

    def test_slots_normalised(self):
        self.assertEqual(normalize_slot("DRT(NT)"), ("DRT", "DRT", 1, "NT"))
        self.assertEqual(normalize_slot("WR5"), ("WR5", "WR", 5, ""))
        self.assertEqual(normalize_slot("LCB2"), ("LCB2", "LCB", 2, ""))
        self.assertEqual(normalize_slot("FB"), ("FB", "FB", 1, ""))
        self.assertEqual(self.by_id["MIN-DRT"]["alt_position"], "NT")

    def test_return_row_attached_to_position_row_by_jersey_and_surname(self):
        wr = self.by_id["MIN-WR5"]
        self.assertEqual((wr["kr_speed"], wr["kr_agility"], wr["kr_break_tackles"]), ("13", "14", "2"))
        self.assertEqual((wr["agility"], wr["return_roles"]), ("8", "KR"))  # position rating kept separate
        self.assertEqual(self.review["return_links"], [{"return_row": "SPECIAL TEAMS:KR", "team": "MIN",
                                                        "player": "MIN-WR5"}])

    def test_return_only_player_kept_once_with_both_roles(self):
        self.assertEqual(self.review["return_only"], ["MIN-RET22"])
        ret = self.by_id["MIN-RET22"]
        self.assertEqual((ret["position"], ret["return_roles"]), ("KR", "KR2;PR"))
        self.assertEqual((ret["kr_break_tackles"], ret["pr_break_tackles"]), ("2", "3"))
        self.assertIn("return_only", self.review["flags"]["MIN-RET22"][0])

    def test_review_flags(self):
        f = self.review["flags"]
        self.assertIn("name_missing", f["MIN-LCB2"])
        self.assertIn("shared_surname: MIN-ROLB", f["MIN-LG"])
        self.assertIn("shared_surname: MIN-LG", f["MIN-ROLB"])
        self.assertNotIn("MIN-QB1", f)

    def test_every_printed_row_accounted_for(self):
        sources = [s for p in self.players for s in p["printed_rows"].split(";") if s]
        self.assertEqual(len(sources), len(PRINTED))

    def test_unknown_printed_column_rejected(self):
        tmp = Path(tempfile.mkdtemp()) / "odd.csv"
        with tmp.open("w", newline="") as fh:
            w = csv.DictWriter(fh, HEADER + ["strength"])
            w.writeheader()
            w.writerow({**PRINTED[0], "strength": "9"})
        with self.assertRaises(BookError):
            read_printed([tmp])

    def test_prepared_file_loads_with_verified_book_schema(self):
        tmp = Path(tempfile.mkdtemp())
        write_prepared(self.players, tmp / "src.csv")
        schema = load_schema(REPO / "schemas" / "madden95_book_schema.v1.json")
        roster = load_roster(tmp / "src.csv", schema)
        qb = next(p for p in roster.players if p.source_id == "MIN-QB1")
        self.assertEqual(qb.ratings, {"speed": 7, "scrambling": 4, "pass_accuracy": 13, "pass_range": 12})
        used = {i.meaning: (i.targets[0][0], i.mapping) for i in schema.interpretations_for("QB")}
        self.assertEqual(used["Pass Range"], ("PTHP", "equivalent"))
        self.assertEqual(used["Scrambling"], ("PAGI", "approximate"))
        with self.assertRaises(FileExistsError):
            write_prepared(self.players, tmp / "src.csv")

    def test_book_scale_rejects_zero(self):
        tmp = Path(tempfile.mkdtemp())
        bad = [dict(p) for p in self.players]
        next(p for p in bad if p["id"] == "MIN-QB1")["scrambling"] = "0"
        write_prepared(bad, tmp / "src.csv")
        with self.assertRaises(ValueError):
            load_roster(tmp / "src.csv", load_schema(REPO / "schemas" / "madden95_book_schema.v1.json"))


class SameTeamSurnameMatching(unittest.TestCase):
    """Two 1994 Vikings printed only as 'McDaniel' (LG #64, ROLB #58)."""

    SOURCE = [{"id": "MIN-LG", "name": "McDaniel", "team": "MIN", "position": "LG", "jersey": "64"},
              {"id": "MIN-ROLB", "name": "McDaniel", "team": "MIN", "position": "ROLB", "jersey": "58"}]

    def test_full_reference_names_resolve_by_position_and_jersey(self):
        refs = [{"id": "randall", "name": "Randall McDaniel", "team": "Minnesota Vikings", "position": "G", "jersey": "64"},
                {"id": "ed", "name": "Ed McDaniel", "team": "Minnesota Vikings", "position": "LB", "jersey": "58"}]
        res = {r.source_id: r for r in match_records(self.SOURCE, refs)}
        self.assertEqual((res["MIN-LG"].status, res["MIN-LG"].target_id), ("matched", "randall"))
        self.assertEqual((res["MIN-ROLB"].status, res["MIN-ROLB"].target_id), ("matched", "ed"))

    def test_surname_and_team_alone_is_ambiguous(self):
        ref = [{"id": "q", "name": "McDaniel", "team": "MIN", "position": "", "jersey": ""}]
        res = match_records(ref, self.SOURCE)[0]
        self.assertEqual(res.status, "ambiguous")

    def test_blank_name_never_auto_matched(self):
        src = [{"id": "MIN-LCB2", "name": "", "team": "MIN", "position": "LCB", "jersey": "36"}]
        refs = [{"id": "x", "name": "Some Corner", "team": "MIN", "position": "CB", "jersey": "36"}]
        self.assertNotEqual(match_records(src, refs)[0].status, "matched")


if __name__ == "__main__":
    unittest.main()
