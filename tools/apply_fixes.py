"""OMRの読み取りミスを、人（またはClaude）が書いた修正ファイルで差し替える。

修正ファイルの書き方（1行 = 1小節の片手ぶん。# から後ろはコメント）:

    2 R: C5.F5.Ab5/q C5/t8 F5/t8 Ab5/t8 G5/q C6/q
    2 L: clef:treble F3/t8 C4/t8 F4/t8 Ab4/q Eb3/8 C4/8 Eb4.G4/q

    - 「小節番号 手:」の手は R（右手）か L（左手）
    - 音: 音名＋オクターブ（C4 = 真ん中のド）。♭は b、♯は #。和音は . でつなぐ
      調号は考えないので、変イ長調でも A♭ は「Ab」と書く（「A」はナチュラル）
    - 長さ: / のあとに w(全) h(2分) q(4分) 8 16。付点は d を付ける（qd）
      3連符は t を付ける（t8 = 3連符の8分、tq = 3連符の4分）
    - 休符: r/q のように書く
    - タイ: 末尾に ~ を付けると、次の音（同じ高さ）へタイでつながる
    - 音部記号: clef:treble / clef:bass（その小節の最初に書く）
    - 拍子記号: time:4/4 など（拍子が変わる小節の最初に書く。OMRが読み落としたとき用）

修正ファイルは楽譜の内容そのものなので、scores/ に置いてコミットしない。
"""

import copy
import re
from fractions import Fraction
from pathlib import Path

from music21 import chord, clef, meter, note, stream, tie

DURATIONS = {"w": Fraction(4), "h": Fraction(2), "q": Fraction(1), "8": Fraction(1, 2), "16": Fraction(1, 4)}
TOKEN = re.compile(r"^(?P<pitches>[^/]+)/(?P<trip>t?)(?P<base>w|h|q|8|16)(?P<dot>d?)(?P<tie>~?)$")
PITCH = re.compile(r"^([A-G])(#|b)?(-?\d)$")


def parse_fixes(path: Path) -> dict[tuple[int, str], list[str]]:
    """修正ファイルを読み、(小節番号, 'R'|'L') → トークンの列 にする。"""
    fixes = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s+([RL])\s*:\s*(.*)$", line)
        if not m:
            raise ValueError(f"{path}:{line_no} 書き方が違います: {raw}")
        fixes[(int(m.group(1)), m.group(2))] = m.group(3).split()
    return fixes


def _pitch_name(text: str) -> str:
    """'Ab4' → music21 の 'A-4'。"""
    m = PITCH.match(text)
    if not m:
        raise ValueError(f"音名が読めません: {text}")
    letter, acc, octave = m.groups()
    return letter + {"b": "-", "#": "#", None: ""}[acc] + octave


def _length(token: re.Match) -> Fraction:
    length = DURATIONS[token["base"]]
    if token["dot"]:
        length *= Fraction(3, 2)
    if token["trip"]:
        length *= Fraction(2, 3)
    return length


def build_measure(number: int, tokens: list[str]) -> stream.Measure:
    """トークンの列から1小節を作る。"""
    measure = stream.Measure(number=number)
    previous_tied: set[str] = set()
    for text in tokens:
        if text.startswith("time:"):
            measure.insert(0, meter.TimeSignature(text.split(":", 1)[1]))
            continue
        if text.startswith("clef:"):
            kind = text.split(":", 1)[1]
            measure.append(clef.TrebleClef() if kind == "treble" else clef.BassClef())
            continue
        token = TOKEN.match(text)
        if not token:
            raise ValueError(f"{number}小節: 読めないトークン {text}")
        length = _length(token)
        if token["pitches"] == "r":
            measure.append(note.Rest(quarterLength=length))
            previous_tied = set()
            continue
        names = [_pitch_name(p) for p in token["pitches"].split(".")]
        element = chord.Chord(names, quarterLength=length) if len(names) > 1 else note.Note(names[0], quarterLength=length)
        notes = element.notes if element.isChord else [element]
        for n in notes:
            starts = bool(token["tie"])
            stops = n.pitch.nameWithOctave in previous_tied
            if starts and stops:
                n.tie = tie.Tie("continue")
            elif starts:
                n.tie = tie.Tie("start")
            elif stops:
                n.tie = tie.Tie("stop")
        previous_tied = {n.pitch.nameWithOctave for n in notes} if token["tie"] else set()
        measure.append(element)
    return measure


def apply_fixes(score: stream.Score, fixes: dict[tuple[int, str], list[str]]) -> list[int]:
    """楽譜の該当小節を差し替え、差し替えた小節番号の一覧を返す。"""
    from score_steps import hand_parts

    right, left = hand_parts(score)
    done = set()
    for (number, hand), tokens in sorted(fixes.items()):
        part = right if hand == "R" else left
        old = next((m for m in part.getElementsByClass(stream.Measure) if m.number == number), None)
        if old is None:
            raise ValueError(f"{number}小節が見つかりません")
        new = build_measure(number, tokens)
        # 拍子記号は、修正ファイルに書いていなければもとの小節から引き継ぐ
        if not new.getElementsByClass("TimeSignature"):
            for ts in old.getElementsByClass("TimeSignature"):
                new.insert(0, copy.deepcopy(ts))
        part.replace(old, new)
        done.add(number)
    return sorted(done)
