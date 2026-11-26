# Third-party notices

photo-guard is distributed under the MIT licence (see `LICENSE`). This file records the
licences of the third-party components that ship with it or are required to build it.

The header and sections before the platform tables are hand-maintained, as are the full
third-party texts under `licenses/` (GPL-3.0, LGPL-3.0 and the OpenCV wheel's bundled
notices). The `Darwin / arm64` and `Windows / AMD64` tables are generated in the desktop
shipping environment (`--extra photoguard --extra desktop --group package`). The Linux table
is measured separately in the Docker image's `photoguard --no-dev` environment. Run
`uv run python packaging/generate_notices.py` in the corresponding environment to refresh
its own platform table; `--check` rejects missing or extra rows in that table only. Rows
reflect distribution metadata and do not supersede bundled-component licences below.

## Bundled model weights

| component | license | source | revision |
|---|---|---|---|
| sd-vae-ft-mse (Stable Diffusion VAE) | MIT | https://huggingface.co/stabilityai/sd-vae-ft-mse | 31f26fdeee1355a5c34592e401dd41e45d25a493 |

The weights are downloaded by `photo-guard download-models` (pinned to the immutable revision
above, `*.json` + `*.safetensors` only) and baked into the Docker image and the desktop
bundles; they are MIT-licensed and unmodified.

## Bundled source and wheel components

| component | source distribution version | licence | source and notice |
|---|---|---|---|
| Vendored `imwatermark/dwtDctSvd.py` from invisible-watermark | 0.2.0 | MIT | https://pypi.org/project/invisible-watermark/ — transcribed in `src/photo_guard/_dwt_dct_svd.py`, which carries the complete upstream MIT text and Copyright (c) 2021 ShieldMnt. |
| FFmpeg bundled in the opencv-python-headless wheel | opencv-python-headless 4.13.0.92; FFmpeg version not stated by the wheel notice | LGPL-2.1 | https://github.com/opencv/opencv-python — the full wheel-provided third-party notice and licence texts are in `licenses/LICENSE-3RD-PARTY-opencv.txt`. |
| Qt runtime libraries and plugins in the PySide6_Essentials and PySide6_Addons wheels (installed with PySide6; the GUI imports QtCore, QtGui and QtWidgets) | PySide6 6.11.1; Qt 6.11.1 as reported by `qVersion()` | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (wheel metadata); used here under LGPL-3.0-only | https://pyside.org — the full LGPL-3.0 text and the GPL-3.0 text it incorporates are `licenses/LGPL-3.0.txt` and `licenses/GPL-3.0.txt`; `packaging/build_desktop.py` includes the whole `licenses/` directory, so both ship inside the desktop bundles. |
| Native libraries bundled in the Pillow wheel; on macOS arm64, 18 dylibs under `PIL/.dylibs`: libavif, brotli (common, dec), FreeType, HarfBuzz, libjpeg-turbo, Little CMS 2, liblzma, OpenJPEG, libpng, LibTIFF, libwebp (webp, webpdemux, webpmux, sharpyuv), libxcb, libXau, zlib-ng | pillow 12.2.0; library versions as built into the wheel | per library; see the wheel's notice file | https://github.com/python-pillow/Pillow — the wheel's `pillow-12.2.0.dist-info/licenses/LICENSE` holds Pillow's MIT-CMU text followed by 21 per-library sections (AOM through ZSTD), one for every library family behind the 18 dylibs; it is one combined file whose sections go beyond this wheel (XDMCP, for example, has no counterpart here). The Windows and Linux wheels' library sets were not measured here. |
| uv binary in the Docker image: `COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv` in the `runtime` stage, which the default `release` stage builds on; the image entrypoint runs it | uv 0.13.7 | MIT OR Apache-2.0 | https://github.com/astral-sh/uv — upstream's published dual licence (`license = "MIT OR Apache-2.0"` in the workspace `Cargo.toml` at the 0.13.7 tag); the image copies only the binary, not uv's licence files. |

