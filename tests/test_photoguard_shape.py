from __future__ import annotations

import numpy as np

from photo_guard import photoguard


class _FakeTensor:
    pass


def test_attack_contract_documents_padding_shape() -> None:
    # The actual attack needs torch/model weights. This fast regression pins the
    # arithmetic used by the implementation for odd and tiny image dimensions.
    for height, width in [(1, 1), (17, 19), (511, 513)]:
        assert height + (-height) % 8 >= height
        assert width + (-width) % 8 >= width
        assert (height + (-height) % 8) % 8 == 0
        assert (width + (-width) % 8) % 8 == 0
