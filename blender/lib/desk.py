"""The desk zone: an oak table and everything on and around it, and the framed prints.

Built with hero.HeroBuilder (bevelled parts, smooth shading), one object per
piece so each stays selectable. Materials are prefixed ``hero_``; wood and
paper use the shared grain/island attributes that materials.finish_scene()
writes. Clutter is seeded, so every build is identical.

Conventions match lib.furniture: ``loc`` is the base of the object, the front
faces -Y in local space, and ``rot_z`` turns it about Z.
"""

import math

import bpy
from mathutils import Matrix, Vector

from . import hero
from . import materials as lib
from .hero import HeroBuilder, smooth_path

A4 = (0.21, 0.297)


# --------------------------------------------------------------------------- materials

def _perforated(name):
    """Aluminium sheet with a staggered grid of round holes (in the local XZ plane)."""
    mat, g, bsdf = lib._new(name, (0.75, 0.75, 0.77))
    x, _, z = g.sep(g.obj_coords())
    pitch = 0.0042
    row = g.math("FLOOR", g.math("DIVIDE", z, pitch))
    xs = g.math("ADD", g.math("DIVIDE", x, pitch), g.math("MULTIPLY", g.math("MODULO", row, 2.0), 0.5))
    fx = g.math("SUBTRACT", g.math("FRACT", xs), 0.5)
    fz = g.math("SUBTRACT", g.math("FRACT", g.math("DIVIDE", z, pitch)), 0.5)
    hole = g.map(g.vmath("LENGTH", g.vec(fx, fz, 0.0)), 0.26, 0.31, 1.0, 0.0)
    lib._principled(g, bsdf, color=g.mix(hole, (0.80, 0.80, 0.82), (0.008, 0.008, 0.009)),
                    metal=g.map(hole, 0.0, 1.0, 1.0, 0.0), rough=0.33,
                    normal=g.bump(hole, 0.6, 0.001, invert=True))
    return mat


COVER_TILE = (0.22, 0.28)  # metres covered by one tile of the cover atlas