The generated `opencv-python-headless` platform row reports the OpenCV distribution's
Apache 2.0 metadata; it does not describe every library bundled in its wheel. The copied
third-party file comes from the pinned 4.13.0.92 macOS arm64 wheel with LF line endings.
The pinned Windows wheel carries the same full text with CRLF endings; checks enforce each
wheel's native bytes and require them to match the shipped LF text after the documented
line-ending conversion. Linux ships the same LF bytes. This notice does not by itself
certify all binary redistribution obligations.

The generated `PySide6`, `PySide6_Essentials`, `PySide6_Addons` and `pillow` rows report
distribution metadata only: they name neither the Qt build nor the libraries bundled in
Pillow's wheel, and uv appears in no platform table because the image copies it as a binary
rather than installing it as a Python distribution. Known residual: the desktop bundles do
not yet ship the full notice texts for Pillow's bundled native libraries, for third-party
code built into the Qt libraries (for example libpng in the macOS QtGui framework) or for
native libraries inside the torch wheel (for example libomp); Qt's own LGPL-3.0 and GPL-3.0
texts do ship via `licenses/`.

## Darwin / arm64

Rows measured in this environment with ``importlib.metadata``. Other platforms' sections are
appended by running this tool on those platforms; ``--check`` validates one section at a time.

| name | version | license | source |
|---|---|---|---|
| accelerate | 1.14.0 | Apache | https://github.com/huggingface/accelerate |
| annotated-doc | 0.0.4 | MIT | https://github.com/fastapi/annotated-doc |
| anyio | 4.14.0 | MIT | https://anyio.readthedocs.io/en/latest/ |
| certifi | 2026.6.17 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.4.7 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.4.1 | BSD-3-Clause | https://click.palletsprojects.com/page/changes/ |
| diffusers | 0.38.0 | Apache 2.0 License | https://github.com/huggingface/diffusers |
| filelock | 3.29.4 | MIT | https://py-filelock.readthedocs.io |
| fsspec | 2026.6.0 | BSD-3-Clause | https://filesystem-spec.readthedocs.io/en/latest/changelog.html |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| hf-xet | 1.5.1 | Apache-2.0 | https://huggingface.co/docs/hub/xet/index |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx/blob/master/CHANGELOG.md |
| huggingface_hub | 1.19.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna/blob/master/HISTORY.md |
| importlib_metadata | 9.0.0 | Apache-2.0 | https://github.com/python/importlib_metadata |
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| Jinja2 | 3.1.6 | BSD License | https://jinja.palletsprojects.com/changes/ |
| markdown-it-py | 4.2.0 | MIT License | https://markdown-it-py.readthedocs.io |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://palletsprojects.com/donate |
| mdurl | 0.1.2 | MIT License | https://github.com/executablebooks/mdurl |
| mpmath | 1.3.0 | BSD | http://mpmath.org/ |
| networkx | 3.6.1 | BSD-3-Clause | https://networkx.org/ |
| Nuitka | 4.1.3 | GNU Affero General Public License v3 | https://nuitka.net |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| opencv-python-headless | 4.13.0.92 | Apache 2.0 | https://github.com/opencv/opencv-python |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | https://packaging.pypa.io/ |
| pillow | 12.2.0 | MIT-CMU | https://pillow.readthedocs.io/en/stable/releasenotes/index.html |
| pluggy | 1.6.0 | MIT | Holger Krekel <holger@merlinux.eu> |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Pygments | 2.20.0 | BSD-2-Clause | https://pygments.org |
| PySide6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Addons | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Essentials | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| pytest | 9.1.0 | MIT | https://docs.pytest.org/en/stable/changelog.html |
| PyWavelets | 1.9.0 | MIT AND BSD-3-Clause | https://github.com/PyWavelets/pywt |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| regex | 2026.5.9 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io |
| rich | 15.0.0 | MIT | https://rich.readthedocs.io/en/latest/ |
| safetensors | 0.8.0 | Apache Software License | https://github.com/huggingface/safetensors |
| setuptools | 81.0.0 | MIT | https://github.com/pypa/setuptools |
| shellingham | 1.5.4 | ISC License | https://github.com/sarugaku/shellingham |
| shiboken6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| sympy | 1.14.0 | BSD | https://sympy.org |
| torch | 2.12.1 | BSD-3-Clause | https://pytorch.org |
| tqdm | 4.68.3 | MPL-2.0 AND MIT | https://tqdm.github.io |
| typer | 0.25.1 | MIT | https://github.com/fastapi/typer |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions/issues |
| urllib3 | 2.7.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| zipp | 4.1.0 | MIT | https://github.com/jaraco/zipp |

