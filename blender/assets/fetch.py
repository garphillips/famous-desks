"""Download the third-party assets listed in blender/assets/manifest/*.json.

    python3 -I blender/assets/fetch.py            # fetch anything missing
    python3 -I blender/assets/fetch.py --check    # list what's missing, download nothing

Assets are downloaded into a shared cache outside the repo (see lib/assets.py),
one folder per asset, so they're fetched once for every checkout. Only the
manifests (sources, licences, credits) are committed.

Manifest format (one file per area of work, e.g. textures.json):
    {
      "oak_floor": {
        "kind": "texture",               # texture | model | hdri
        "title": "Oak floor 01",
        "source": "Poly Haven",
        "page": "https://polyhaven.com/a/...",
        "author": "...",
        "license": "CC0",                # must be in ALLOWED_LICENSES
        "files": [{"url": "https://...", "name": "oak_floor_diff_2k.jpg"}]
      }
    }
Zip files are extracted into the asset's folder (path-checked).
"""

import argparse
import glob
import json
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWED_LICENSES = {"CC0", "CC-BY-4.0"}
CACHE = os.environ.get(
    "OFFICE_TOUR_ASSETS", os.path.expanduser("~/Library/Caches/office-tour/assets")
)


def load_manifest():
    assets = {}
    for path in sorted(glob.glob(os.path.join(HERE, "manifest", "*.json"))):
        with open(path) as fh:
            for asset_id, entry in json.load(fh).items():
                if asset_id in assets:
                    sys.exit(f"Duplicate asset id {asset_id!r} in {os.path.basename(path)}")
                entry["_manifest"] = os.path.basename(path)
                assets[asset_id] = entry
    return assets


# Only plain data comes out of zips: never .blend/.usd/scripts, which can carry code.
EXTRACT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".exr", ".hdr", ".tif", ".tiff", ".webp",
                      ".gltf", ".glb", ".bin", ".fbx", ".obj", ".mtl"}


def safe_extract(zip_path, dest):
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            if member.is_dir():
                continue
            if os.path.splitext(member.filename)[1].lower() not in EXTRACT_EXTENSIONS:
                print(f"  skipping {member.filename}")
                continue
            target = os.path.realpath(os.path.join(dest, member.filename))
            if not target.startswith(os.path.realpath(dest) + os.sep):
                raise ValueError(f"Unsafe path in {zip_path}: {member.filename}")
            z.extract(member, dest)


def fetch(asset_id, entry, check_only):
    if entry.get("license") not in ALLOWED_LICENSES:
        sys.exit(f"{asset_id}: licence {entry.get('license')!r} not allowed ({sorted(ALLOWED_LICENSES)})")
    folder = os.path.join(CACHE, asset_id)
    missing = [f for f in entry["files"] if not os.path.exists(os.path.join(folder, f["name"]))]
    if not missing:
        return 0
    if check_only:
        print(f"missing: {asset_id} ({len(missing)} files)")
        return len(missing)
    os.makedirs(folder, exist_ok=True)
    for f in missing:
        dest = os.path.join(folder, f["name"])
        if not os.path.realpath(dest).startswith(os.path.realpath(folder) + os.sep):
            sys.exit(f"{asset_id}: unsafe file name {f['name']!r}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)  # names may include a subfolder (glTF textures/)
        print(f"fetching {asset_id}/{f['name']}")
        req = urllib.request.Request(f["url"], headers={"User-Agent": "office-tour-asset-fetch/1"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest + ".part", "wb") as out:
            shutil.copyfileobj(r, out)
        os.replace(dest + ".part", dest)
        if dest.endswith(".zip"):
            safe_extract(dest, folder)
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    assets = load_manifest()
    missing = sum(fetch(k, v, a.check) for k, v in assets.items())
    print(f"{len(assets)} assets in manifest; cache: {CACHE}" + (f"; {missing} files missing" if a.check else ""))


main()
