"""MusicXML から「同時に押す音のまとまり（ステップ）」を取り出す。

ステップ = 同じ小節・同じタイミングで鳴り始める音の集合。
右手は楽譜の上の段（staff 1）、左手は下の段（staff 2）から直接取るので、
「境目の鍵盤」で左右を判定する必要がない。

除外するもの:
    - タイでつながった後ろ側の音（新しく押さないため）
    - 装飾音（前打音など）
    - 休符
"""

from dataclasses import dataclass, field
from fractions import Fraction

from music21 import clef, converter, key, meter, stream

# music21 の調名（'A-'）をアプリ用の表記（'Ab'）に直す
_FLAT = "-"


@dataclass
class Step:
    measure: int
    offset: Fraction  # 小節の頭からの位置（4分音符=1）
    right: set[int] = field(default_factory=set)
    left: set[int] = field(default_factory=set)

    def to_json(self) -> dict:
        return {
            "m": self.measure,
            "beat": round(float(self.offset) + 1, 3),  # 1拍目 = 1.0
            "r": sorted(self.right),
            "l": sorted(self.left),
        }


def load_score(path: str) -> stream.Score:
    """MusicXML（.musicxml / .xml / .mxl）を読み込む。"""
    return converter.parse(path)


def hand_parts(score: stream.Score) -> tuple[stream.Part, stream.Part]:
    """右手（上の段）と左手（下の段）のパートを返す。

    ピアノ譜は music21 で読むと PartStaff が2つになる。
    段が1つしかない楽譜では左手は空になる。
    """
    parts = list(score.parts)
    if not parts:
        raise ValueError("パートが見つかりません")
    if len(parts) == 1:
        return parts[0], stream.Part()
    if len(parts) > 2:
        print(f"  注意: パートが{len(parts)}個あります。上の2つだけを使います")
    return parts[0], parts[1]


def _starting_pitches(element) -> list[int]:
    """音符または和音のうち、新しく押す音（タイの後ろ側でない音）の MIDI 番号。"""
    notes = element.notes if element.isChord else [element]
    result = []
    for n in notes:
        if n.tie is not None and n.tie.type in ("stop", "continue"):
            continue
        result.append(n.pitch.midi)
    return result


def collect_steps(score: stream.Score) -> list[Step]:
    """楽譜全体からステップの一覧を作る（小節・タイミング順）。"""
    right_part, left_part = hand_parts(score)
    steps: dict[tuple[int, Fraction], Step] = {}

    for hand, part in (("right", right_part), ("left", left_part)):
        for measure in part.getElementsByClass(stream.Measure):
            for element in measure.flatten().notes:
                if element.duration.isGrace:
                    continue
                pitches = _starting_pitches(element)
                if not pitches:
                    continue
                offset = Fraction(element.offset).limit_denominator(96)
                k = (measure.number, offset)
                step = steps.setdefault(k, Step(measure.number, offset))
                getattr(step, hand).update(pitches)

    return [steps[k] for k in sorted(steps)]


def key_name(score: stream.Score) -> str:
    """最初の調号から長調の名前を返す（例: 'Ab'）。調号がなければ 'C'。"""
    signature = next(iter(score.recurse().getElementsByClass(key.KeySignature)), None)
    if signature is None:
        return "C"
    k = signature if isinstance(signature, key.Key) else signature.asKey("major")
    return k.tonic.name.replace(_FLAT, "b")


def time_name(score: stream.Score) -> str:
    """最初の拍子（例: '4/4'）。"""
    ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
    return ts.ratioString if ts else "4/4"


def title_of(score: stream.Score, fallback: str) -> str:
    md = score.metadata
    if md is not None and md.title:
        return md.title
    return fallback


# ---------------------------------------------------------------------------
# 楽譜表示用のデータ（アプリで「段階譜」を描くため）
# ---------------------------------------------------------------------------

# 時間の単位：4分音符 = 12 tick（3連符の8分音符 = 4、16分音符 = 3 が整数になる）
TICKS_PER_QUARTER = 12


def _ticks(quarter_length) -> int:
    return round(Fraction(quarter_length).limit_denominator(96) * TICKS_PER_QUARTER)


def _spelled(p) -> str:
    """music21 の音名（'E-5'）を表示用（'Eb5'）にする。"""
    return p.nameWithOctave.replace("-", "b")


def _clef_name(measure: stream.Measure) -> str:
    """小節の音部記号。小節の中に書かれていればそれを、なければ前の小節から引き継ぐ。"""
    inside = list(measure.recurse().getElementsByClass(clef.Clef))
    c = inside[0] if inside else measure.getContextByClass(clef.Clef)
    if c is not None and c.sign == "F":
        return "bass"
    return "treble"


def _measure_events(measure: stream.Measure) -> list[dict]:
    """1小節・片手ぶんの「同時に鳴り始める音のまとまり」を時間順に並べる。

    声部が複数あっても1列にまとめる（表示を簡単にするため）。
    同じタイミングの音は1つの和音にし、長さは短い方に合わせる。
    タイの後ろ側の音も表示には入れる（"tie" に印を付ける）。
    """
    groups: dict[int, dict] = {}
    for element in measure.flatten().notes:
        if element.duration.isGrace:
            continue
        onset = _ticks(element.offset)
        length = _ticks(element.duration.quarterLength)
        if length <= 0:
            continue
        g = groups.setdefault(onset, {"o": onset, "d": length, "p": [], "n": [], "tie": [], "t": 0})
        g["d"] = min(g["d"], length)
        if element.duration.tuplets:
            g["t"] = 1
        notes = element.notes if element.isChord else [element]
        for n in notes:
            if n.pitch.midi in g["n"]:
                continue
            g["p"].append(_spelled(n.pitch))
            g["n"].append(n.pitch.midi)
            if n.tie is not None and n.tie.type in ("stop", "continue"):
                g["tie"].append(n.pitch.midi)

    events = [groups[k] for k in sorted(groups)]
    for g in events:
        order = sorted(range(len(g["n"])), key=lambda i: g["n"][i])
        g["p"] = [g["p"][i] for i in order]
        g["n"] = [g["n"][i] for i in order]
        if not g["tie"]:
            del g["tie"]
        if not g["t"]:
            del g["t"]
    return events


def collect_notation(score: stream.Score) -> dict[str, dict]:
    """小節番号 → {"len": 小節の長さ, "r": {...}, "l": {...}} の辞書。

    小節の長さは拍子記号ではなく、実際に書かれた音の長さ（両手の長い方）にする。
    OMR が拍子記号を読み落としても、表示が崩れないようにするため。

    各手は {"clef": "treble"|"bass", "ev": [{"o", "d", "p", "n", "tie"?, "t"?}]}。
    o=小節頭からの位置、d=長さ（どちらも tick）、p=音名、n=MIDI番号、t=3連符。
    """
    right_part, left_part = hand_parts(score)
    result: dict[str, dict] = {}
    for hand, part in (("r", right_part), ("l", left_part)):
        for measure in part.getElementsByClass(stream.Measure):
            entry = result.setdefault(str(measure.number), {})
            entry["len"] = max(entry.get("len", 0), _ticks(measure.highestTime))
            entry[hand] = {"clef": _clef_name(measure), "ev": _measure_events(measure)}
    return result