## Linux / x86_64

Rows measured in this environment with ``importlib.metadata``. Other platforms' sections are
appended by running this tool on those platforms; ``--check`` validates one section at a time.

| name | version | license | source |
|---|---|---|---|
| accelerate | 1.14.0 | Apache | https://github.com/huggingface/accelerate |
| annotated-doc | 0.0.4 | MIT | https://github.com/fastapi/annotated-doc |
| anyio | 4.14.0 | MIT | https://anyio.readthedocs.io/en/latest/ |
| certifi | 2026.6.17 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.4.7 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.4.1 | BSD-3-Clause | https://click.palletsprojects.com/page/changes/ |
| cuda-bindings | 13.3.1 | LicenseRef-NVIDIA-SOFTWARE-LICENSE | https://github.com/NVIDIA/cuda-python |
| cuda-pathfinder | 1.5.5 | Apache-2.0 | https://github.com/NVIDIA/cuda-python |
| cuda-toolkit | 13.0.2 | declared in package metadata | https://developer.nvidia.com/cuda-toolkit |
| diffusers | 0.38.0 | Apache 2.0 License | https://github.com/huggingface/diffusers |
| filelock | 3.29.4 | MIT | https://py-filelock.readthedocs.io |
| fsspec | 2026.6.0 | BSD-3-Clause | https://filesystem-spec.readthedocs.io/en/latest/changelog.html |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| hf-xet | 1.5.1 | Apache-2.0 | https://huggingface.co/docs/hub/xet/index |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx/blob/master/CHANGELOG.md |
| huggingface_hub | 1.19.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna/blob/master/HISTORY.md |
| importlib_metadata | 9.0.0 | Apache-2.0 | https://github.com/python/importlib_metadata |
| Jinja2 | 3.1.6 | BSD License | https://jinja.palletsprojects.com/changes/ |
| markdown-it-py | 4.2.0 | MIT License | https://markdown-it-py.readthedocs.io |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://palletsprojects.com/donate |
| mdurl | 0.1.2 | MIT License | https://github.com/executablebooks/mdurl |
| mpmath | 1.3.0 | BSD | http://mpmath.org/ |
| networkx | 3.6.1 | BSD-3-Clause | https://networkx.org/ |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| nvidia-cublas | 13.1.1.3 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cuda-cupti | 13.0.85 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cuda-nvrtc | 13.0.88 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cuda-runtime | 13.0.96 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cudnn-cu13 | 9.20.0.48 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cufft | 12.0.0.61 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cufile | 1.15.1.6 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-curand | 10.4.0.35 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cusolver | 12.0.4.66 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cusparse | 12.6.3.3 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-cusparselt-cu13 | 0.8.1 | NVIDIA Proprietary Software | https://developer.nvidia.com/cusparselt |
| nvidia-nccl-cu13 | 2.29.7 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-nvjitlink | 13.0.88 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-nvshmem-cu13 | 3.4.5 | LicenseRef-NVIDIA-Proprietary | https://developer.nvidia.com/cuda-zone |
| nvidia-nvtx | 13.0.85 | Apache 2.0 | https://developer.nvidia.com/cuda-zone |
| opencv-python-headless | 4.13.0.92 | Apache 2.0 | https://github.com/opencv/opencv-python |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | https://packaging.pypa.io/ |
| pillow | 12.2.0 | MIT-CMU | https://pillow.readthedocs.io/en/stable/releasenotes/index.html |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Pygments | 2.20.0 | BSD-2-Clause | https://pygments.org |
| PyWavelets | 1.9.0 | MIT AND BSD-3-Clause | https://github.com/PyWavelets/pywt |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| regex | 2026.5.9 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io |
| rich | 15.0.0 | MIT | https://rich.readthedocs.io/en/latest/ |
| safetensors | 0.8.0 | Apache Software License | https://github.com/huggingface/safetensors |
| setuptools | 81.0.0 | MIT | https://github.com/pypa/setuptools |
| shellingham | 1.5.4 | ISC License | https://github.com/sarugaku/shellingham |
| sympy | 1.14.0 | BSD | https://sympy.org |
| torch | 2.12.1 | BSD-3-Clause | https://pytorch.org |
| tqdm | 4.68.3 | MPL-2.0 AND MIT | https://tqdm.github.io |
| triton | 3.7.1 | MIT License | https://github.com/triton-lang/triton/ |
| typer | 0.25.1 | MIT | https://github.com/fastapi/typer |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions/issues |
| urllib3 | 2.7.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| zipp | 4.1.0 | MIT | https://github.com/jaraco/zipp |

