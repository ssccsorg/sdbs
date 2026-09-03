# Third-Party Notices

SDBS orchestrates external tools at build time and redistributes several of them inside the published Docker image `ghcr.io/ssccsorg/sdbs`. This file lists those components with their licenses and source locations. SDBS itself is licensed under the Apache License 2.0 (see `LICENSE`).

The Dockerfile installs each component from its official upstream distribution and pins the version where a pin exists. License texts that ship inside the installed trees are copied verbatim into `/usr/local/share/licenses/` during the image build, preserving their original layout under `quarto/`, `tinytex/`, and `uv-tools/`. The GPL-2.0 text for the Pandoc binary bundled with Quarto CLI is installed as `/usr/local/share/licenses/pandoc/COPYING-GPL-2.0`. This `NOTICE.md` is installed as `/usr/local/share/licenses/NOTICE.md`.

Components redistributed in the Docker image:

| Component | Version | License | Source |
|---|---|---|---|
| Quarto CLI | 1.9.35 | MIT License, Copyright (c) 2020-2024 Posit Software, PBC | https://github.com/quarto-dev/quarto-cli/tree/v1.9.35 |
| Pandoc | bundled with Quarto CLI | GPL-2.0-or-later | https://github.com/jgm/pandoc |
| TinyTeX | TeX Live based distribution | per-package licenses (LPPL, GPL, and others), texts under `texmf-dist/doc` | https://github.com/rstudio/tinytex-releases, https://tug.org/texlive |
| c2patool | 0.9.12 | Apache-2.0 OR MIT | https://github.com/contentauth/c2patool/tree/v0.9.12 |
| rumdl | 0.1.86 | MIT License | https://github.com/rvben/rumdl |
| uv | latest from ghcr.io/astral-sh/uv | MIT OR Apache-2.0 | https://github.com/astral-sh/uv |

apt packages installed by the image carry their copyright and license texts under `/usr/share/doc/`. Python packages installed into the image carry their metadata, including license text where published, in their installed distributions under the Python site-packages directory.

No component above is modified by SDBS. The image distributes each component as a separate program invoked through its own interface. SDBS has no plans to use the Quarto trademark, and this notice does not imply endorsement by any of the listed copyright holders.

References and license texts:

- https://quarto.org/license.html
- https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt
- https://www.apache.org/licenses/LICENSE-2.0
- https://opensource.org/license/mit/
