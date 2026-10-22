#!/usr/bin/env bash
# The Azure HTTP mirror can throttle large TeX downloads below the job timeout.
set -euo pipefail
for source in /etc/apt/apt-mirrors.txt /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
  if [[ -f "$source" ]]; then
    sudo sed -i 's|http://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' "$source"
  fi
done
sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
sudo env DEBIAN_FRONTEND=noninteractive apt-get \
  -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
  install -y --no-install-recommends \
  fonts-dejavu-core latexmk pandoc poppler-utils \
  texlive-fonts-recommended texlive-latex-extra texlive-xetex \
  "$@"
