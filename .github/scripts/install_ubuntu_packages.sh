#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=/etc/os-release
. /etc/os-release
archive=https://archive.ubuntu.com/ubuntu
security=https://security.ubuntu.com/ubuntu

release_available() {
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 4 --max-time 8 --output /dev/null "$1/dists/$2/InRelease"
}

if ! release_available "$archive" "$VERSION_CODENAME" ||
   ! release_available "$security" "$VERSION_CODENAME-security"; then
  # Listed by Launchpad as an official Ubuntu archive mirror. APT still verifies
  # the signed metadata with the runner's existing Ubuntu archive keyring.
  archive=https://mirror.math.princeton.edu/pub/ubuntu
  security=$archive
  echo "Canonical archive unavailable; using the Princeton Ubuntu mirror."
  release_available "$archive" "$VERSION_CODENAME"
  release_available "$security" "$VERSION_CODENAME-security"
fi

for source in /etc/apt/apt-mirrors.txt /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
  if [[ -f "$source" ]]; then
    sudo sed -Ei \
      -e "s#https?://(azure\\.)?archive\\.ubuntu\\.com/ubuntu#$archive#g" \
      -e "s#https?://security\\.ubuntu\\.com/ubuntu#$security#g" \
      "$source"
  fi
done
options=(-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
sudo apt-get "${options[@]}" -o APT::Update::Error-Mode=any update
sudo env DEBIAN_FRONTEND=noninteractive apt-get "${options[@]}" install -y "$@"
