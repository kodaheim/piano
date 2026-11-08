# 楽譜 → アプリ用JSON 変換ツール

楽譜PDFを読み取り、練習アプリ（`index.html`）で読み込める `*_data.json` を作る。

```
楽譜PDF ─ preprocess.py ─▶ 段ごとのPNG ─ Audiveris ─▶ .mxl ─ convert.py ─▶ *_data.json
                                                               ▲
                                    MuseScoreで作った/直した MusicXML もここから
```

> **注意**：リポジトリは Public。楽譜・画像・MusicXML・JSON は `元の楽譜/` か `scores/` に置く（`.gitignore` で除外済み）。

## 準備（初回だけ）

- Python仮想環境：`C:\Users\kodah\venvs\piano`（music21, opencv-python, pymupdf）
- Audiveris 5.11：`%LOCALAPPDATA%\Programs\Audiveris-5.11.0\Audiveris\Audiveris.exe`（Java同梱）

Git Bash で仮想環境を有効にする：

```bash
source ~/venvs/piano/Scripts/activate
```

## 手順（例：にじ）

```bash
# 1. 前処理：見開きを分割 → 拡大 → 白黒 → 段（システム）ごとに切り出し
python tools/preprocess.py 元の楽譜/にじ.pdf scores/niji/systems --systems

# 2. OMR：段ごとに MusicXML(.mxl) にする（9段で1分ほど）
"$LOCALAPPDATA/Programs/Audiveris-5.11.0/Audiveris/Audiveris.exe" -batch -export -output scores/niji/omr_sys -- scores/niji/systems/*.png

# 3. 変換と検証：段をつなげて JSON にし、拍の合わない小節を一覧表示
python tools/convert.py scores/niji/omr_sys/*.mxl --title にじ -o scores/niji/niji_data.json
```

```bash
# 4. 要確認の小節を元の画像と見比べ、修正ファイルに正しい音を書いて差し替える
#    （書き方は apply_fixes.py の先頭の説明。にじは scores/niji/fixes.txt で12小節を修正済み）
python tools/convert.py scores/niji/omr_sys/*.mxl --title にじ --fixes scores/niji/fixes.txt -o scores/niji/niji_data.json
```

できた `niji_data.json` をスマホに送り、アプリの「曲」画面で読み込む。
修正ファイルで直すとリズムも残るので、段階譜もきれいに表示される。
アプリの「入力」画面でピアノから入れ直すこともできる（こちらはリズムなしの表示になる）。

## なぜ段ごとに読み取るのか

Audiveris は拍子記号を1つ読み落とすと、その後の小節をすべて間違った拍子として扱い、
はみ出した音を捨ててしまう（「にじ」では6小節目の C を読み落とし、後半の音が消えた）。
段ごとに分けると、拍子記号のない段は拍子を決めつけずに読まれるので、被害がその段だけで止まる。

## ファイル

| ファイル | 役割 |
|---|---|
| `preprocess.py` | PDF/画像 → OMR用PNG（分割・拡大・二値化・段の切り出し） |
| `score_steps.py` | MusicXML → 同時に押す音のまとまり（ステップ）。右手＝上の段、左手＝下の段 |
| `merge_scores.py` | 段ごとの MusicXML を1曲につなげ、小節番号を振り直す |
| `apply_fixes.py` | 修正ファイル（1行＝1小節の片手）で、読み取りミスの小節を差し替える |
| `validate_measures.py` | 小節ごとに「拍子の長さ」と「書かれた音価の合計」を比べ、ミス候補を出す |
| `convert.py` | 上をまとめて実行し、JSON を書き出す |
| `tests/` | 自作のテスト楽譜を使ったテスト（`python -m unittest discover -s tools/tests`） |

## JSON の形（version 2）

```json
{
  "version": 2, "title": "にじ", "key": "Ab", "time": "4/4", "measures": 36,
  "suspect": [2, 3, 4],
  "steps": [ {"m": 9, "beat": 1.0, "r": [68, 73, 77], "l": [37]} ]
}
```

- `beat`：小節内の位置（1拍目＝1.0、4分音符単位。3連符は 2.333 など）
- `r` / `l`：右手・左手で新しく押す音の MIDI 番号（タイの後ろ側・装飾音は含めない）
- `suspect`：拍の合計が合わなかった小節（読み取りミス候補）
- `score`：アプリで段階譜を描くためのデータ。小節番号ごとに
  `{"len": 48, "r": {"clef": "treble", "ev": [{"o": 0, "d": 6, "p": ["Ab4","Db5","F5"], "n": [68,73,77]}]}, "l": {...}}`
  - `o`・`d`：位置と長さ（tick、4分音符＝12。3連符の8分＝4）
  - `p`：音名（調に合わせた綴り）、`n`：MIDI番号、`tie`：タイの続きの音、`t`：3連符
