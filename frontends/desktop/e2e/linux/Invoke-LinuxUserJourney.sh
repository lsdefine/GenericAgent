#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --artifact <portable.tar.gz> --expected-commit <sha> [--work-dir <dir>]" >&2
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
artifact="$(realpath "$artifact")"
[[ -f "$artifact" ]] || { echo "Artifact not found: $artifact" >&2; exit 1; }
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
driver="$script_dir/../package/real_package_journey.py"
if [[ -z "$work_dir" ]]; then
  work_dir="$(mktemp -d -t ga-linux-package-e2e.XXXXXX)"
else
  mkdir -p "$work_dir"
  work_dir="$(realpath "$work_dir")"
fi
extract_dir="$work_dir/extracted"
report_dir="$work_dir/report"
driver_work="$work_dir/driver-work"
mkdir -p "$extract_dir" "$report_dir" "$driver_work"

cleanup() {
  if [[ $keep_work_dir -eq 0 ]]; then
    echo "Evidence kept at $report_dir; extracted package kept until the report is collected."
  else
    echo "Work directory kept at $work_dir"
  fi
}
trap cleanup EXIT

tar -xzf "$artifact" -C "$extract_dir"
package_root="$extract_dir/GenericAgent-Desktop-Linux-Portable"
if [[ ! -d "$package_root" ]]; then
  mapfile -t roots < <(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d)
  [[ ${#roots[@]} -eq 1 ]] || { echo "Could not identify the portable package root" >&2; exit 1; }
  package_root="${roots[0]}"
fi
chmod +x "$package_root/GenericAgent.AppImage"

sidecar="$(dirname "$artifact")/SHA256SUMS-linux.txt"
[[ -f "$sidecar" ]] || { echo "Linux SHA-256 sidecar not found: $sidecar" >&2; exit 1; }
expected_hash="$(grep -Eo '[0-9a-fA-F]{64}' "$sidecar" | head -n 1 | tr '[:upper:]' '[:lower:]')"
actual_hash="$(sha256sum "$artifact" | awk '{print $1}')"
[[ "$actual_hash" == "$expected_hash" ]] || { echo "Artifact SHA-256 mismatch" >&2; exit 1; }

python3 "$driver" \
  --platform linux \
  --artifact "$artifact" \
  --expected-commit "$expected_commit" \
  --package-root "$package_root" \
  --application-relative "GenericAgent.AppImage" \
  --runtime-relative "runtime" \
  --relocated-root "$work_dir/relocated/含 空格/GenericAgent 包" \
  --report-dir "$report_dir" \
  --work-dir "$driver_work" \
  --allow-user-settings-mutation