## Windows / AMD64

Rows measured in this environment with ``importlib.metadata``. Other platforms' sections are
appended by running this tool on those platforms; ``--check`` validates one section at a time.

| name | version | license | source |
|---|---|---|---|
| Jinja2 | 3.1.6 | BSD License | https://jinja.palletsprojects.com/changes/ |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://palletsprojects.com/donate |
| Nuitka | 4.1.3 | GNU Affero General Public License v3 | https://nuitka.net |
| PySide6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Addons | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Essentials | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PyWavelets | 1.9.0 | MIT AND BSD-3-Clause | https://github.com/PyWavelets/pywt |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| Pygments | 2.20.0 | BSD-2-Clause | https://pygments.org |
| accelerate | 1.14.0 | Apache | https://github.com/huggingface/accelerate |
| annotated-doc | 0.0.4 | MIT | https://github.com/fastapi/annotated-doc |
| anyio | 4.14.0 | MIT | https://anyio.readthedocs.io/en/latest/ |
| certifi | 2026.6.17 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.4.7 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.4.1 | BSD-3-Clause | https://click.palletsprojects.com/page/changes/ |
| colorama | 0.4.6 | BSD License | https://github.com/tartley/colorama |
| diffusers | 0.38.0 | Apache 2.0 License | https://github.com/huggingface/diffusers |
| filelock | 3.29.4 | MIT | https://py-filelock.readthedocs.io |
| fsspec | 2026.6.0 | BSD-3-Clause | https://filesystem-spec.readthedocs.io/en/latest/changelog.html |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| hf-xet | 1.5.1 | Apache-2.0 | https://huggingface.co/docs/hub/xet/index |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx/blob/master/CHANGELOG.md |
| huggingface_hub | 1.19.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna/blob/master/HISTORY.md |
| importlib_metadata | 9.0.0 | Apache-2.0 | https://github.com/python/importlib_metadata |
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| markdown-it-py | 4.2.0 | MIT License | https://markdown-it-py.readthedocs.io |
| mdurl | 0.1.2 | MIT License | https://github.com/executablebooks/mdurl |
| mpmath | 1.3.0 | BSD | http://mpmath.org/ |
| networkx | 3.6.1 | BSD-3-Clause | https://networkx.org/ |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| opencv-python-headless | 4.13.0.92 | Apache 2.0 | https://github.com/opencv/opencv-python |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | https://packaging.pypa.io/ |
| pillow | 12.2.0 | MIT-CMU | https://pillow.readthedocs.io/en/stable/releasenotes/index.html |
| pluggy | 1.6.0 | MIT | Holger Krekel <holger@merlinux.eu> |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| pytest | 9.1.0 | MIT | https://docs.pytest.org/en/stable/changelog.html |
| regex | 2026.5.9 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io |
| rich | 15.0.0 | MIT | https://rich.readthedocs.io/en/latest/ |
| safetensors | 0.8.0 | Apache Software License | https://github.com/huggingface/safetensors |
| setuptools | 81.0.0 | MIT | https://github.com/pypa/setuptools |
| shellingham | 1.5.4 | ISC License | https://github.com/sarugaku/shellingham |
| shiboken6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| sympy | 1.14.0 | BSD | https://sympy.org |
| torch | 2.12.1 | BSD-3-Clause | https://pytorch.org |
| tqdm | 4.68.3 | MPL-2.0 AND MIT | https://tqdm.github.io |
| typer | 0.25.1 | MIT | https://github.com/fastapi/typer |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions/issues |
| urllib3 | 2.7.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| zipp | 4.1.0 | MIT | https://github.com/jaraco/zipp |
