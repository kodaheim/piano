"""MusicXML → アプリ用JSON（version 2）への変換。

使い方:
    python tools/convert.py scores/niji/にじ.musicxml
    python tools/convert.py scores/niji/にじ.mxl -o scores/niji/niji_data.json
    # 段ごとに読み取ったファイルをつなげる（ファイル名順に並べること）
    python tools/convert.py scores/niji/omr_sys/*.mxl --title にじ -o scores/niji/niji_data.json
    # 読み取りミスを修正ファイルで差し替える（書き方は apply_fixes.py の説明を参照）
    python tools/convert.py scores/niji/omr_sys/*.mxl --title にじ --fixes scores/niji/fixes.txt -o scores/niji/niji_data.json

出力ファイル名は *_data.json にすること（.gitignore で除外される）。
読み取りミス候補の小節は画面に一覧表示し、JSON の "suspect" にも入れる。
"""

import argparse
import json
from pathlib import Path

from apply_fixes import apply_fixes, parse_fixes
from merge_scores import merge_scores
from score_steps import collect_notation, collect_steps, key_name, load_score, time_name, title_of
from validate_measures import find_issues, suspect_measures


def build_song(paths: Path | list[Path], title: str | None = None,
               fixes: Path | None = None) -> tuple[dict, list]:
    """1つまたは複数（段ごと）の MusicXML から、アプリ用の曲データを作る。"""
    if isinstance(paths, Path):
        paths = [paths]
    if len(paths) == 1:
        score = load_score(str(paths[0]))
    else:
        score = merge_scores([str(p) for p in paths])
    corrected = apply_fixes(score, parse_fixes(fixes)) if fixes else []
    steps = collect_steps(score)
    issues = find_issues(score)
    song = {
        "version": 2,
        "title": title or title_of(score, paths[0].stem),
        "key": key_name(score),
        "time": time_name(score),
        "measures": max((s.measure for s in steps), default=0),
        "suspect": suspect_measures(issues),
        "corrected": corrected,  # 修正ファイルで差し替えた小節
        "steps": [s.to_json() for s in steps],
        "score": collect_notation(score),  # 楽譜表示用（アプリの段階譜）
    }
    return song, issues


def default_output(src: Path) -> Path:
    return src.with_name(f"{src.stem}_data.json")


def write_json(song: dict, path: Path) -> None:
    # 1ステップ1行・1小節1行にして、差分やテキストエディタで見やすくする
    steps = [json.dumps(s, ensure_ascii=False) for s in song["steps"]]
    measures = [f'"{m}": ' + json.dumps(v, ensure_ascii=False) for m, v in song["score"].items()]
    head = {k: v for k, v in song.items() if k not in ("steps", "score")}
    text = json.dumps(head, ensure_ascii=False, indent=2)[:-2]
    text += ',\n  "steps": [\n    ' + ",\n    ".join(steps) + "\n  ]"
    text += ',\n  "score": {\n    ' + ",\n    ".join(measures) + "\n  }\n}\n"
    path.write_text(text, encoding="utf-8")


def print_report(song: dict, issues: list) -> None:
    print(f"曲名: {song['title']}  調: {song['key']}  拍子: {song['time']}")
    print(f"小節数: {song['measures']}  ステップ数: {len(song['steps'])}")
    if song["corrected"]:
        print(f"修正ファイルで差し替えた小節: {song['corrected']}")
    if not issues:
        print("拍の合計が合わない小節はありません")
        return
    print(f"\n読み取りミス候補: {len(song['suspect'])}小節 {song['suspect']}")
    for issue in issues:
        print("  " + issue.describe())


def main() -> None:
    parser = argparse.ArgumentParser(description="MusicXML をアプリ用JSONに変換する")
    parser.add_argument("src", type=Path, nargs="+", help=".musicxml / .xml / .mxl（複数可）")
    parser.add_argument("-o", "--output", type=Path, help="出力先（省略時は *_data.json）")
    parser.add_argument("--title", help="曲名（省略時は楽譜の題名かファイル名）")
    parser.add_argument("--fixes", type=Path, help="読み取りミスの修正ファイル")
    args = parser.parse_args()

    song, issues = build_song(sorted(args.src), args.title, args.fixes)
    out = args.output or default_output(args.src[0])
    write_json(song, out)
    print_report(song, issues)
    print(f"\n保存しました: {out}")


if __name__ == "__main__":
    main()
