"""Outdoors, sun and sky: everything outside the room's walls.

Shared by every room. Sun and sky angles: azimuth 0 = north, clockwise (east = 90).
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import assets
from .geo import Builder, collection


def _blob(b, centre, radius, mat, squash=1.0, seed=0, lumpiness=0.35):
    """A lumpy, roughly spherical leaf mass (icosphere displaced by smooth noise)."""
    from mathutils import Matrix, noise

    m = Matrix.Translation(centre) @ Matrix.Diagonal((radius, radius, radius * squash, 1.0))
    result = bmesh.ops.create_icosphere(b.bm, subdivisions=3, radius=1.0, matrix=m)
    off = Vector((seed * 3.7, seed * 1.3, seed * 5.1))
    c = Vector(centre)
    for v in result["verts"]:
        d = v.co - c
        n = noise.noise(d / radius * 1.4 + off) + 0.5 * noise.noise(d / radius * 3.5 + off)
        v.co = c + d * (1.0 + lumpiness * n)
    b._assign(result["verts"], mat)


def _tree(b, trunk, x, y, height, spread, crown_mat, mats, rng):
    trunk.cyl(0.12 + height * 0.012, height * 0.55, (x, y, height * 0.275), mats["bark"], segments=10,
              radius2=0.08 + height * 0.006)
    for i in range(rng.randint(5, 8)):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.15, 0.55) * spread
        z = height * rng.uniform(0.55, 0.85)
        _blob(b, (x + math.cos(a) * r, y + math.sin(a) * r, z), spread * rng.uniform(0.45, 0.7), crown_mat,
              squash=rng.uniform(0.75, 1.0), seed=rng.randint(0, 999))


def _house(b, x, y, w, d, eaves, ridge, wall_mat, mats, rot_y=False):
    """Simple gabled house; the ridge runs along X (or Y when rot_y)."""
    sx, sy = (d, w) if rot_y else (w, d)
    b.box((sx, sy, eaves), (x, y, eaves / 2), wall_mat)
    bm = b.bm
    over = 0.3
    if rot_y:
        base = [(x - sx / 2 - over, y - sy / 2 - over), (x + sx / 2 + over, y - sy / 2 - over),
                (x + sx / 2 + over, y + sy / 2 + over), (x - sx / 2 - over, y + sy / 2 + over)]
        ridge_pts = [(x, y - sy / 2 - over), (x, y + sy / 2 + over)]
    else:
        base = [(x - sx / 2 - over, y - sy / 2 - over), (x + sx / 2 + over, y - sy / 2 - over),
                (x + sx / 2 + over, y + sy / 2 + over), (x - sx / 2 - over, y + sy / 2 + over)]
        ridge_pts = [(x - sx / 2 - over, y), (x + sx / 2 + over, y)]
    vb = [bm.verts.new((px, py, eaves - 0.2)) for px, py in base]
    vr = [bm.verts.new((px, py, ridge)) for px, py in ridge_pts]
    if rot_y:
        faces = [(vb[0], vb[1], vr[0]), (vb[1], vb[2], vr[1], vr[0]), (vb[2], vb[3], vr[1]),
                 (vb[3], vb[0], vr[0], vr[1]), (vb[3], vb[2], vb[1], vb[0])]
    else:
        faces = [(vb[0], vb[1], vr[1], vr[0]), (vb[1], vb[2], vr[1]), (vb[2], vb[3], vr[0], vr[1]),
                 (vb[3], vb[0], vr[0]), (vb[3], vb[2], vb[1], vb[0])]
    for f in faces:
        bm.faces.new(f)
    b._assign(vb + vr, mats["roof_slate"])
    # dark windows on every face, two storeys
    for level in (eaves * 0.28, eaves * 0.72):
        for t in (-0.3, 0.0, 0.3):
            if rot_y:
                for side in (-1, 1):
                    b.box((0.08, 1.0, 1.2), (x + side * sx / 2, y + t * sy, level), mats["steel_black"])
            else:
                for side in (-1, 1):
                    b.box((1.0, 0.08, 1.2), (x + t * sx, y + side * sy / 2, level), mats["steel_black"])


def build_outdoors(mats, size=200.0, seed=11):
    """A simple procedural garden: lawn, clipped hedges, a few trees and shrubs,
    and the roofs of neighbouring houses beyond the hedge. Everything the
    north and east windows can see is dressed; the rest is kept plain."""
    import random

    rng = random.Random(seed)
    col = collection("Outdoors")
    b = Builder()
    b.box((size, size, 0.1), (0, 0, -0.17), mats["garden"])
    b.build("ground", col)

    # hedges: chains of overlapping leaf masses around the garden
    hedges = Builder()
    for (x0, y0, x1, y1, h) in [(-14, 11, 14, 11, 2.3), (11, -12, 11, 11, 2.0),
                                (-11, -12, -11, 11, 2.0), (-14, -11, 14, -11, 1.8)]:
        n = int(math.hypot(x1 - x0, y1 - y0) / 0.9)
        for i in range(n + 1):
            t = i / n
            hh = h * rng.uniform(0.9, 1.08)
            _blob(hedges, (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, hh * 0.5), 0.85, mats["foliage_dark"],
                  squash=hh / 1.7, seed=rng.randint(0, 999), lumpiness=0.2)
    hedges.build("hedges", col)

    # trees and shrubs (north and east gardens are what the windows see)
    trunks = Builder()
    crowns = Builder()
    tree_specs = [
        (-2.5, 7.5, 7.0, 2.4, "foliage"), (5.0, 7.0, 8.5, 2.8, "foliage_light"), (-8.0, 8.5, 9.0, 3.0, "foliage"),
        (1.5, 13.5, 11.0, 3.4, "foliage_dark"), (8.5, 2.0, 7.5, 2.6, "foliage"), (7.0, -4.5, 9.5, 3.2, "foliage_light"),
        (13.5, 6.5, 10.0, 3.5, "foliage_dark"), (-5.5, -8, 7.0, 2.2, "foliage"), (4.5, -8.5, 8.0, 2.6, "foliage"),
        (-12.5, 14.0, 12.0, 3.8, "foliage_dark"), (15.5, -3.0, 11.0, 3.6, "foliage"),
    ]
    for x, y, h, spread, mat in tree_specs:
        _tree(crowns, trunks, x, y, h, spread, mats[mat], mats, rng)
    for x, y, r in [(-1.0, 4.2, 0.7), (1.8, 4.6, 0.9), (-4.5, 4.0, 0.8), (5.3, 3.8, 0.75), (5.2, 0.4, 0.8),
                    (6.2, -2.0, 0.7), (3.0, 5.6, 0.6)]:
        for k in range(3):
            _blob(crowns, (x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4), r * 0.6), r * rng.uniform(0.7, 1.0),
                  mats[rng.choice(["foliage", "foliage_light"])], squash=0.8, seed=rng.randint(0, 999))
    trunks.build("tree_trunks", col)
    crowns.build("planting", col)

    # neighbouring houses beyond the hedges
    houses = Builder()
    for x, y, w, d, eaves, ridge, mat, rot in [
        (-9.0, 24.0, 9.0, 7.0, 5.8, 9.0, "house_render", False),
        (3.5, 27.0, 10.0, 8.0, 6.2, 9.8, "house_brick", False),
        (15.0, 23.0, 8.0, 7.0, 5.6, 8.6, "house_render", False),
        (25.0, 2.0, 9.0, 7.5, 5.8, 9.2, "house_brick", True),
        (27.0, 14.0, 8.0, 7.0, 6.0, 9.0, "house_render", True),
    ]:
        _house(houses, x, y, w, d, eaves, ridge, mats[mat], mats, rot)
    houses.build("houses", col)


def build_sun(azimuth_deg, elevation_deg, strength=4.0, colour=(1.0, 0.82, 0.68), angle_deg=0.6):
    """Sun shining FROM the given azimuth (0 = north, 90 = east)."""
    col = collection("Lighting")
    light = bpy.data.lights.new("sun", "SUN")
    light.energy = strength
    light.color = colour
    light.angle = math.radians(angle_deg)
    obj = bpy.data.objects.new("sun", light)
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    towards_sun = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    obj.rotation_euler = (-towards_sun).to_track_quat("-Z", "Y").to_euler()
    col.objects.link(obj)
    return obj


# Irradiance of the Multiple Scattering sky's sun disc at 35 deg elevation relative
# to world strength 1 (measured in Blender 5.2). build_sun(strength=SKY_SUN_RATIO * k)
# matches a sky of strength k.
SKY_SUN_RATIO = 155.0


def build_world(strength=0.1, sun_azimuth=200.0, sun_elevation=35.0, air=1.0, aerosol=1.6, colour=None):
    """Physical sky (Blender 5.x Multiple Scattering) lit for the given sun position.

    The sky's own sun disc is off; build_sun() adds a sun lamp at the same angle
    (cleaner shadows, less noise). Azimuth as build_sun: 0 = north, clockwise.
    `colour` keeps the old flat-colour sky as a fallback.
    """
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    nt = world.node_tree
    bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.get("World Output") or nt.nodes.new("ShaderNodeOutputWorld")
    bg.inputs["Strength"].default_value = strength
    if colour is not None:
        bg.inputs["Color"].default_value = (*colour, 1)
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.sky_type = "MULTIPLE_SCATTERING"
        sky.sun_disc = False
        sky.sun_elevation = math.radians(sun_elevation)
        sky.sun_rotation = math.radians(sun_azimuth)  # same clockwise-from-north convention
        sky.air_density = air
        sky.aerosol_density = aerosol
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return world


# Daylight HDRIs (blender/assets/manifest/environment.json). sun_azimuth: where the
# photo's sun lands with no rotation; sun_irradiance: the energy clamped out of its
# sun disc, relative to the sky (so a sun lamp of that strength puts it back).
HDRIS = {
    "studio_garden": {"asset": "hdri_studio_garden", "file": "studio_garden_8k.exr",
                      "sun_azimuth": 126.2, "sun_irradiance": 8.0},
}


def build_hdri_world(name, sun_azimuth, strength=1.0, clamp=20.0, mirror=False, backplate=1.0):
    """Photographic sky: light, reflections and the view out of the windows.

    Rotated so the photo's sun sits at sun_azimuth (0 = north, clockwise); its
    disc is clamped away and build_sun() stands in for it. mirror flips the
    photo east-west (the sun stays put). backplate scales only what the camera
    sees directly, to balance the bright view against the interior.
    """
    info = HDRIS[name]
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    nt = world.node_tree
    nodes, link = nt.nodes, nt.links.new
    bg = nodes.get("Background") or nodes.new("ShaderNodeBackground")
    out = nodes.get("World Output") or nodes.new("ShaderNodeOutputWorld")
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    turn = (-sun_azimuth if mirror else sun_azimuth) - info["sun_azimuth"]
    mapping.inputs["Rotation"].default_value = (0, 0, math.radians(turn))
    mapping.inputs["Scale"].default_value = (-1 if mirror else 1, 1, 1)
    env = nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(assets.path(info["asset"], info["file"]), check_existing=True)
    env.interpolation = "Cubic"
    link(coord.outputs["Generated"], mapping.inputs["Vector"])
    link(mapping.outputs["Vector"], env.inputs["Vector"])
    colour = env.outputs["Color"]
    if clamp:
        lo = nodes.new("ShaderNodeVectorMath")
        lo.operation = "MINIMUM"
        lo.inputs[1].default_value = (clamp, clamp, clamp)
        link(colour, lo.inputs[0])
        colour = lo.outputs["Vector"]
    link(colour, bg.inputs["Color"])
    if backplate == 1.0:
        bg.inputs["Strength"].default_value = strength
    else:
        path = nodes.new("ShaderNodeLightPath")
        mix = nodes.new("ShaderNodeMix")
        mix.inputs["A"].default_value = strength
        mix.inputs["B"].default_value = strength * backplate
        link(path.outputs["Is Camera Ray"], mix.inputs["Factor"])
        link(mix.outputs["Result"], bg.inputs["Strength"])
    link(bg.outputs[0], out.inputs["Surface"])
    return world


def build_daylight(sun_azimuth, sun_elevation, hdri="studio_garden", strength=1.0, mirror=False, backplate=1.0,
                   sun_colour=(1.0, 0.9, 0.8)):
    """HDRI sky plus a sun lamp standing in for its (clamped) sun, at the same azimuth and energy."""
    world = build_hdri_world(hdri, sun_azimuth, strength, mirror=mirror, backplate=backplate)
    sun = build_sun(sun_azimuth, sun_elevation, strength=HDRIS[hdri]["sun_irradiance"] * strength, colour=sun_colour)
    return world, sun
