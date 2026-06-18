"""Subject region detection (AGENTS.md 三③: 「压在脸部 / 主体关键纹理上」).

Three-tier fallback so the layer always returns *some* meaningful region:

1. Faces via OpenCV's bundled Haar cascade (`haarcascade_frontalface_default.xml`).
   Zero extra deps — the XML ships with `opencv-python-headless`.
2. Saliency via Sobel-magnitude integral image: find the H×W window with the
   highest aggregate edge energy. Catches non-face main subjects (objects,
   pets, products) without an ML model.
3. Geometric center fallback — last resort if both above degenerate.

All detectors return a list of `(x, y, w, h)` boxes in image pixel space.
The visible-watermark layer picks the largest box.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h

    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def _haar_path() -> str:
    return cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


def detect_faces(image_bgr: np.ndarray) -> list[Box]:
    """Return frontal face boxes; empty list if none found."""
    cascade = cv2.CascadeClassifier(_haar_path())
    if cascade.empty():
        return []
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    h, w = gray.shape
    min_side = max(60, min(h, w) // 12)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.15,
        minNeighbors=5,
        minSize=(min_side, min_side),
    )
    return [Box(int(x), int(y), int(bw), int(bh)) for (x, y, bw, bh) in faces]


def detect_salient_box(
    image_bgr: np.ndarray, *, target_frac: float = 0.30
) -> Box:
    """Pick the rectangle of size ~target_frac of the image with max edge energy.

    Uses Sobel magnitude → integral image → single sliding-window max. O(W·H).
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    sx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(sx, sy)

    h, w = mag.shape
    bw = max(64, int(w * target_frac))
    bh = max(64, int(h * target_frac))
    bw = min(bw, w)
    bh = min(bh, h)

    integral = cv2.integral(mag)  # (h+1, w+1)

    # vectorised box-sum over all valid top-left corners
    ys = np.arange(0, h - bh + 1)
    xs = np.arange(0, w - bw + 1)
    A = integral[np.ix_(ys, xs)]
    B = integral[np.ix_(ys, xs + bw)]
    C = integral[np.ix_(ys + bh, xs)]
    D = integral[np.ix_(ys + bh, xs + bw)]
    sums = D - B - C + A

    flat_idx = int(np.argmax(sums))
    yi, xi = divmod(flat_idx, sums.shape[1])
    return Box(int(xs[xi]), int(ys[yi]), bw, bh)


def detect_subject(image_bgr: np.ndarray) -> Box:
    """Return the best subject box, applying the three-tier fallback."""
    faces = detect_faces(image_bgr)
    if faces:
        return max(faces, key=lambda b: b.area)
    try:
        return detect_salient_box(image_bgr)
    except cv2.error:
        h, w = image_bgr.shape[:2]
        bw, bh = int(w * 0.6), int(h * 0.6)
        return Box((w - bw) // 2, (h - bh) // 2, bw, bh)
