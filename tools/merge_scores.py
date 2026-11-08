"""段（システム）ごとに読み取った MusicXML を、1曲分につなげる。

OMRを段ごとにかけると、ファイルごとに小節番号が 1 から始まる。
ここで小節番号を通し番号に振り直す。

2段目以降には拍子記号が書かれていないが、ここでは補わない。
（補うと、OMRが読み落とした拍子変更まで次の段に持ち越してしまうため。
  拍子の引き継ぎは validate_measures.py が小節の中身を見ながら行う。）
"""

import copy

from music21 import stream

from score_steps import hand_parts, load_score


def merge_scores(paths: list[str]) -> stream.Score:
    """複数の MusicXML を順番につないだ Score を返す（右手・左手の2パート）。"""
    merged = stream.Score()
    right_out, left_out = stream.PartStaff(), stream.PartStaff()
    merged.insert(0, right_out)
    merged.insert(0, left_out)

    number = 0
    for path in paths:
        score = load_score(path)
        if number == 0 and score.metadata is not None:
            merged.metadata = copy.deepcopy(score.metadata)
        right, left = hand_parts(score)
        start = number
        for src, dst in ((right, right_out), (left, left_out)):
            number = start
            for measure in src.getElementsByClass(stream.Measure):
                number += 1
                m = copy.deepcopy(measure)
                m.number = number
                dst.append(m)
        print(f"  {path}: {start + 1}〜{number}小節")
    return merged