def _cover_atlas(name="hero_cover_atlas", cols=4, rows=3, tw=220, th=280):
    """Generated magazine and catalogue covers: a colour field, a photo (crops of
    the CC0 prints' sources), a masthead band and blocks of grey 'type'. No real text."""
    import numpy as np

    img = bpy.data.images.get(name)
    if img:
        return img
    rng = np.random.default_rng(9)
    photos = [hero.photo_pixels("print_autumn_meadow", "DSC_0415.jpg", 1200),
              hero.photo_pixels("print_misty_pines", "misty_pines.jpg", 1600)]
    palette = np.array([(0.85, 0.84, 0.8), (0.62, 0.08, 0.06), (0.03, 0.03, 0.03), (0.12, 0.2, 0.42),
                        (0.92, 0.92, 0.9), (0.8, 0.6, 0.12), (0.3, 0.36, 0.33), (0.9, 0.9, 0.88)], np.float32)
    atlas = np.zeros((rows * th, cols * tw, 3), np.float32)
    for r in range(rows):
        for c in range(cols):
            tile = np.empty((th, tw, 3), np.float32)
            tile[:] = palette[rng.integers(len(palette))]
            src = photos[rng.integers(2)]
            top = int(th * rng.uniform(0.15, 0.3))
            bottom = int(th * rng.uniform(0.75, 1.0))
            inset = int(tw * rng.choice((0.0, 0.08)))
            if src is not None:
                ph, pw = bottom - top, tw - 2 * inset
                cw = rng.uniform(0.15, 0.35)
                cx, cy = rng.uniform(0, 1 - cw), rng.uniform(0.35, 0.6)
                part = hero.crop(src, (cx, cy, cx + cw, cy + cw * src.shape[1] / src.shape[0] * ph / pw))
                tile[top:bottom, inset:tw - inset] = hero.resize(part, pw, ph)
            band = palette[rng.integers(len(palette))]
            tile[int(th * 0.03):int(th * 0.12), int(tw * 0.06):int(tw * rng.uniform(0.6, 0.94))] = band
            for k in range(rng.integers(3, 9)):
                y = int(th * rng.uniform(0.3, 0.92))
                x0 = int(tw * rng.uniform(0.05, 0.4))
                tile[y:y + 2, x0:x0 + int(tw * rng.uniform(0.15, 0.45))] = 0.95 if tile[y, x0].mean() < 0.5 else 0.1
            atlas[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = tile
    return hero.packed_image(name, atlas)


def _covers(name, cols=4, rows=3):
    """Magazine covers: the generated atlas projected from above, tiled so each
    cover (and each pile) lands on a different part of it."""
    mat, g, bsdf = lib._new(name, (0.5, 0.3, 0.3))
    _, rnd = g.attr("island_rand")
    x, y, _ = g.sep(g.obj_coords())
    u = g.math("ADD", g.math("DIVIDE", x, cols * COVER_TILE[0]), g.math("MULTIPLY", rnd, 3.0))
    v = g.math("ADD", g.math("DIVIDE", y, rows * COVER_TILE[1]), g.math("MULTIPLY", rnd, 5.0))
    tex = g.node("ShaderNodeTexImage")
    tex.image = _cover_atlas()
    tex.interpolation = "Cubic"
    g.set(tex.inputs["Vector"], g.vec(u, v, 0.0))
    lib._principled(g, bsdf, color=tex.outputs["Color"], rough=0.3, coat=0.25, coat_rough=0.1)
    return mat


def _frame_glass(name):
    """Picture glass: transparent with Fresnel reflections (shadows pass through)."""
    mat, g, bsdf = lib._new(name, (0.8, 0.85, 0.85))
    nt = g.nt
    out = nt.nodes["Material Output"]
    nt.nodes.remove(bsdf)
    clear = g.node("ShaderNodeBsdfTransparent")
    g.set(clear.inputs["Color"], (0.96, 0.975, 0.97))
    gloss = g.node("ShaderNodeBsdfGlossy")
    g.set(gloss.inputs["Roughness"], g.map(g.noise(g.position(), 3.0, 2.0), 0.3, 0.7, 0.1, 0.16))
    fres = g.node("ShaderNodeFresnel")
    g.set(fres.inputs["IOR"], 1.52)
    mix = g.node("ShaderNodeMixShader")
    g.set(mix.inputs["Fac"], g.math("MULTIPLY", fres.outputs["Fac"], 0.7))
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(gloss.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    mat.diffuse_color = (0.8, 0.85, 0.85, 0.2)
    return mat


def _image_material(name, image, rough=0.5):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, g, bsdf = lib._new(name, (0.3, 0.3, 0.3))
    tex = g.node("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Cubic"
    lib._principled(g, bsdf, color=tex.outputs["Color"], rough=rough)
    return mat


# Crops of the CC0 photos for the snapshots in small frames: (asset, file, width, crop box).
SNAPSHOTS = {
    "snapshot": ("print_autumn_meadow", "DSC_0415.jpg", 1200, (0.55, 0.45, 0.8, 0.95)),
    "snapshot_2": ("print_autumn_meadow", "DSC_0415.jpg", 1200, (0.05, 0.35, 0.35, 0.85)),
    "snapshot_3": ("print_misty_pines", "misty_pines.jpg", 1200, (0.2, 0.15, 0.45, 0.6)),
    "snapshot_4": ("print_misty_pines", "misty_pines.jpg", 1200, (0.6, 0.3, 0.85, 0.75)),
}


def _snapshot(name="hero_snapshot_image", key="snapshot"):
    """A faded colour snapshot (a crop of a CC0 photo) for a small frame."""
    import numpy as np

    img = bpy.data.images.get(name)
    if img:
        return img
    asset, filename, width, crop = SNAPSHOTS[key]
    src = hero.photo_pixels(asset, filename, width)
    if src is None:
        src = np.full((64, 48, 3), 0.5, np.float32)
    rgb = hero.resize(hero.crop(src, crop), 240, 330)
    rgb = 0.08 + 0.8 * rgb * np.array([1.0, 0.93, 0.8], np.float32)
    return hero.packed_image(name, rgb.astype(np.float32))


def _p(name, color, rough, metal=0.0, **extra):
    return hero._principled(name, color, rough, metal, **extra)


def materials(m):
    """The desk zone's materials (created once). m is the room's shared library."""
    h = hero.materials()
    return {
        **h,
        # a little darker than natural oak, as in the photo from his desk
        "oak": lib.wood("hero_desk_oak", (0.50, 0.24, 0.075), (0.22, 0.085, 0.024), 0.3, 70.0, coat=0.45),
        "paper": m["paper"],
        "cardboard": m["cardboard"],
        "plastic_white": m["plastic_white"],
        "perforated": lib._cached("hero_perforated_aluminium", _perforated),
        "vinyl": hero._with_bump(_p("hero_speaker_vinyl", (0.014, 0.014, 0.015), 0.42), 2500, 0.25),
        "baffle": _p("hero_speaker_baffle", (0.008, 0.008, 0.009), 0.3),
        "cone": hero._with_bump(_p("hero_driver_cone", (0.018, 0.018, 0.019), 0.75), 900, 0.2),
        "dome": _p("hero_silk_dome", (0.03, 0.03, 0.032), 0.55, **{"Sheen Weight": 0.6}),
        "grille": lib._cached("hero_grille_cloth", lambda n: lib.fabric(n, (0.012, 0.012, 0.014))),
        "keycap": _p("hero_keycap_white", (0.86, 0.86, 0.85), 0.32),
        "pad": hero._with_bump(_p("hero_mouse_pad", (0.03, 0.03, 0.033), 0.8), 3000, 0.3),
        "phone": _p("hero_phone_plastic", (0.02, 0.02, 0.022), 0.35),
        "phone_key": _p("hero_phone_key", (0.12, 0.12, 0.125), 0.45),
        "cord": _p("hero_cord", (0.015, 0.015, 0.016), 0.4),
        "cable_white": _p("hero_cable_white", (0.8, 0.8, 0.79), 0.35),
        "covers": lib._cached("hero_magazine_cover", _covers),
        "kraft": hero._with_bump(_p("hero_kraft_paper", (0.60, 0.43, 0.25), 0.8), 400, 0.2),
        "jewel_case": _p("hero_jewel_case", (0.008, 0.008, 0.009), 0.1, **{"Coat Weight": 0.6}),
        "notebook_black": _p("hero_notebook_black", (0.018, 0.018, 0.018), 0.6),
        "notebook_red": _p("hero_notebook_red", (0.32, 0.04, 0.03), 0.55),
        "elastic": _p("hero_elastic", (0.01, 0.01, 0.01), 0.7),
        "ceramic": _p("hero_ceramic", (0.82, 0.81, 0.77), 0.1, **{"Coat Weight": 0.5}),
        "coffee": _p("hero_coffee", (0.03, 0.012, 0.004), 0.05),
        "bottle_green": _p("hero_bottle_green", (0.10, 0.45, 0.12), 0.02, **{"Transmission Weight": 1.0}),
        "glass_clear": _p("hero_glass_clear", (0.9, 0.92, 0.9), 0.02, **{"Transmission Weight": 1.0}),
        "cap_white": _p("hero_cap_white", (0.85, 0.85, 0.83), 0.3),
        "pens": [_p(f"hero_pen_{i}", c, 0.35) for i, c in enumerate(
            [(0.02, 0.02, 0.02), (0.05, 0.1, 0.4), (0.6, 0.05, 0.03), (0.8, 0.8, 0.78), (0.8, 0.55, 0.05)])],
        "frame_black": hero._with_bump(_p("hero_frame_black", (0.012, 0.011, 0.01), 0.42), 300, 0.15,
                                       stretch=(1, 1, 20)),
        "mount": hero._with_bump(_p("hero_mount_board", (0.87, 0.86, 0.82), 0.9), 1200, 0.1),
        "glass": lib._cached("hero_frame_glass", _frame_glass),
        **{key: _image_material(f"hero_{key}", _snapshot(f"hero_{key}_image", key), rough=0.25)
           for key in SNAPSHOTS},
        # deep brown, like the chest of drawers in the photo from his desk
        "walnut": lib.wood("hero_walnut", (0.17, 0.085, 0.04), (0.06, 0.027, 0.013), 0.35, 60.0, coat=0.5),
        "frame_black": _p("hero_frame_black", (0.02, 0.02, 0.02), 0.45),
    }


# --------------------------------------------------------------------------- the desk

def desk(mt, col, name, loc, size, rot_z=0.0):
    """Solid oak table: a top of four glued boards with eased edges, square legs,
    aprons set back from the leg faces and pegged mortise-and-tenon joints,
    corner blocks underneath. loc is the floor centre; size is the top."""
    w, d, h = size
    top_t, leg, inset = 0.032, 0.066, 0.035
    apron_h, apron_t, reveal = 0.105, 0.022, 0.007
    oak = mt["oak"]
    b = HeroBuilder()
    boards = 4
    bw = w / boards
    for i in range(boards):
        x = -w / 2 + bw * (i + 0.5)
        inner = [s for s, edge in ((-1, i > 0), (1, i < boards - 1)) if edge]
        half = bw / 2 - 0.0002
        b.box((bw - 0.0004, d, top_t), (x, 0, h - top_t / 2), oak, bevel=0.004, segments=3,
              edge_filter=lambda c, inner=inner, half=half: not any(abs(c.x - s * half) < 1e-4 for s in inner))
    under = h - top_t
    lx, ly = w / 2 - inset - leg / 2, d / 2 - inset - leg / 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box((leg, leg, under), (sx * lx, sy * ly, under / 2), oak, bevel=0.0025, segments=2)
            # drawbore pegs through the leg into each apron's tenon
            for k in (-1, 1):
                z = under - apron_h / 2 + k * 0.026
                b.cyl(0.0042, 0.003, (sx * (lx + leg / 2), sy * (ly - leg / 2 + 0.017), z), oak,
                      rot=(0, math.pi / 2, 0), segments=12)
                b.cyl(0.0042, 0.003, (sx * (lx - leg / 2 + 0.017), sy * (ly + leg / 2), z), oak,
                      rot=(math.pi / 2, 0, 0), segments=12)
            # corner block bracing the aprons
            b.box((0.12, 0.028, 0.07), (sx * (lx - 0.07), sy * (ly - 0.07), under - 0.045), oak,
                  rot=(0, 0, sx * sy * -math.pi / 4), bevel=0.002, segments=1)
    za = under - apron_h / 2
    long_len = 2 * ly - leg + 0.04  # tenons run into the legs
    short_len = 2 * lx - leg + 0.04
    for s in (-1, 1):
        b.box((apron_t, long_len, apron_h), (s * (lx + leg / 2 - reveal - apron_t / 2), 0, za), oak,
              bevel=0.0015, segments=2)
        b.box((short_len, apron_t, apron_h), (0, s * (ly + leg / 2 - reveal - apron_t / 2), za), oak,
              bevel=0.0015, segments=2)
    # felt pads keep the legs off the floorboards
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box((leg - 0.01, leg - 0.01, 0.002), (sx * lx, sy * ly, 0.001), mt["rubber"])
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- tower

def tower(mt, col, name, loc, rot_z=0.0, size=(0.21, 0.47, 0.51)):
    """Aluminium workstation tower: side panels that rise into carry handles and
    drop into feet, perforated front and back grilles, a few front ports. No logo."""
    w, d, h = size
    al, t = mt["aluminium"], 0.006
    b = HeroBuilder()
    foot, top = 0.035, h - 0.05
    b.box((w - 2 * t, d - 0.02, top - foot), (0, 0, (top + foot) / 2), al, bevel=0.002, segments=2)
    for sx in (-1, 1):
        x = sx * (w / 2 - t / 2)
        b.box((t, d, top - foot), (x, 0, (top + foot) / 2), al, bevel=0.0025, segments=3)
        for sy in (-1, 1):
            y = sy * (d / 2 - 0.03)
            b.box((t, 0.06, h - top + 0.01), (x, y, (h + top) / 2 - 0.005), al, bevel=0.0025, segments=3)
            b.box((t, 0.06, foot + 0.01), (x, y, foot / 2 + 0.005), al, bevel=0.0025, segments=3)
    for sy in (-1, 1):
        # handle bars across the top, front and back
        b.box((w, 0.034, 0.014), (0, sy * (d / 2 - 0.017), h - 0.007), al, bevel=0.0055, segments=4)
        b.box((w - 2 * t - 0.002, 0.003, top - foot - 0.01), (0, sy * (d / 2 - 0.0015), (top + foot) / 2),
              mt["perforated"], bevel=0.001, segments=1)
    b.box((w - 2 * t, d - 0.12, 0.004), (0, 0, top + 0.002), al, bevel=0.0015, segments=2)
    # front: power button, optical slot, ports
    front = -d / 2 - 0.001
    b.cyl(0.0065, 0.004, (w / 2 - 0.035, front, top - 0.03), al, rot=(math.pi / 2, 0, 0), bevel=0.001)
    b.box((0.13, 0.003, 0.004), (-0.015, front, top - 0.03), mt["gloss_black"])
    for i, x in enumerate((-0.05, -0.03, 0.0, 0.025)):
        size_ = (0.012, 0.003, 0.005) if i < 2 else (0.008, 0.003, 0.008)
        b.box(size_, (x, front, foot + 0.04), mt["gloss_black"])
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- speaker

def _driver(b, mt, centre, radius):
    """A woofer: trim ring, rubber surround, paper cone and dust cap, facing -Y."""
    b.push(Matrix.Translation(centre) @ Matrix.Rotation(math.pi / 2, 4, "X"))
    r = radius
    b.lathe([(r + 0.006, -0.002), (r + 0.006, 0.002), (r + 0.003, 0.004), (r - 0.003, 0.004),
             (r - 0.004, -0.002)], (0, 0, 0), mt["gloss_black"], segments=48)
    b.lathe([(r - 0.003, 0.003), (r - 0.006, 0.0065), (r - 0.011, 0.0075), (r - 0.016, 0.0065),
             (r - 0.019, 0.003)], (0, 0, 0), mt["rubber"], segments=48)
    b.lathe([(r - 0.019, 0.003), (r * 0.6, -0.006), (r * 0.38, -0.014), (r * 0.36, -0.013),
             (r * 0.28, -0.008), (r * 0.15, -0.005), (0, -0.0045)], (0, 0, 0), mt["cone"], segments=48)
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        b.cyl(0.0022, 0.002, ((r + 0.003) * math.cos(a), (r + 0.003) * math.sin(a), 0.0045),
              mt["metal_dark"], segments=12)
    b.pop()


def _tweeter(b, mt, centre):
    b.push(Matrix.Translation(centre) @ Matrix.Rotation(math.pi / 2, 4, "X"))
    b.cyl(0.036, 0.004, (0, 0, 0.0), mt["gloss_black"], bevel=0.0012, segments=48)
    b.lathe([(0.031, 0.0022), (0.024, -0.0005), (0.017, -0.003), (0.0135, -0.0035)], (0, 0, 0),
            mt["baffle"], segments=48)
    b.lathe([(0.0135, -0.0035), (0.012, 0.0), (0.008, 0.003), (0.0, 0.0045)], (0, 0, 0), mt["dome"],
            segments=48)
    b.pop()


def speaker(mt, col, name, loc, rot_z=0.0, size=(0.19, 0.23, 0.30)):
    """Black bookshelf speaker: vinyl-wrapped cabinet, tweeter and woofer on the
    baffle, its grille cloth frame leaning against the side."""
    w, d, h = size
    b = HeroBuilder()
    b.box((w, d, h), (0, 0, h / 2), mt["vinyl"], bevel=0.006, segments=3)
    front = -d / 2
    b.box((w - 0.01, 0.003, h - 0.01), (0, front - 0.0012, h / 2), mt["baffle"], bevel=0.0012, segments=2)
    _driver(b, mt, (0, front - 0.003, 0.115), 0.066)
    _tweeter(b, mt, (0, front - 0.003, 0.238))
    b.cyl(0.021, 0.004, (0, d / 2 + 0.001, 0.08), mt["gloss_black"], rot=(math.pi / 2, 0, 0), bevel=0.002)
    for z in (0.17, 0.2):
        b.cyl(0.006, 0.014, (0.03, d / 2 + 0.007, z), mt["chrome"], rot=(math.pi / 2, 0, 0))
    # grille: cloth over a thin frame, propped against the right-hand side
    lean = 0.09
    b.push(Matrix.Translation((w / 2 + 0.008 + (h - 0.012) * math.sin(lean) / 2, -0.01, 0))
           @ Matrix.Rotation(-lean, 4, "Y") @ Matrix.Rotation(-math.pi / 2, 4, "Z"))
    b.box((w - 0.01, 0.012, h - 0.012), (0, 0, (h - 0.012) / 2 + 0.002), mt["grille"], bevel=0.003, segments=2)
    b.pop()
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.cyl(0.008, 0.003, (sx * (w / 2 - 0.02), sy * (d / 2 - 0.02), -0.0015), mt["rubber"], segments=16)
    obj = b.build(name, col, loc, rot_z)
    obj.location.z += 0.003
    return obj


# --------------------------------------------------------------------------- desk lamp

def desk_lamp(mt, col, name, loc, rot_z=0.0):
    """Balanced-arm task lamp in black: a forked stand, twin thin arms with a
    counterweight, and a small round head. loc is the base."""
    b = HeroBuilder()
    blk, gloss = mt["metal_black"], mt["gloss_black"]
    b.cyl(0.038, 0.012, (0, 0, 0.006), gloss, bevel=0.003, segments=40)
    pivot = Vector((0, 0, 0.15))
    for sx in (-1, 1):
        path = smooth_path([(sx * 0.026, 0, 0.01), (sx * 0.024, 0, 0.05), (sx * 0.01, 0, 0.12), pivot], 6)
        b.tube(path, 0.0035, blk, sides=10)
    b.cyl(0.0075, 0.026, pivot, blk, rot=(math.pi / 2, 0, 0), segments=20, bevel=0.001)
    # parallel arms through the pivot, joined by short links at each end
    back, front, slope, gap = -0.17, 0.21, 0.12, 0.024
    for dz, r in ((0.0, 0.003), (gap, 0.0022)):
        x0 = back if dz == 0 else back + 0.02
        b.rod((x0, 0, pivot.z + slope * x0 + dz), (front, 0, pivot.z + slope * front + dz), r, blk, segments=10)
    for x in (back + 0.02, front):
        z = pivot.z + slope * x
        b.rod((x, 0, z - 0.004), (x, 0, z + gap + 0.004), 0.0035, blk, segments=10)
    zb = pivot.z + slope * back
    b.cyl(0.014, 0.045, (back - 0.005, 0, zb - 0.02), blk, bevel=0.003, segments=24)
    head = Vector((front, 0, pivot.z + slope * front - 0.035))
    b.rod((front, 0, head.z + 0.035), (front, 0, head.z + 0.02), 0.004, blk, segments=10)
    b.sphere(0.034, head, blk, scale=(1, 1, 0.92))
    b.cyl(0.02, 0.002, head - Vector((0, 0, 0.0315)), mt["marking"], segments=32)
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- keyboard, mouse, phone

def keyboard(mt, col, name, loc, rot_z=0.0, unit=0.0183):
    """Thin aluminium keyboard with white keys: main block, navigation keys and a
    number pad. No legends or logos. Front edge faces -Y."""
    w, d = 0.43, 0.118
    b = HeroBuilder()
    b.push(Matrix.Translation((0, 0, 0.0035)) @ Matrix.Rotation(0.045, 4, "X"))
    b.box((w, d, 0.0075), (0, 0, 0.0005), mt["aluminium"], bevel=0.0028, segments=3)
    z = 0.0043 + 0.0009
    cap, gap = unit - 0.0026, 0.0026
    x0 = -w / 2 + 0.008

    def key(x, y, units=1.0, height=1.0):
        b.box((units * unit - gap, height * unit - gap, 0.0018), (x + units * unit / 2, y, z),
              mt["keycap"], bevel=0.0007, segments=1)

    rows = [[1.0] * 13 + [2.0], [1.5] + [1.0] * 12 + [1.5], [1.75] + [1.0] * 11 + [2.25],
            [2.25] + [1.0] * 10 + [2.75], [1.0, 1.0, 1.0, 1.25, 5.5, 1.25, 1.0, 1.0, 1.0, 1.0]]
    yf = d / 2 - 0.011
    for k in range(15):
        key(x0 + k * unit, yf, 1.0, 0.62)
    for k in range(3):
        key(x0 + (15.4 + k) * unit, yf, 1.0, 0.62)
    for k in range(4):
        key(x0 + (18.8 + k) * unit, yf, 1.0, 0.62)
    for r, widths in enumerate(rows):
        y = yf - 0.0135 - r * unit
        x = x0
        for units in widths:
            key(x, y, units)
            x += units * unit
        if r < 2:
            for k in range(3):
                key(x0 + (15.4 + k) * unit, y)
        if r == 3:
            key(x0 + 16.4 * unit, y)
        if r == 4:
            for k in range(3):
                key(x0 + (15.4 + k) * unit, y)
        for k in range(4):
            if r == 4 and k == 1:
                continue
            key(x0 + (18.8 + k) * unit, y, 2.0 if r == 4 and k == 0 else 1.0)
    b.pop()
    for sx in (-1, 1):
        b.box((0.02, 0.01, 0.006), (sx * (w / 2 - 0.03), d / 2 - 0.01, 0.003), mt["rubber"])
    return b.build(name, col, loc, rot_z)


def mouse(mt, col, name, loc, rot_z=0.0):
    """White one-button mouse on a dark cloth pad."""
    b = HeroBuilder()
    b.box((0.23, 0.19, 0.003), (0, 0.01, 0.0015), mt["pad"], bevel=0.0012, segments=2)
    b.sphere(0.03, (0, 0, 0.003), mt["plastic_white"], scale=(1.0, 1.85, 0.62), u=32, v=16)
    b.sphere(0.0035, (0, -0.02, 0.021), mt["metal_dark"], u=12, v=8)
    return b.build(name, col, loc, rot_z)


def _coil(b, path, radius, wire, mat, turns_per_m=260.0, sides=6):
    """A coiled cord wound around a centreline."""
    pts = [Vector(p) for p in smooth_path(path, 10)]
    dense = [pts[0]]
    for p in pts[1:]:
        seg = p - dense[-1]
        n = max(1, int(seg.length / 0.0006))
        dense += [dense[-1] + seg * (k / n) for k in range(1, n + 1)]
    out, s = [], 0.0
    normal = (dense[1] - dense[0]).orthogonal().normalized()
    for i, p in enumerate(dense):
        t = (dense[min(i + 1, len(dense) - 1)] - dense[max(i - 1, 0)]).normalized()
        normal = (normal - t * normal.dot(t)).normalized()
        if i:
            s += (p - dense[i - 1]).length
        a = 2 * math.pi * turns_per_m * s
        out.append(p + radius * (math.cos(a) * normal + math.sin(a) * t.cross(normal)))
    b.tube(out, wire, mat, sides=sides)


def desk_phone(mt, col, name, loc, rot_z=0.0):
    """Corded desk phone: sloped body, keypad, small display, handset in its cradle
    and a coiled cord."""
    b = HeroBuilder()
    body = mt["phone"]
    b.box((0.17, 0.21, 0.032), (0, 0, 0.016), body, bevel=0.007, segments=3)
    tilt = Matrix.Translation((0, 0.004, 0.034)) @ Matrix.Rotation(0.17, 4, "X")
    b.push(tilt)
    b.box((0.165, 0.2, 0.02), (0, 0, 0.0), body, bevel=0.007, segments=3)
    for r in range(4):
        for c in range(3):
            b.box((0.016, 0.011, 0.004), (0.022 + c * 0.021, -0.07 + r * 0.017, 0.011), mt["phone_key"],
                  bevel=0.0015, segments=1)
    b.box((0.06, 0.026, 0.001), (0.043, 0.05, 0.0102), mt["screen"])
    for k in range(4):
        b.box((0.011, 0.007, 0.003), (0.021 + k * 0.014, 0.075, 0.0105), mt["phone_key"], bevel=0.001, segments=1)
    # handset lying in the cradle on the left
    b.push(Matrix.Translation((-0.043, 0, 0.026)))
    b.box((0.042, 0.2, 0.02), (0, 0, 0), body, bevel=0.008, segments=3)
    for sy in (-1, 1):
        b.box((0.052, 0.06, 0.03), (0, sy * 0.075, -0.004), body, bevel=0.012, segments=3)
    b.pop()
    b.pop()
    _coil(b, [(-0.075, -0.08, 0.03), (-0.1, -0.1, 0.012), (-0.11, -0.04, 0.005), (-0.1, 0.03, 0.006),
              (-0.086, 0.05, 0.012)], 0.005, 0.0013, mt["cord"])
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- desk clutter

def _curl(rng, amount):
    """lift(u, v) for a sheet with one or two lifted corners/edges."""
    cu, cv = rng.choice((0.0, 1.0)), rng.choice((0.0, 1.0))
    sag = rng.uniform(0.0, 0.002)
    edge = rng.random() < 0.4

    def lift(u, v):
        du = abs(u - cu)
        dv = abs(v - cv)
        corner = max(0.0, 1.0 - (du if edge else math.hypot(du, dv)) / 0.6) ** 2.2
        return amount * corner + sag * math.sin(math.pi * u) * math.sin(math.pi * v)
    return lift


def paper_pile(b, mt, rng, centre, height, size=A4, loose=3, base=0.0):
    """Stacked paper: a few sub-stacks slightly askew, curled sheets on top."""
    x, y = centre
    z = base
    while z < base + height - 0.004:
        t = min(rng.uniform(0.006, 0.025), base + height - z)
        sz = (size[0] + rng.uniform(-0.01, 0.015), size[1] + rng.uniform(-0.01, 0.015), t)
        b.box(sz, (x + rng.uniform(-0.012, 0.012), y + rng.uniform(-0.012, 0.012), z + t / 2), mt["paper"],
              rot=(0, 0, rng.uniform(-0.07, 0.07)), bevel=0.0007, segments=1)
        z += t
    for _ in range(loose):
        z += 0.0006
        b.sheet(size, (x + rng.uniform(-0.03, 0.03), y + rng.uniform(-0.03, 0.03), z),
                rng.choice((mt["paper"], mt["paper"], mt["kraft"])),
                rot=(0, 0, rng.uniform(-0.25, 0.25)), lift=_curl(rng, rng.uniform(0.005, 0.03)))
    return z


def magazine(b, mt, rng, centre, z, rot, size=(0.215, 0.28), t=0.006):
    """Page block between two printed covers."""
    x, y = centre
    b.push(Matrix.Translation((x, y, z)) @ Matrix.Rotation(rot, 4, "Z"))
    w, d = size
    b.box((w - 0.002, d - 0.003, t - 0.001), (0.0005, 0, t / 2), mt["paper"])
    for zz in (0.0003, t - 0.0003):
        b.box((w, d, 0.0006), (0, 0, zz), mt["covers"], bevel=0.0002, segments=1)
    b.box((0.0008, d, t), (-w / 2, 0, t / 2), mt["covers"])
    b.pop()
    return z + t


def jewel_cases(b, mt, rng, centre, z, n):
    x, y = centre
    for _ in range(n):
        b.box((0.142, 0.125, 0.0104), (x + rng.uniform(-0.006, 0.006), y + rng.uniform(-0.006, 0.006), z + 0.0052),
              mt["jewel_case"], rot=(0, 0, rng.uniform(-0.1, 0.1)), bevel=0.0008, segments=1)
        z += 0.0104
    return z


def envelope(b, mt, rng, centre, z, rot, size=(0.229, 0.162)):
    mat = rng.choice((mt["paper"], mt["kraft"]))
    b.sheet(size, (centre[0], centre[1], z + 0.0008), mat, rot=(0, 0, rot), lift=_curl(rng, 0.006), nx=6, ny=4)
    b.sheet((size[0] - 0.004, size[1] * 0.45), (centre[0], centre[1], z + 0.0016), mat,
            rot=(0, 0, rot), nx=2, ny=2)
    return z + 0.002


def notebook(b, mt, rng, centre, z, rot, cover, size=(0.13, 0.21), t=0.016):
    x, y = centre
    b.push(Matrix.Translation((x, y, z)) @ Matrix.Rotation(rot, 4, "Z"))
    w, d = size
    b.box((w - 0.004, d - 0.005, t - 0.003), (0.001, 0, t / 2), mt["paper"])
    for zz in (0.00075, t - 0.00075):
        b.box((w, d, 0.0015), (0, 0, zz), cover, bevel=0.0015, segments=2)
    b.box((0.0025, d, t), (-w / 2, 0, t / 2), cover, bevel=0.001, segments=1)
    b.box((0.006, d + 0.002, t + 0.001), (w / 2 - 0.02, 0, t / 2), mt["elastic"])
    b.pop()
    return z + t


def mug(b, mt, centre, rot=0.0):
    x, y, z = centre
    b.push(Matrix.Translation((x, y, z)) @ Matrix.Rotation(rot, 4, "Z"))
    b.lathe([(0, 0.0), (0.036, 0.0), (0.039, 0.004), (0.04, 0.05), (0.04, 0.094), (0.0385, 0.096),
             (0.0365, 0.094), (0.0362, 0.012), (0.03, 0.008), (0, 0.008)], (0, 0, 0), mt["ceramic"], segments=40)
    b.cyl(0.0362, 0.001, (0, 0, 0.062), mt["coffee"], segments=40)
    b.push(Matrix.Translation((0.039, 0, 0.05)) @ Matrix.Rotation(math.pi / 2, 4, "X")
           @ Matrix.Rotation(-math.pi / 2, 4, "Z"))
    b.torus(0.026, 0.0058, (0, 0, 0), mt["ceramic"], u=20, v=10, arc=math.pi)
    b.pop()
    b.pop()


def pen_pot(b, mt, rng, centre):
    x, y, z = centre
    r, hh = 0.037, 0.1
    b.lathe([(0, 0), (r, 0), (r, hh), (r - 0.0015, hh), (r - 0.0015, 0.004), (0, 0.004)], (x, y, z),
            mt["metal_black"], segments=32)
    for i in range(7):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.0, r - 0.008)
        foot = Vector((x + rr * math.cos(a), y + rr * math.sin(a), z + 0.006))
        lean = Vector((math.cos(a), math.sin(a), 0)) * rng.uniform(0.15, 0.35) + Vector((0, 0, 1))
        top = foot + lean.normalized() * rng.uniform(0.13, 0.16)
        mat = rng.choice(mt["pens"])
        b.rod(foot, top, 0.0042, mat, segments=6 if i % 3 == 0 else 12)
        b.rod(top, top + lean.normalized() * 0.012, 0.0042, mt["pens"][0], segments=12, radius2=0.001)


def bottle(b, mt, centre, height=0.30, radius=0.036, mat=None, cap=None):
    """Glass bottle with a real wall thickness (so it refracts like glass)."""
    x, y, z = centre
    s, r, wall = height / 0.30, radius, 0.0025
    outer = [(r - 0.003, 0.0), (r, 0.004), (r, 0.19 * s), (r * 0.8, 0.225 * s), (r * 0.4, 0.255 * s),
             (0.0125, 0.275 * s), (0.0125, height - 0.008), (0.0145, height - 0.006), (0.0145, height)]
    inner = [(0.0105, height), (0.0105, 0.275 * s), (r * 0.4 - wall, 0.253 * s), (r * 0.8 - wall, 0.223 * s),
             (r - wall, 0.19 * s), (r - wall, 0.008), (0, 0.012)]
    b.lathe([(0, 0.006)] + outer + inner, (x, y, z), mat or mt["bottle_green"], segments=36)
    if cap:
        b.cyl(0.016, 0.02, (x, y, z + height + 0.008), cap, bevel=0.002, segments=24)


def pile(mt, col, name, loc, recipe, rng, rot_z=0.0):
    """A desk pile built bottom-up from a recipe of (kind, amount) layers:
    papers (height), mags (count), catalogues (count), cds (count), envelopes
    (count), notebook (0 black / 1 red)."""
    b = HeroBuilder()
    z = 0.0

    def jitter(r=0.02):
        return (rng.uniform(-r, r), rng.uniform(-r, r))

    for kind, amount in recipe:
        if kind == "papers":
            z = paper_pile(b, mt, rng, jitter(0.01), amount, loose=rng.randint(1, 3), base=z)
        elif kind in ("mags", "catalogues"):
            t = 0.004 if kind == "mags" else 0.011
            size = (0.215, 0.28) if kind == "mags" else (0.23, 0.30)
            for _ in range(amount):
                z = magazine(b, mt, rng, jitter(0.03), z, rng.uniform(-0.3, 0.3), size,
                             t * rng.uniform(0.7, 1.4)) + 0.0002
        elif kind == "cds":
            z = jewel_cases(b, mt, rng, jitter(0.01), z, amount)
        elif kind == "envelopes":
            for _ in range(amount):
                z = envelope(b, mt, rng, jitter(0.04), z, rng.uniform(-0.5, 0.5),
                             rng.choice(((0.229, 0.162), (0.22, 0.11), (0.324, 0.229))))
        elif kind == "notebook":
            z = notebook(b, mt, rng, jitter(0.02), z, rng.uniform(-0.2, 0.2),
                         (mt["notebook_black"], mt["notebook_red"])[amount])
    return b.build(name, col, loc, rot_z)


def photo_frame(mt, col, name, loc, rot_z, size=(0.13, 0.18), wood="oak", photo="snapshot", lean=0.22):
    """Small standing frame (oak by default), leaning back on a strut, with a colour snapshot."""
    w, h = size
    b = HeroBuilder()
    b.push(Matrix.Translation((0, 0, 0.0)) @ Matrix.Rotation(-lean, 4, "X") @ Matrix.Translation((0, 0, h / 2)))
    b.ring((w, h), 0.016, -0.006, 0.006, mt[wood], bevel=0.0015)
    verts = b.sheet((w - 0.03, h - 0.03), (0, -0.001, 0), mt[photo], rot=(math.pi / 2, 0, 0), nx=1, ny=1)
    b.planar_uvs(verts, b.matrix.inverted(), (-(w - 0.03) / 2, -(h - 0.03) / 2), (w - 0.03, h - 0.03))
    b.box((w - 0.02, 0.003, h - 0.02), (0, 0.0045, 0), mt["cardboard"])
    b.pop()
    b.rod((0, 0.03, 0.12), (0, 0.075, 0.002), 0.004, mt["cardboard"], segments=6)
    return b.build(name, col, loc, rot_z)


def chest_of_drawers(mt, col, name, loc, rot_z=0.0, size=(1.42, 0.46, 0.78)):
    """Mid-century walnut chest: a low carcass of six drawers (two across, three high) with
    recessed finger pulls, on four tapered, slightly splayed legs. loc is the floor centre;
    the drawers face -Y."""
    w, d, h = size
    legs, top_t, gap = 0.2, 0.022, 0.006
    walnut = mt["walnut"]
    b = HeroBuilder()
    body = h - legs - top_t
    b.box((w, d, body), (0, 0, legs + body / 2), walnut, bevel=0.003, segments=2)
    b.box((w + 0.012, d + 0.012, top_t), (0, 0, h - top_t / 2), walnut, bevel=0.006, segments=3)
    # drawer fronts, a hair proud of the carcass, each with a dark finger slot under its top edge
    fw, fh = (w - 0.04 - gap) / 2, (body - 0.04 - 2 * gap) / 3
    front = -d / 2 - 0.009
    for i in range(2):
        for j in range(3):
            x = -w / 2 + 0.02 + fw / 2 + i * (fw + gap)
            z = legs + 0.02 + fh / 2 + j * (fh + gap)
            b.box((fw, 0.018, fh), (x, front, z), walnut, bevel=0.003, segments=2)
            b.box((fw * 0.4, 0.004, 0.014), (x, front - 0.0085, z + fh / 2 - 0.03), mt["metal_dark"], bevel=0.002)
    # tapered legs, splayed a little outwards
    for sx in (-1, 1):
        for sy in (-1, 1):
            top = (sx * (w / 2 - 0.07), sy * (d / 2 - 0.06), legs + 0.01)
            foot = (sx * (w / 2 - 0.04), sy * (d / 2 - 0.035), 0.0)
            b.rod(top, foot, 0.019, walnut, segments=16, radius2=0.011)
    return b.build(name, col, loc, rot_z)


def frame_stack(mt, col, name, loc, rot_z, sizes):
    """Frames lying flat in a loose pile, face up: (width, depth) each, bottom first."""
    b = HeroBuilder()
    z = 0.0
    woods = ("frame_black", "oak", "walnut")
    for i, (w, d) in enumerate(sizes):
        t = 0.018
        b.push(Matrix.Translation((0.01 * (i % 2 * 2 - 1), 0.008 * i, z + t / 2)) @ Matrix.Rotation(0.12 * (i - 1), 4, "Z"))
        b.box((w, d, t), (0, 0, 0), mt[woods[i % 3]], bevel=0.002, segments=1)
        b.box((w - 0.03, d - 0.03, 0.002), (0, 0, t / 2), mt[("snapshot_2", "snapshot_3", "snapshot_4")[i % 3]])
        b.pop()
        z += t + 0.001
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- framed prints

def bw_print(name, asset_id, filename, src_width, left, top, height, aspect, gamma=1.0, out_h=900, as_is=False):
    """A black-and-white print cut from a CC0 photo: crop, greyscale, tone curve,
    a gentle darkroom burn at the edges and a warm-neutral paper tone.
    as_is: a real photographer's print (e.g. the Ansel Adams): only cropped and on paper, its tones untouched."""
    import numpy as np

    img = bpy.data.images.get(name)
    if img:
        return img
    src = hero.photo_pixels(asset_id, filename, src_width)
    if src is None:
        rng = np.random.default_rng(3)
        g = np.clip(rng.normal(0.3, 0.15, (out_h // 8, int(out_h * aspect) // 8)), 0, 1)
        g = np.repeat(np.repeat(g, 8, 0), 8, 1)[..., None]
    else:
        sh, sw = src.shape[:2]
        width = height * sh * aspect / sw
        g = hero.crop(src, (left, top, left + width, top + height))
        g = hero.resize(g, int(out_h * aspect), out_h)
        g = (g @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
        if as_is:
            return hero.packed_image(name, (0.025 + 0.93 * g * np.array([1.0, 0.99, 0.965], np.float32)).astype(np.float32))
        lo, hi = np.percentile(g, 2.0), np.percentile(g, 99.8)
        g = np.clip((g - lo) / (hi - lo), 0, 1) ** gamma
        g = g * g * (3 - 2 * g) * 0.6 + g * 0.4  # S-curve: deep blacks, open highlights
    h, w = g.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r2 = ((xx / w - 0.5) / 0.5) ** 2 + ((yy / h - 0.5) / 0.5) ** 2
    g = g * (1 - 0.12 * np.clip(r2 - 0.3, 0, None))[..., None]
    rgb = 0.025 + 0.93 * g * np.array([1.0, 0.99, 0.965], np.float32)
    return hero.packed_image(name, rgb.astype(np.float32))


def framed_print(mt, col, name, loc, size, art, window, rot_z=0.0, face=0.02, depth=0.032):
    """Black wood frame (mitred moulding with a stepped sight edge), glass, a
    bevel-cut white mount and the print floated on white paper behind it.
    loc is the centre of the back face; the art faces -Y."""
    w, h = size
    ww, wh = window
    b = HeroBuilder()
    b.ring((w, h), face, -depth, 0.0, mt["frame_black"], bevel=0.0018)
    iw, ih = w - 2 * face, h - 2 * face
    b.ring((iw + 0.008, ih + 0.008), 0.006, -depth + 0.004, -depth + 0.0085, mt["frame_black"], bevel=0.0008)
    b.box((iw + 0.006, 0.002, ih + 0.006), (0, -depth + 0.0095, 0), mt["glass"])
    mount_y = -depth + 0.0108
    b.ring((iw + 0.006, ih + 0.006), ((iw - ww) / 2, (ih - wh) / 2), mount_y, mount_y + 0.0025, mt["mount"],
           inner_slope=0.0022)
    pw, ph = ww - 0.01, wh - 0.01
    verts = b.sheet((pw, ph), (0, mount_y + 0.0028, 0), art, rot=(math.pi / 2, 0, 0), nx=1, ny=1)
    b.planar_uvs(verts, Matrix.Identity(4), (-pw / 2, -ph / 2), (pw, ph))
    b.sheet((ww + 0.03, wh + 0.03), (0, mount_y + 0.0034, 0), mt["mount"], rot=(math.pi / 2, 0, 0), nx=1, ny=1)
    b.box((iw + 0.004, 0.003, ih + 0.004), (0, -0.0035, 0), mt["cardboard"])
    obj = b.build(name, col, loc, rot_z)
    obj["no_bevel"] = True
    return obj
