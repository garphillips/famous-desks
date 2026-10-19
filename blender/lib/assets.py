"""Locate third-party assets (textures, models, HDRIs) in the shared cache.

Assets are listed with source and licence in blender/assets/manifest/*.json and
downloaded by blender/assets/fetch.py. Never bundle an asset that isn't in a
manifest: the manifests are the site's credits and licence record.
"""

import glob
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get(
    "OFFICE_TOUR_ASSETS", os.path.expanduser("~/Library/Caches/office-tour/assets")
)


def manifest():
    assets = {}
    for path in sorted(glob.glob(os.path.join(HERE, "assets", "manifest", "*.json"))):
        with open(path) as fh:
            assets.update(json.load(fh))
    return assets


def path(asset_id, name=""):
    """Absolute path to an asset's folder, or a file inside it (may be in a subfolder of an extracted zip)."""
    if asset_id not in manifest():
        raise KeyError(f"Asset {asset_id!r} isn't in any blender/assets/manifest/*.json")
    folder = os.path.join(CACHE, asset_id)
    if not name:
        return folder
    direct = os.path.join(folder, name)
    if os.path.exists(direct):
        return direct
    found = glob.glob(os.path.join(folder, "**", name), recursive=True)
    if found:
        return found[0]
    raise FileNotFoundError(f"{asset_id}/{name} not in the cache; run: python3 -I blender/assets/fetch.py")
