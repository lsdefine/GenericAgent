#!/bin/bash
# Repackage a Tauri-bundled DMG into a clean DMG with proper Finder layout.
# Only contains .app + Applications symlink + .DS_Store for layout.
# No .VolumeIcon.icns, .background, .fseventsd or other debris.
#
# Usage: ./scripts/post-dmg.sh <path-to-dmg>
# Requires: macOS (hdiutil), Python 3 with ds_store package

set -euo pipefail

DMG_PATH="${1:-}"
HDIUTIL_BIN="${HDIUTIL_BIN:-hdiutil}"
if [[ -z "$DMG_PATH" ]]; then
  echo "Usage: $0 <path-to.dmg>" >&2
  exit 1
fi

if [[ ! -f "$DMG_PATH" ]]; then
  echo "Error: DMG not found: $DMG_PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DMG_DIR="$(cd "$(dirname "$DMG_PATH")" && pwd)"
DMG_NAME="$(basename "$DMG_PATH")"
STAGE_DIR="$(mktemp -d)"
RW_DMG="$(mktemp -u).dmg"

cleanup() {
  if [[ -n "${MOUNT_POINT:-}" ]] && mount | grep -q "$MOUNT_POINT"; then
    "$HDIUTIL_BIN" detach "$MOUNT_POINT" -force 2>/dev/null || true
  fi
  rm -rf "$STAGE_DIR" "$RW_DMG"
}
trap cleanup EXIT

# --- Step 1: Extract app from original DMG ---
echo "Mounting original DMG..."
MOUNT_OUTPUT="$("$HDIUTIL_BIN" attach "$DMG_PATH" -readonly -noverify -noautoopen -plist)"
MOUNT_POINT="$(echo "$MOUNT_OUTPUT" | grep -A1 '<key>mount-point</key>' | grep '<string>' | sed 's/.*<string>\(.*\)<\/string>.*/\1/' | head -1)"

if [[ -z "$MOUNT_POINT" ]]; then
  echo "Error: could not determine mount point" >&2
  exit 1
fi

APP_NAME=""
for item in "$MOUNT_POINT"/*.app; do
  if [[ -d "$item" ]]; then
    APP_NAME="$(basename "$item")"
    ditto "$item" "$STAGE_DIR/$APP_NAME"
    break
  fi
done

if [[ -z "$APP_NAME" ]]; then
  echo "Error: no .app found in DMG" >&2
  exit 1
fi

"$HDIUTIL_BIN" detach "$MOUNT_POINT" -quiet
unset MOUNT_POINT

# --- Step 2: Prepare stage directory ---
ln -s /Applications "$STAGE_DIR/Applications"

# Generate .DS_Store with layout metadata
python3 -c "
import struct, plistlib, sys
sys.path.insert(0, '')
from ds_store import DSStore, DSStoreEntry

app_name = '$APP_NAME'
output = '$STAGE_DIR/.DS_Store'

entries = []

# Icon positions (Iloc: x(4) + y(4) + padding(8))
iloc_app = struct.pack('>II', 140, 190) + b'\xff\xff\xff\xff\xff\xff\x00\x00'
entries.append(DSStoreEntry(app_name, 'Iloc', 'blob', iloc_app))

iloc_apps = struct.pack('>II', 400, 190) + b'\xff\xff\xff\xff\xff\xff\x00\x00'
entries.append(DSStoreEntry('Applications', 'Iloc', 'blob', iloc_apps))

# Icon view properties
icvp = {
    'backgroundColorBlue': 1.0,
    'backgroundColorGreen': 1.0,
    'backgroundColorRed': 1.0,
    'backgroundType': 1,
    'gridOffsetX': 0.0,
    'gridOffsetY': 0.0,
    'gridSpacing': 100.0,
    'iconSize': 128.0,
    'labelOnBottom': True,
    'showIconPreview': True,
    'showItemInfo': False,
    'textSize': 13.0,
    'viewOptionsVersion': 1,
    'arrangeBy': 'none',
}
entries.append(DSStoreEntry('.', 'icvp', 'blob', plistlib.dumps(icvp, fmt=plistlib.FMT_BINARY)))

# View style (1 = icon view)
entries.append(DSStoreEntry('.', 'vSrn', 'long', 1))

# Browser window settings
bwsp = {
    'WindowBounds': '{{100, 100}, {540, 380}}',
    'ShowSidebar': False,
    'ShowStatusBar': False,
    'ShowToolbar': False,
    'ShowTabView': False,
    'SidebarWidth': 0,
}
entries.append(DSStoreEntry('.', 'bwsp', 'blob', plistlib.dumps(bwsp, fmt=plistlib.FMT_BINARY)))

with DSStore.open(output, 'w+') as ds:
    for e in entries:
        ds.insert(e)
"

echo "  Stage: $APP_NAME + Applications + .DS_Store"

# --- Step 3: Create final DMG ---
VOLNAME="${APP_NAME%.app}"
CREATE_STATUS=1
for attempt in 1 2 3; do
  rm -f "$DMG_DIR/$DMG_NAME"
  if "$HDIUTIL_BIN" create \
    -volname "$VOLNAME" \
    -srcfolder "$STAGE_DIR" \
    -ov \
    -format UDZO \
    "$DMG_DIR/$DMG_NAME"; then
    CREATE_STATUS=0
    break
  else
    CREATE_STATUS=$?
  fi

  if [[ "$attempt" -lt 3 ]]; then
    echo "hdiutil create failed (attempt $attempt/3, exit $CREATE_STATUS); retrying..." >&2
    sleep $((attempt * 2))
  fi
done

if [[ "$CREATE_STATUS" -ne 0 ]]; then
  echo "Error: hdiutil create failed after 3 attempts" >&2
  exit "$CREATE_STATUS"
fi

echo "Done: $DMG_NAME ($(du -h "$DMG_DIR/$DMG_NAME" | cut -f1))"
