"""Export tool + CLI end-to-end. The editor-reader test runs only where the
Madden06Editor source (game_formats.py) is importable, e.g.:

  set MADDEN06_EDITOR_SRC=D:\\Madden 06
  python -m unittest discover -s tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from synthetic import make_m06_play, write_fixture_files
from tdb_builder import RATING_TAGS, template_dat

REPO = Path(__file__).resolve().parents[1]
EDITOR_SRC = os.environ.get("MADDEN06_EDITOR_SRC", "")


def _editor_available() -> bool:
    if not EDITOR_SRC:
        return False
    p = Path(EDITOR_SRC)
    return (p / "game_formats.py").exists() or (p / "game_formats.pyc").exists()


@unittest.skipUnless(_editor_available(), "set MADDEN06_EDITOR_SRC to the Madden 06 editor source folder")
class ExportToolWithEditorReader(unittest.TestCase):
    def test_export_reads_member_1_via_load_players_and_feeds_baseline(self):
        play = [r for r in make_m06_play() if r["TGID"] < 32]
        teams = [{"TGID": t, "TLNA": f"Team{t:02d}", "TDNA": "Synth"} for t in range(32)]
        for r in play:
            r["PJEN"] = r["PGID"] % 99
        tmp = Path(tempfile.mkdtemp())
        dat = tmp / "TEMPLATE.DAT"
        dat.write_bytes(template_dat(play, teams))
        out = tmp / "export.json"
        tool = REPO / "tools" / "export_m06_play_table.py"
        subprocess.run([sys.executable, str(tool), "--editor-src", EDITOR_SRC, "--template-dat", str(dat),
                        "--out", str(out), "--csv", str(tmp / "export.csv")], check=True, capture_output=True)
        data = json.loads(out.read_text())
        self.assertEqual(data["record_count"], len(play))
        first = data["players"][0]
        self.assertEqual(first["_member"], 1)
        self.assertEqual(first["_team"], "Team00 Synth")
        for tag in RATING_TAGS + ("PPOS", "POVR", "PGID"):
            self.assertEqual(first[tag], play[0][tag])
        # Refuses to overwrite.
        r = subprocess.run([sys.executable, str(tool), "--editor-src", EDITOR_SRC, "--template-dat", str(dat),
                            "--out", str(out)], capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        from historical_ratings.baseline import Baseline
        b = Baseline.from_play_export(out)
        self.assertEqual(b.meta["rostered_players"], len(play))


class CliEndToEnd(unittest.TestCase):
    def test_baseline_then_convert_test_group(self):
        tmp = Path(tempfile.mkdtemp())
        f = write_fixture_files(tmp)
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        run = lambda *a: subprocess.run([sys.executable, "-m", "historical_ratings", *a], cwd=REPO, env=env,
                                        capture_output=True, text=True)
        r = run("baseline", "--play-export", str(f["play"]), "--out", str(tmp / "b.json"),
                "--report", str(tmp / "report.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        assign = tmp / "assign.json"
        assign.write_text(json.dumps([{"name": "Fake HB1T03", "team": "Old03", "position": "HB",
                                       "archetype": "elusive"}]))
        r = run("convert", "--source", str(f["source"]), "--schema", str(f["schema"]), "--baseline",
                str(tmp / "b.json"), "--archetypes", str(REPO / "schemas" / "archetypes.v1.json"),
                "--assign", str(assign), "--only", "T03-HB1,T03-QB1,T03-K", "--out-dir", str(tmp / "out"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        result = json.loads((tmp / "out" / "conversion.json").read_text())
        self.assertEqual([p["source_id"] for p in result["players"]], ["T03-HB1", "T03-K", "T03-QB1"])
        hb = result["players"][0]
        self.assertEqual(hb["archetype"], "elusive")
        for name in ("ratings.csv", "provenance.csv", "diagnostics.csv", "skipped.csv"):
            self.assertTrue((tmp / "out" / name).exists())

    def test_ambiguous_archetype_assignment_stops_run(self):
        tmp = Path(tempfile.mkdtemp())
        f = write_fixture_files(tmp)
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        subprocess.run([sys.executable, "-m", "historical_ratings", "baseline", "--play-export", str(f["play"]),
                        "--out", str(tmp / "b.json")], cwd=REPO, env=env, check=True, capture_output=True)
        assign = tmp / "assign.json"
        assign.write_text(json.dumps([{"name": "Fake", "team": "Old03", "archetype": "elusive"}]))
        r = subprocess.run([sys.executable, "-m", "historical_ratings", "convert", "--source", str(f["source"]),
                            "--schema", str(f["schema"]), "--baseline", str(tmp / "b.json"), "--archetypes",
                            str(REPO / "schemas" / "archetypes.v1.json"), "--assign", str(assign),
                            "--out-dir", str(tmp / "out")], cwd=REPO, env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("need review", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
