"""楽譜PDF/画像の前処理（OMRにかける前の下ごしらえ）。

処理の流れ:
    PDF/画像 → ページ画像を取り出す → 見開きなら左右に分割 → 拡大 → 二値化 → PNG保存

使い方:
    python tools/preprocess.py 元の楽譜/にじ.pdf scores/niji

出力先は .gitignore で除外されたフォルダ（scores/ など）にすること。
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
import pymupdf

# OMR（Audiveris）は五線の間隔が 15〜25px 程度あると読みやすい。
# 小さい画像はこの倍率まで拡大する。
TARGET_SCALE = 2.0


def load_pages(path: Path) -> list[np.ndarray]:
    """PDFまたは画像ファイルを読み込み、ページごとのグレースケール画像を返す。"""
    if path.suffix.lower() == ".pdf":
        return _load_pdf_pages(path)
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"画像を読み込めません: {path}")
    return [image]


def _load_pdf_pages(path: Path) -> list[np.ndarray]:
    """PDFの各ページから画像を取り出す。

    ページに画像が1枚だけ埋め込まれている場合（スキャンやスクショを貼ったPDF）は、
    再描画せず元の解像度のまま取り出す。そうでなければ300dpiで描画する。
    """
    pages = []
    doc = pymupdf.open(path)
    for page in doc:
        images = page.get_images(full=True)
        if len(images) == 1:
            data = doc.extract_image(images[0][0])["image"]
            buf = np.frombuffer(data, dtype=np.uint8)
            pages.append(cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE))
        else:
            pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
            pages.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w))
    return pages


def split_spread(image: np.ndarray) -> list[np.ndarray]:
    """横長の見開き画像を、中央付近の白い縦すじで左右2ページに分ける。

    縦長（1ページ分）の画像はそのまま返す。
    """
    height, width = image.shape
    if width < height * 1.2:
        return [image]

    # 中央 ±15% の範囲で、黒い画素が最も少ない列を境目とする
    ink_per_column = (image < 128).sum(axis=0)
    left, right = int(width * 0.35), int(width * 0.65)
    split_x = left + int(np.argmin(ink_per_column[left:right]))
    return [image[:, :split_x], image[:, split_x:]]


def trim_margin(image: np.ndarray, pad: int = 20) -> np.ndarray:
    """周囲の余白を切り詰める（少しだけ余白 pad を残す）。"""
    ys, xs = np.where(image < 128)
    if len(xs) == 0:
        return image
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, image.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, image.shape[1])
    return image[y0:y1, x0:x1]


def upscale(image: np.ndarray, scale: float = TARGET_SCALE) -> np.ndarray:
    """補間しながら拡大する。細い線がつぶれないよう INTER_CUBIC を使う。"""
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def binarize(image: np.ndarray) -> np.ndarray:
    """大津の方法で白黒2値にする（スマホ写真のムラには adaptive の方が良い場合あり）。"""
    _, result = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return result


def find_staff_lines(image: np.ndarray) -> list[int]:
    """五線の線（幅の6割以上つながった横線）の y 座標を返す。太い線は1本にまとめる。"""
    row_ink = (image < 128).sum(axis=1)
    rows = np.where(row_ink > image.shape[1] * 0.6)[0]
    lines: list[int] = []
    for y in rows:
        if lines and y - lines[-1] <= 2:
            lines[-1] = y
        else:
            lines.append(int(y))
    return lines


def group_staves(lines: list[int]) -> list[tuple[int, int]]:
    """横線の一覧から、間隔がほぼ等しい5本の組（＝五線）を探し、(上端, 下端) を返す。

    リピートの括弧（1. 2.）の横線のように、五線でない長い線は自然に読み飛ばされる。
    """
    staves = []
    i = 0
    while i + 5 <= len(lines):
        group = lines[i:i + 5]
        gaps = np.diff(group)
        if gaps.max() <= gaps.min() * 1.3:
            staves.append((group[0], group[-1]))
            i += 5
        else:
            i += 1
    return staves


def split_systems(image: np.ndarray, staves_per_system: int = 2) -> list[np.ndarray]:
    """1ページを段（システム＝右手と左手の五線のひと組）ごとに切り分ける。

    OMRは拍子記号を1つ読み落とすと、その後の小節をすべて間違った拍子で
    解釈してしまう。段ごとに分けて読ませると、影響がその段だけで止まる。

    方法: 五線の線を見つけて5本ずつ1つの五線にまとめ、2つ（ピアノの右手・左手）で1段。
    段と段のあいだでは、黒い画素が最も少ない行で切る（コード名やペダル記号を避ける）。
    """
    staves = group_staves(find_staff_lines(image))
    per = staves_per_system
    if len(staves) % per != 0:
        raise ValueError(f"五線が {len(staves)} 個見つかりました（{per}の倍数でない）")
    systems = [(staves[i][0], staves[i + per - 1][1]) for i in range(0, len(staves), per)]

    row_ink = (image < 128).sum(axis=1)
    cuts = [0]
    for (_, bottom), (top, _) in zip(systems, systems[1:]):
        cuts.append(bottom + int(np.argmin(row_ink[bottom:top])))
    cuts.append(image.shape[0])
    return [image[a:b] for a, b in zip(cuts, cuts[1:])]


def save_png(image: np.ndarray, path: Path) -> None:
    """日本語パスでも保存できるように imencode 経由で書き出す。"""
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"保存に失敗: {path}")
    buf.tofile(str(path))


def preprocess(src: Path, out_dir: Path, by_system: bool = False) -> list[Path]:
    """前処理した画像を out_dir に保存する。

    by_system=True のときは段ごとに pageNN_sysMM.png として保存する
    （ファイル名順 = 楽譜の順番になる）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    page_no = 0
    for spread in load_pages(src):
        for page in split_spread(spread):
            page_no += 1
            page = binarize(upscale(trim_margin(page)))
            if by_system:
                parts = {f"page{page_no:02d}_sys{i:02d}": img
                         for i, img in enumerate(split_systems(page), start=1)}
            else:
                parts = {f"page{page_no:02d}": page}
            for name, img in parts.items():
                path = out_dir / f"{name}.png"
                save_png(img, path)
                written.append(path)
                print(f"  {path}  ({img.shape[1]}x{img.shape[0]})")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="楽譜PDF/画像をOMR用のPNGにする")
    parser.add_argument("src", type=Path, help="楽譜のPDFまたは画像")
    parser.add_argument("out_dir", type=Path, help="出力フォルダ（scores/ 以下を推奨）")
    parser.add_argument("--systems", action="store_true", help="段ごとに分けて保存する")
    args = parser.parse_args()
    print(f"前処理: {args.src}")
    preprocess(args.src, args.out_dir, by_system=args.systems)


if __name__ == "__main__":
    main()
