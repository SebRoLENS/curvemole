#!/usr/bin/env bash
# GitHub's Azure Ubuntu mirror can become unreachable during runner setup.
set -euo pipefail
for source in /etc/apt/apt-mirrors.txt /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
  if [[ -f "$source" ]]; then
    sudo sed -Ei \
      -e 's#https?://azure\.archive\.ubuntu\.com/ubuntu#https://archive.ubuntu.com/ubuntu#g' \
      -e 's#http://(archive|security)\.ubuntu\.com/ubuntu#https://\1.ubuntu.com/ubuntu#g' \
      "$source"
  fi
done
options=(-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
sudo apt-get "${options[@]}" -o APT::Update::Error-Mode=any update
sudo env DEBIAN_FRONTEND=noninteractive apt-get "${options[@]}" \
  install -y "$@"
