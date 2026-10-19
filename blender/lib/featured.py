"""Featured books: real books on a generated shelf that the website lets you pull out.

A room lists them (title, author, cover asset, real size, spine design, description) and
calls place_books() after stocking the shelf. Each one replaces a generated upright book
near the shelf position it asks for: same spot, the real book's size, its spine printed
with artwork from web/scripts/book-art.mjs. The object is tagged for export.py:
    item_of   the hotspot it belongs to (its detail on the website lists the books)
    item      the book's slug; item_json the rest of its data (title, author, summary...)
so the website can draw the book where it stands and fly it out. Featured books keep
the generated book's tiny Z wobble, so the slot looks lived in.
"""

import json
import os
import shutil
import subprocess

import bpy
from mathutils import Vector

from . import assets
from . import materials as mt
from .books import _book_mesh

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
ART_SCRIPT = os.path.join(ROOT, "web", "scripts", "book-art.mjs")
ART_BUILD = os.path.join(HERE, "build", "books")


def make_art(space, books):
    """Runs book-art.mjs for the books; returns {slug: folder with spine.png, cover.webp, art.json}."""
    node = shutil.which("node")
    if not node or not os.path.isdir(os.path.join(ROOT, "web", "node_modules", "sharp")):
        raise SystemExit("featured.py: book artwork needs node and sharp (run `npm ci` in web/)")
    out = os.path.join(ART_BUILD, space)
    os.makedirs(out, exist_ok=True)
    spec = [dict(b, cover=assets.path(b["cover"], "cover.jpg")) for b in books]
    spec = [{k: v for k, v in b.items() if k != "summary"} for b in spec]
    path = os.path.join(out, "books.json")
    with open(path, "w") as fh:
        json.dump(spec, fh, indent=1)
    subprocess.run([node, ART_SCRIPT, "--books", path, "--out", out], check=True)
    return {b["slug"]: os.path.join(out, b["slug"]) for b in books}


def _spine_material(slug, folder, cover_colour):
    """Printed spine (UV u 0..1 across it, v up), plain boards in the cover's colour."""
    mat, g, bsdf = mt._new(f"book_featured_{slug}", (0.5, 0.5, 0.5))
    img = bpy.data.images.load(os.path.join(folder, "spine.png"), check_existing=True)
    uv = g.node("ShaderNodeUVMap", uv_map="UVMap").outputs["UV"]
    u, v, _ = g.sep(uv)
    spine = g.math("LESS_THAN", u, 1.5)
    art = g.tex(img, g.vec(g.math("MINIMUM", u, 1.0), v, 0.0))
    col = g.mix(spine, cover_colour, art)
    p = g.obj_coords()
    # slightly rubbed spine edges, as on the generated books
    edge = g.math("MINIMUM", g.math("MINIMUM", u, g.math("SUBTRACT", 1.0, u)),
                  g.math("MULTIPLY", g.math("MINIMUM", v, g.math("SUBTRACT", 1.0, v)), 3.0))
    wear = g.math("MULTIPLY", g.map(edge, 0.0, 0.05, 1.0, 0.0), g.map(g.noise(p, 180.0, 3.0, 0.6), 0.45, 0.7))
    col = g.mix(g.math("MULTIPLY", g.math("MULTIPLY", wear, spine), 0.3), col, (0.5, 0.48, 0.45))
    relief = g.math("ADD", g.math("MULTIPLY", g.noise(p, 300.0, 2.0, 0.5), 0.15),
                    g.math("MULTIPLY", g.noise(p, 1500.0, 2.0, 0.6), 0.1))
    mt._principled(g, bsdf, color=col, rough=g.map(g.math("MULTIPLY", wear, 0.6), 0.0, 1.0, 0.42, 0.7),
                   coat=0.25, coat_rough=0.15, normal=g.bump(relief, 0.15, 0.0005))
    return mat


def _hex_linear(h):
    srgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)


def _upright(obj):
    """Stands straight on its shelf: local up is world up, spine facing into the room."""
    return obj.matrix_world.to_3x3().col[2].normalized().z > 0.999


def _world_box(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return lo, hi


def _overlaps(a, b, pad=0.003):
    return all(a[0][i] - pad < b[1][i] and b[0][i] - pad < a[1][i] for i in range(3))


def _candidates(shelf_books):
    """Upright generated books nothing rests on or leans against (no lying or leaning book touches them)."""
    boxes = {o: _world_box(o) for o in shelf_books}
    loose = [o for o in shelf_books if not _upright(o)]
    out = []
    for o in shelf_books:
        if not _upright(o) or o.get("item"):
            continue
        if any(_overlaps(boxes[o], boxes[x]) for x in loose):
            continue
        out.append(o)
    return out


def place_books(space, prefix, books, mats, hotspot):
    """Swap generated books on shelf `prefix` (books.bookshelf's name) for the featured ones.

    books: [{slug, title, author, cover (asset id), kind ('paperback'|'hardback'),
             size: (thickness, height, width) m, near: (x, y, z) world point to stand near,
             spine: {...} (see book-art.mjs), summary}]
    """
    art = make_art(space, books)
    shelf = [o for o in bpy.data.collections["Books"].objects if o.name.startswith(f"{prefix}_book_")]
    for order, book in enumerate(books):
        pool = _candidates(shelf)
        t, h, d = book["size"]
        near = Vector(book["near"])
        # thick enough for the real book (so it never pushes into its neighbours), and
        # standing in the compartment the point is in (within 15 cm of its height)
        fits = [o for o in pool if o["dims"][0] >= t - 0.002 and abs(o.matrix_world.translation.z - near.z) < 0.15]
        if not fits:
            raise SystemExit(f"featured.py: no generated book near {tuple(near)} can hold {book['slug']}")
        old = min(fits, key=lambda o: (o.matrix_world.translation - near).length)
        t_old, _, d_old = old["dims"]
        mesh = _book_mesh(f"book_featured_{book['slug']}", book["kind"], min(t, t_old), d, h)
        with open(os.path.join(art[book["slug"]], "art.json")) as fh:
            colours = json.load(fh)
        mesh.materials.append(_spine_material(book["slug"], art[book["slug"]],
                                              _hex_linear(colours["coverColour"])))
        mesh.materials.append(mats["pages"])
        # keep the spine where the old one was: move along the book's depth by the change in depth
        m = old.matrix_world.copy()
        m.translation += m.to_3x3() @ Vector((0.0, (d - d_old) / 2, 0.0))
        old.data = mesh
        old.matrix_world = m
        old.name = f"{prefix}_featured_{book['slug']}"
        old["dims"] = (min(t, t_old), h, d)
        old["item"] = book["slug"]
        old["item_of"] = hotspot
        old["item_art"] = art[book["slug"]]
        old["item_order"] = order
        old["item_json"] = json.dumps({k: book[k] for k in ("title", "author", "summary", "kind")}
                                      | {"spineColour": book["spine"]["bg"], "coverColour": colours["coverColour"],
                                         "coverAspect": colours["coverAspect"]})
        print(f"featured: {book['slug']} replaces a {t_old * 100:.1f} cm book at "
              f"{tuple(round(c, 2) for c in m.translation)}")
