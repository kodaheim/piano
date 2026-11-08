"""小節ごとに「音価の合計」と「拍子」が合っているかを調べる。

OMR（楽譜の自動読み取り）は、3連符の数字の見落としや、音符・休符の読み落としで
小節の長さが合わなくなることが多い。合わない小節を「読み取りミス候補」として返す。

制御の言葉で言えば、目標値 = 拍子から決まる小節の長さ、
実測値 = 書かれた音符と休符の長さの合計、偏差 ≠ 0 の小節を異常とみなす。
"""

from dataclasses import dataclass
from fractions import Fraction

from music21 import meter, stream

from score_steps import hand_parts


@dataclass
class MeasureIssue:
    measure: int
    hand: str  # "右手" / "左手" / "両手"
    expected: Fraction  # 拍子から決まる長さ（4分音符=1）
    actual: Fraction  # 実際に書かれている長さ（いちばん長い声部）
    kind: str = "length"  # "length"=音の読み落とし等 / "time"=拍子記号の読み落とし

    def describe(self) -> str:
        if self.kind == "time":
            return (
                f"{self.measure:>3}小節 両手とも {_fmt(self.actual)}拍 "
                f"(拍子記号では {_fmt(self.expected)}拍) → 拍子記号の読み落とし？"
                f"以降は {_fmt(self.actual)}拍として検証"
            )
        diff = self.actual - self.expected
        sign = "+" if diff > 0 else ""
        return (
            f"{self.measure:>3}小節 {self.hand}: 拍子では {_fmt(self.expected)}拍、"
            f"書かれた合計 {_fmt(self.actual)}拍 (差 {sign}{_fmt(diff)})"
        )


def _fmt(value: Fraction) -> str:
    """3連符の端数を 1/3 のような分数で見せる。"""
    return str(value) if value.denominator != 1 else str(value.numerator)


def _declared_length(measure: stream.Measure) -> Fraction | None:
    """この小節に拍子記号が書かれていれば、その小節の長さ。なければ None。"""
    signatures = measure.getElementsByClass(meter.TimeSignature)
    if not signatures:
        return None
    return Fraction(signatures[0].barDuration.quarterLength).limit_denominator(96)


def _written_length(measure: stream.Measure) -> Fraction:
    """書かれている長さ = いちばん長い声部の音符・休符の合計。

    2つ目以降の声部は途中までしか書かれないことがある（楽譜として正しい）ので、
    小節の長さは最長の声部で決める。
    """
    voices = list(measure.voices) or [measure]
    return max(
        sum(
            (Fraction(n.duration.quarterLength).limit_denominator(96)
             for n in v.notesAndRests if not n.duration.isGrace),
            Fraction(0),
        )
        for v in voices
    )


def find_issues(score: stream.Score) -> list[MeasureIssue]:
    """拍の合計が合わない小節を一覧にする。

    判定（目標値 = 拍子から決まる長さ、実測値 = 書かれた長さ）:
      - 両手とも目標どおり → OK
      - 1小節目が両手とも短い → 弱起（アウフタクト）なので OK
      - 両手が同じ長さで、目標だけ違う → 音はそろっていて拍子記号を読み落とした可能性。
        ミス候補にはせず注意として出し、以降の目標値をその長さに置き換える
      - それ以外 → 読み取りミス候補
    """
    issues = []
    right_part, left_part = hand_parts(score)
    rights = list(right_part.getElementsByClass(stream.Measure))
    lefts = list(left_part.getElementsByClass(stream.Measure))
    target = Fraction(4)  # 拍子記号が見つかるまでは 4/4 とみなす

    for index, right in enumerate(rights):
        left = lefts[index] if index < len(lefts) else None
        declared = _declared_length(right)
        if declared is not None:
            target = declared

        lengths = {"右手": _written_length(right)}
        if left is not None:
            lengths["左手"] = _written_length(left)
        values = set(lengths.values())

        if values == {target}:
            continue
        if index == 0 and max(values) <= target:
            continue
        if len(values) == 1 and len(lengths) == 2:
            actual = values.pop()
            issues.append(MeasureIssue(right.number, "両手", target, actual, kind="time"))
            target = actual
            continue
        for hand, actual in lengths.items():
            if actual != target:
                issues.append(MeasureIssue(right.number, hand, target, actual))
    return issues


def suspect_measures(issues: list[MeasureIssue]) -> list[int]:
    """読み取りミス候補の小節番号（拍子記号だけの問題は含めない）。"""
    return sorted({x.measure for x in issues if x.kind == "length"})
