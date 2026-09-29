# Third-party notices

photo-guard is distributed under the MIT licence (see `LICENSE`). This file records the
licences of the third-party components that ship with it or are required to build it.

Two things are hand-maintained and never generated: this file's header sections and the
copyleft texts under `licenses/` (`GPL-3.0.txt`, `LGPL-3.0.txt`, kept in full because
PySide6/Qt is shipped under LGPL-3.0). Everything below a `## <platform>` heading is
generated: run `uv run python packaging/generate_notices.py` **on that platform, in the
shipping environment** (`--extra photoguard --extra desktop --group package`) to write or
refresh its section, and `... --check` to fail loudly when the section no longer matches what
is installed. `--check` validates one platform's section at a time.

## Bundled model weights

| component | license | source | revision |
|---|---|---|---|
| sd-vae-ft-mse (Stable Diffusion VAE) | MIT | https://huggingface.co/stabilityai/sd-vae-ft-mse | main（P15 将钉到不可变 revision） |

The weights are downloaded by `photo-guard download-models` and baked into the Docker image
and the desktop bundles; they are MIT-licensed and unmodified.


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
