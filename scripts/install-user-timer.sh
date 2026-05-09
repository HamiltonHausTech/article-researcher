#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
user_unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
service_name="article-digest.service"
timer_name="article-digest.timer"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; this installer is for Linux hosts with systemd." >&2
  exit 1
fi

if [[ ! -x "$repo_dir/.venv/bin/python" ]]; then
  echo "Missing virtualenv python: $repo_dir/.venv/bin/python" >&2
  echo "Run: cd $repo_dir && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "$user_unit_dir"
cp "$repo_dir/systemd/$service_name" "$user_unit_dir/$service_name"
cp "$repo_dir/systemd/$timer_name" "$user_unit_dir/$timer_name"

systemctl --user daemon-reload
systemctl --user enable --now "$timer_name"

echo "Installed user systemd timer: $timer_name"
echo
echo "Validate with:"
echo "  systemctl --user list-timers $timer_name"
echo "  systemctl --user start $service_name"
echo "  journalctl --user -u $service_name -n 100 --no-pager"
echo
if command -v loginctl >/dev/null 2>&1; then
  if loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
    echo "User lingering is enabled; the timer can run without an active login session."
  else
    echo "Optional but recommended for unattended boot-time runs:"
    echo "  sudo loginctl enable-linger $USER"
  fi
fi
