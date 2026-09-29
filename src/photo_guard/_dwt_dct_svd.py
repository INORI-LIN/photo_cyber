"""Vendored transcription of ``imwatermark/dwtDctSvd.py`` (invisible-watermark 0.2.0).

G1: the core install must not drag torch in, and ``invisible-watermark`` imports torch at
import time (``rivaGan.py`` → ``import torch``) no matter which method is used. The
DWT-DCT-SVD arithmetic therefore lives in-repo instead of coming through that dependency.

The class region below is byte-for-byte the upstream code (oracle sha256
221c856e83516892e9217b99e1851097726d8a4a1fc2020c1c8de5d8a03a46d7), quirks included on purpose: the H/V detail-band swap in ``encode``, the
``s[0] // scale + 0.25 + 0.5 * wmBit`` quantisation, the ``num % wmLen`` wraparound, the
shared ``scores`` list across channels, and the dead code after ``return score``.

Do not "fix" anything here — ``watermark_invisible._CarrierEmbed`` subclasses
``EmbedDwtDctSvd`` so the P11 correction stays an override. Do not rename or privatise the
class either: the transcription check compares this region against the upstream text
verbatim, and ``docs/fix-plan.md`` §6 G1 forbids touching the quirks.

Equivalence evidence (spike A/A'/B/C/D/E/F, 2026-09-28, all green): five ``np.array_equal``
pairs with identical sha256 (sizes 512²/511×507/260×330, scales covering the shipped vector,
the library default, the legacy carrier and a dual-channel vector, plus a non-ASCII payload
and 37-bit non-byte-aligned bits); the repo's P11 path bit-identical to a fixed variant of
this copy; byte and bit round trips; two pre-removal fixtures decoded exactly; a subprocess
probe showing this module alone pulls in neither torch nor imwatermark; and the verbatim
3192-character class-region check. Material lives in ``spikes/g1/`` outside the repository.

Source: https://pypi.org/project/invisible-watermark/ 0.2.0 (MIT). Licence text below is
copied from the distribution's ``dist-info/LICENSE`` (sha256 fb12dda69d231690bd725fea224fd6016d4492465a9e8dcafadec162b2243474).

------------------------------------------------------------------------------
MIT License

Copyright (c) 2021 ShieldMnt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import cv2
import numpy as np
import pywt

__all__ = ["embed_bits", "decode_bits"]


class EmbedDwtDctSvd(object):
    def __init__(self, watermarks=[], wmLen=8, scales=[0,36,0], block=4):
        self._watermarks = watermarks
        self._wmLen = wmLen
        self._scales = scales
        self._block = block

    def encode(self, bgr):
        (row, col, channels) = bgr.shape

        yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)

        for channel in range(2):
            if self._scales[channel] <= 0:
                continue

            ca1,(h1,v1,d1) = pywt.dwt2(yuv[:row//4*4,:col//4*4,channel], 'haar')
            self.encode_frame(ca1, self._scales[channel])

            yuv[:row//4*4,:col//4*4,channel] = pywt.idwt2((ca1, (v1,h1,d1)), 'haar')

        bgr_encoded = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
        return bgr_encoded

    def decode(self, bgr):
        (row, col, channels) = bgr.shape

        yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)

        scores = [[] for i in range(self._wmLen)]
        for channel in range(2):
            if self._scales[channel] <= 0:
                continue

            ca1,(h1,v1,d1) = pywt.dwt2(yuv[:row//4*4,:col//4*4,channel], 'haar')

            scores = self.decode_frame(ca1, self._scales[channel], scores)

        avgScores = list(map(lambda l: np.array(l).mean(), scores))

        bits = (np.array(avgScores) * 255 > 127)
        return bits

    def decode_frame(self, frame, scale, scores):
        (row, col) = frame.shape
        num = 0

        for i in range(row//self._block):
            for j in range(col//self._block):
                block = frame[i*self._block : i*self._block + self._block,
                              j*self._block : j*self._block + self._block]

                score = self.infer_dct_svd(block, scale)
                wmBit = num % self._wmLen
                scores[wmBit].append(score)
                num = num + 1

        return scores

    def diffuse_dct_svd(self, block, wmBit, scale):
        u,s,v = np.linalg.svd(cv2.dct(block))

        s[0] = (s[0] // scale + 0.25 + 0.5 * wmBit) * scale
        return cv2.idct(np.dot(u, np.dot(np.diag(s), v)))

    def infer_dct_svd(self, block, scale):
        u,s,v = np.linalg.svd(cv2.dct(block))

        score = 0
        score = int ((s[0] % scale) > scale * 0.5)
        return score
        if score >= 0.5:
            return 1.0
        else:
            return 0.0

    def encode_frame(self, frame, scale):
        '''
        frame is a matrix (M, N)

        we get K (watermark bits size) blocks (self._block x self._block)

        For i-th block, we encode watermark[i] bit into it
        '''
        (row, col) = frame.shape
        num = 0
        for i in range(row//self._block):
            for j in range(col//self._block):
                block = frame[i*self._block : i*self._block + self._block,
                              j*self._block : j*self._block + self._block]
                wmBit = self._watermarks[(num % self._wmLen)]


                diffusedBlock = self.diffuse_dct_svd(block, wmBit, scale)
                frame[i*self._block : i*self._block + self._block,
                      j*self._block : j*self._block + self._block] = diffusedBlock

                num = num+1


def embed_bits(
    bgr: np.ndarray, bits, *, scales=(0, 36, 0), block: int = 4
) -> np.ndarray:
    """Bit-level embed (the repo's public path keeps its own fix on top)."""
    watermarks = [int(bit) % 2 for bit in bits]
    encoder = EmbedDwtDctSvd(
        watermarks=watermarks, wmLen=len(watermarks), scales=list(scales), block=block
    )
    return encoder.encode(bgr)


def decode_bits(
    bgr: np.ndarray, wm_len: int, *, scales=(0, 36, 0), block: int = 4
) -> np.ndarray:
    """Bit-level decode; ``wm_len == 0`` raises ``ZeroDivisionError`` exactly as upstream."""
    decoder = EmbedDwtDctSvd(watermarks=[], wmLen=wm_len, scales=list(scales), block=block)
    return decoder.decode(bgr)
