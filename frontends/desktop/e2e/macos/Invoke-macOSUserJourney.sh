#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --artifact <desktop.dmg> --expected-commit <sha> [--work-dir <dir>]" >&2
}

artifact=""
expected_commit=""
work_dir=""
keep_work_dir=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) artifact="$2"; shift 2 ;;
    --expected-commit) expected_commit="$2"; shift 2 ;;
    --work-dir) work_dir="$2"; shift 2 ;;
    --keep-work-dir) keep_work_dir=1; shift ;;
    *) usage; exit 2 ;;
  esac
done

[[ -n "$artifact" && -n "$expected_commit" ]] || { usage; exit 2; }
artifact="$(cd "$(dirname "$artifact")" && pwd)/$(basename "$artifact")"
[[ -f "$artifact" ]] || { echo "Artifact not found: $artifact" >&2; exit 1; }
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
driver="$script_dir/../package/real_package_journey.py"
if [[ -z "$work_dir" ]]; then
  work_dir="$(mktemp -d -t ga-macos-package-e2e.XXXXXX)"
else
  mkdir -p "$work_dir"
  work_dir="$(cd "$work_dir" && pwd)"
fi
report_dir="$work_dir/report"
driver_work="$work_dir/driver-work"
mount_point="$work_dir/dmg"
install_app="/Applications/GenericAgent P2 E2E $$.app"
mounted=0
mkdir -p "$report_dir" "$driver_work" "$mount_point"

cleanup() {
  if [[ $mounted -eq 1 ]]; then
    hdiutil detach "$mount_point" -quiet || true
  fi
  if [[ -d "$install_app" ]]; then
    rm -rf -- "$install_app"
  fi
  if [[ $keep_work_dir -eq 1 ]]; then
    echo "Work directory kept at $work_dir"
  else
    echo "Evidence kept at $report_dir"
  fi
}
trap cleanup EXIT

[[ ! -e "$install_app" ]] || { echo "Refusing to replace existing app: $install_app" >&2; exit 1; }
sidecar="$artifact.sha256"
[[ -f "$sidecar" ]] || { echo "macOS SHA-256 sidecar not found: $sidecar" >&2; exit 1; }
expected_hash="$(grep -Eo '[0-9a-fA-F]{64}' "$sidecar" | head -n 1 | tr '[:upper:]' '[:lower:]')"
actual_hash="$(shasum -a 256 "$artifact" | awk '{print $1}')"
[[ "$actual_hash" == "$expected_hash" ]] || { echo "Artifact SHA-256 mismatch" >&2; exit 1; }

hdiutil attach "$artifact" -mountpoint "$mount_point" -nobrowse -readonly -quiet
mounted=1
source_app="$(find "$mount_point" -mindepth 1 -maxdepth 1 -type d -name '*.app' | head -n 1)"
[[ -n "$source_app" ]] || { echo "DMG does not contain an application" >&2; exit 1; }
ditto "$source_app" "$install_app"
hdiutil detach "$mount_point" -quiet
mounted=0

binary="$(find "$install_app/Contents/MacOS" -mindepth 1 -maxdepth 1 -type f -perm -111 | head -n 1)"
[[ -n "$binary" ]] || { echo "Installed application has no executable" >&2; exit 1; }
binary_relative="${binary#"$install_app"/}"

python3 "$driver" \
  --platform macos \
  --artifact "$artifact" \
  --expected-commit "$expected_commit" \
  --package-root "$install_app" \
  --application-relative "$binary_relative" \
  --runtime-relative "Contents/Resources/runtime" \
  --relocated-root "$work_dir/relocated/含 空格/GenericAgent 已移动.app" \
  --report-dir "$report_dir" \
  --work-dir "$driver_work" \
  --allow-user-settings-mutation \
  --allow-external-package
