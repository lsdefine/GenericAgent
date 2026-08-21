"""Generate a .DS_Store file for DMG layout.

Usage: python3 gen_ds_store.py <output-path> <app-name>

Creates a .DS_Store that configures Finder to display:
- 540x380 window
- icon view, 128px icons
- <app-name> at (140, 190), Applications at (400, 190)
"""
import sys
import struct
from ds_store import DSStore, DSStoreEntry
from mac_alias import Alias
import plistlib

def main():
    output_path = sys.argv[1]
    app_name = sys.argv[2]

    with DSStore.open(output_path, 'w+') as ds:
        # Icon view properties for the folder
        icvp = {
            'backgroundColorBlue': 1.0,
            'backgroundColorGreen': 1.0,
            'backgroundColorRed': 1.0,
            'backgroundType': 1,  # 1 = solid color
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
        ds['.'] = DSStoreEntry('.', 'icvp', plistlib.dumps(icvp, fmt=plistlib.FMT_BINARY))

        # Window bounds/settings
        # vSrn = view style (icnv = icon view)
        ds['.'] = DSStoreEntry('.', 'vSrn', 1)

        # bwsp = browser window settings plist
        bwsp = {
            'WindowBounds': '{{100, 100}, {540, 380}}',
            'ShowPathbar': False,
            'ShowSidebar': False,
            'ShowStatusBar': False,
            'ShowToolbar': False,
            'ShowTabView': False,
            'SidebarWidth': 0,
        }
        ds['.'] = DSStoreEntry('.', 'bwsp', plistlib.dumps(bwsp, fmt=plistlib.FMT_BINARY))

        # Icon positions (Iloc = icon location, 16 bytes: x(4) + y(4) + padding(8))
        # GenericAgent.app at (140, 190)
        iloc_app = struct.pack('>II', 140, 190) + b'\xff\xff\xff\xff\xff\xff\x00\x00'
        ds[app_name] = DSStoreEntry(app_name, 'Iloc', iloc_app)

        # Applications at (400, 190)
        iloc_apps = struct.pack('>II', 400, 190) + b'\xff\xff\xff\xff\xff\xff\x00\x00'
        ds['Applications'] = DSStoreEntry('Applications', 'Iloc', iloc_apps)

    print(f"Generated: {output_path}")

if __name__ == '__main__':
    main()
