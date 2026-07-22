#!/usr/bin/env bash
set -euo pipefail

ROOT="${ARGUS_INSTALL_ROOT:-/opt/argus}"
if [[ ! -f /etc/argus-bridge.env ]]; then
  echo "missing /etc/argus-bridge.env; existing ARGUS secret management is required" >&2
  exit 1
fi
sudo install -d -m 0755 "${ROOT}/scripts"
sudo install -d -o root -g root -m 0700 /var/lib/argus-build-identity
sudo install -d -o root -g root -m 0755 /run/argus-build-identity
sudo install -m 0755 scripts/argus_build_identity.py \
  "${ROOT}/scripts/argus_build_identity.py"
sudo install -m 0755 scripts/argus_mission_tick.py \
  "${ROOT}/scripts/argus_mission_tick.py"
sudo install -m 0755 scripts/check_argus_mission_timer.sh \
  "${ROOT}/scripts/check_argus_mission_timer.sh"
sudo install -m 0644 ops/systemd/argus-mission-tick.service \
  /etc/systemd/system/argus-mission-tick.service
sudo install -m 0644 ops/systemd/argus-mission-tick.timer \
  /etc/systemd/system/argus-mission-tick.timer
if [[ ! -f /etc/argus-mission-tick.env ]]; then
  sudo install -m 0600 ops/systemd/argus-mission-tick.env.example \
    /etc/argus-mission-tick.env
fi
sudo systemctl daemon-reload
sudo systemctl enable --now argus-mission-tick.timer
sudo systemctl is-enabled argus-mission-tick.timer
sudo systemctl is-active argus-mission-tick.timer
sudo systemctl list-timers argus-mission-tick.timer --no-pager
