"""変換スクリプトのテスト。

実行:
    python -m unittest discover -s tools/tests
"""

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from convert import build_song  # noqa: E402

SAMPLE = TOOLS / "tests" / "fixtures" / "sample.musicxml"


class ConvertSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song, cls.issues = build_song(SAMPLE)
        cls.steps = {(s["m"], s["beat"]): s for s in cls.song["steps"]}

    def test_header(self):
        self.assertEqual(self.song["version"], 2)
        self.assertEqual(self.song["key"], "Ab")
        self.assertEqual(self.song["time"], "4/4")
        self.assertEqual(self.song["measures"], 3)

    def test_chord_split_by_staff(self):
        first = self.steps[(1, 1.0)]
        self.assertEqual(first["r"], [68, 72, 75])  # Ab4 C5 Eb5
        self.assertEqual(first["l"], [44])  # Ab2

    def test_triplet_offsets(self):
        self.assertEqual(self.steps[(1, 2.333)]["r"], [75])
        self.assertEqual(self.steps[(1, 2.667)]["r"], [77])

    def test_grace_note_ignored(self):
        # 1小節目の前打音 G5(79) は除外、2小節目の G5 は普通の音符なので残る
        measure1 = [n for s in self.song["steps"] if s["m"] == 1 for n in s["r"]]
        self.assertNotIn(79, measure1)
        self.assertEqual(self.steps[(2, 4.0)]["r"], [79])

    def test_tied_continuation_ignored(self):
        self.assertEqual(self.steps[(2, 1.0)]["r"], [])
        self.assertEqual(self.steps[(2, 1.0)]["l"], [49])

    def test_notation_for_display(self):
        m1 = self.song["score"]["1"]
        self.assertEqual(m1["r"]["clef"], "treble")
        self.assertEqual(m1["l"]["clef"], "bass")
        triplet = m1["r"]["ev"][1]
        self.assertEqual((triplet["o"], triplet["d"], triplet.get("t")), (12, 4, 1))
        self.assertEqual(m1["r"]["ev"][0]["p"], ["Ab4", "C5", "Eb5"])
        # タイの後ろ側は表示には残し、印を付ける
        self.assertEqual(self.song["score"]["2"]["r"]["ev"][0]["tie"], [80])

    def test_short_measure_is_suspect(self):
        self.assertEqual(self.song["suspect"], [3])
        self.assertEqual(len(self.issues), 1)
        self.assertEqual(self.issues[0].hand, "右手")


class ApplyFixesTest(unittest.TestCase):
    """修正ファイルで3小節目（右手が1拍足りない）を直すと、ミス候補が消えること。"""

    @classmethod
    def setUpClass(cls):
        import tempfile
        fixes = "3 R: Eb5/q~ Eb5/t8 F5/t8 G5/t8 Ab5.C6/h  # タイと3連符と和音\n"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(fixes)
            cls.fix_path = Path(f.name)
        cls.song, cls.issues = build_song(SAMPLE, fixes=cls.fix_path)
        cls.steps = {(s["m"], s["beat"]): s for s in cls.song["steps"]}

    @classmethod
    def tearDownClass(cls):
        cls.fix_path.unlink()

    def test_suspect_cleared(self):
        self.assertEqual(self.song["suspect"], [])
        self.assertEqual(self.song["corrected"], [3])

    def test_tie_and_triplet(self):
        self.assertEqual(self.steps[(3, 1.0)]["r"], [75])
        self.assertNotIn((3, 2.0), self.steps)  # タイの続きしかない位置は押す音がない
        self.assertEqual(self.steps[(3, 2.333)]["r"], [77])
        self.assertEqual(self.steps[(3, 3.0)]["r"], [80, 84])  # Ab5 + C6
        self.assertEqual(self.steps[(3, 1.0)]["l"], [44])  # 左手は元のまま


if __name__ == "__main__":
    unittest.main()
