#!/usr/bin/env bash
set -euo pipefail
bash "$(dirname -- "$0")/install_ubuntu_packages.sh" --no-install-recommends \
  fonts-dejavu-core lmodern latexmk pandoc poppler-utils \
  texlive-fonts-recommended texlive-latex-extra texlive-xetex \
  "$@"
