"""Imported models (glTF / FBX / OBJ from the asset cache), and scripted
stand-ins for pieces no CC0 library has (office chair, floor lamp, bins).

load() brings a cached asset in as ONE named mesh object: world transforms are
baked, parts joined, materials prefixed with the asset id, the origin moved to
the base centre, the front turned to local -Y and the size set to real-world
metres. Conventions match lib.furniture: ``loc`` is the floor contact point and
``rot_z`` turns the object about Z.

Every object here carries ``no_bevel`` (finish_scene's bevel pass is for
Builder boxes) and is shaded smooth with sharp edges by angle.
"""

import math
import os
import re

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import assets
from .geo import Builder

SHARP_ANGLE = math.radians(35)
FRONT = {"-Y": 0.0, "+Y": math.pi, "+X": -math.pi / 2, "-X": math.pi / 2}


# --------------------------------------------------------------------------- import

def _import_file(path):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        try:
            bpy.ops.wm.fbx_import(filepath=path)
        except AttributeError:
            bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path, forward_axis="NEGATIVE_Z", up_axis="Y")
    else:
        raise ValueError(f"Can't import {path}: use .gltf/.glb/.fbx/.obj")
    return [o for o in bpy.data.objects if o not in before]


def _bake(objs):
    """Bake world transforms into mesh data; drop empties, cameras and lights."""
    meshes = [o for o in objs if o.type == "MESH"]
    for o in meshes:
        if o.data.users > 1:
            o.data = o.data.copy()
        mw = o.matrix_world.copy()
        o.parent = None
        o.data.transform(mw)
        o.matrix_world = Matrix.Identity(4)
    for o in objs:
        if o.type != "MESH":
            bpy.data.objects.remove(o)
    return meshes


def _prefix_materials(meshes, asset_id):
    prefix = f"{asset_id}_"
    for o in meshes:
        for slot in o.material_slots:
            mat = slot.material
            if mat is None:
                continue
            base = re.sub(r"\.\d{3}$", "", mat.name)
            name = base if base.startswith(prefix) else prefix + base
            if name == mat.name:
                continue
            existing = bpy.data.materials.get(name)
            if existing:  # same asset imported before: share its materials
                slot.material = existing
                if mat.users == 0:
                    bpy.data.materials.remove(mat)
            else:
                mat.name = name


def join(objs, name=None):
    """Join mesh objects into the first one (keeps world placement)."""
    target = objs[0]
    if len(objs) > 1:
        with bpy.context.temp_override(active_object=target, object=target, selected_objects=objs,
                                       selected_editable_objects=objs):
            bpy.ops.object.join()
    if name:
        target.name = name
        target.data.name = name
    return target


def _bounds(obj):
    co = [v.co for v in obj.data.vertices]
    lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
    hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
    return lo, hi


def load(asset_id, filename, col, name, loc=(0, 0, 0), rot_z=0.0, front="-Y",
         scale=1.0, height=None, footprint=None):
    """Import asset_id/filename as one mesh object named ``name``.

    front: the model's own front axis ("-Y", "+Y", "+X", "-X"), turned to -Y.
    Size: ``height`` (m) or ``footprint`` ((w, d) m, fits inside, keeps
    proportions) override ``scale`` (multiplier on the file's own units).
    """
    meshes = _bake(_import_file(assets.path(asset_id, filename)))
    if not meshes:
        raise ValueError(f"{asset_id}/{filename} has no meshes")
    _prefix_materials(meshes, asset_id)
    obj = join(meshes, name)
    obj.data.transform(Matrix.Rotation(FRONT[front], 4, "Z"))
    lo, hi = _bounds(obj)
    obj.data.transform(Matrix.Translation(-Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))))
    size = hi - lo
    if height:
        scale = height / size.z
    elif footprint:
        scale = min(footprint[0] / size.x, footprint[1] / size.y)
    obj.data.transform(Matrix.Scale(scale, 4))
    obj.data.update()
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (0, 0, rot_z)
    obj["asset_id"] = asset_id
    obj["no_bevel"] = True
    return obj


# --------------------------------------------------------------------------- bmesh parts
# Each part is made in its own bmesh (so bevels can't touch its neighbours),
# placed, then appended to the object's Builder with one material.

def _material(name, color, roughness, metallic=0.0):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass  # Blender 5+: materials always use nodes
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def _merge(b, bm, mat, matrix=None):
    if matrix is not None:
        bm.transform(matrix)
    tmp = bpy.data.meshes.new("_part")
    bm.to_mesh(tmp)
    bm.free()
    start = len(b.bm.verts)
    b.bm.from_mesh(tmp)  # appends
    bpy.data.meshes.remove(tmp)
    b.bm.verts.ensure_lookup_table()
    b._assign(b.bm.verts[start:], mat)


def _round(bm, offset, segments=3):
    bmesh.ops.bevel(bm, geom=bm.verts[:] + bm.edges[:], offset=offset, segments=segments,
                    affect="EDGES", profile=0.5, clamp_overlap=True)


def _rbox(b, size, center, mat, radius, rot=Matrix.Identity(3), bend=0.0, segments=3):
    """Rounded box; ``bend`` curves it about local Z (y += bend * x^2), e.g. a chair back."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((*size, 1.0)))
    _round(bm, radius, segments)
    for v in bm.verts:
        v.co.y += bend * v.co.x ** 2
    _merge(b, bm, mat, Matrix.Translation(center) @ rot.to_4x4())


def _frustum(b, p0, p1, size0, size1, mat, radius=0.0):
    """Bar from p0 to p1 whose (width, height) section tapers from size0 to size1."""
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0).normalized()
    side = d.cross(Vector((0, 0, 1)))
    side = side.normalized() if side.length > 1e-6 else Vector((1, 0, 0))
    up = side.cross(d)
    sq = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    bm = bmesh.new()
    r0 = [bm.verts.new(p0 + side * sx * size0[0] / 2 + up * sz * size0[1] / 2) for sx, sz in sq]
    r1 = [bm.verts.new(p1 + side * sx * size1[0] / 2 + up * sz * size1[1] / 2) for sx, sz in sq]
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    bm.faces.new(r0)
    bm.faces.new(r1)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if radius:
        _round(bm, radius, 2)
    _merge(b, bm, mat)


def _lathe(b, profile, mat, center=(0, 0, 0), segments=48, cap_bottom=False, cap_top=False, closed=False):
    """Surface of revolution about Z from (radius, z) pairs, bottom to top
    (``closed`` joins the last pair back to the first, e.g. a torus)."""
    bm = bmesh.new()
    angles = [2 * math.pi * i / segments for i in range(segments)]
    rings = [[bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for a in angles] for r, z in profile]
    pairs = list(zip(rings, rings[1:])) + ([(rings[-1], rings[0])] if closed else [])
    for r0, r1 in pairs:
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    if cap_bottom:
        bm.faces.new(list(reversed(rings[0])))
    if cap_top:
        bm.faces.new(rings[-1])
    _merge(b, bm, mat, Matrix.Translation(center))


def _tube(b, points, radius, mat, sides=8):
    """Round tube along a polyline (cables, rods)."""
    pts = [Vector(p) for p in points]
    bm = bmesh.new()
    rings = []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        q = Vector((0, 0, 1)).rotation_difference(t)
        rings.append([bm.verts.new(p + q @ Vector((radius * math.cos(a), radius * math.sin(a), 0)))
                      for a in (2 * math.pi * k / sides for k in range(sides))])
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(sides):
            j = (k + 1) % sides
            bm.faces.new((r0[k], r0[j], r1[j], r1[k]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    _merge(b, bm, mat)


def _finish(obj, sharp=SHARP_ANGLE):
    obj.data.shade_smooth()
    try:
        obj.data.set_sharp_from_angle(angle=sharp)
    except (AttributeError, TypeError):
        pass
    obj["no_bevel"] = True
    return obj


# --------------------------------------------------------------------------- office chair

def office_chair(m, col, name, loc, rot_z=0.0):
    """Black task chair: five-star base on twin-wheel casters, gas lift, padded
    seat and curved back, loop arms. Seat front faces -Y."""
    b = Builder()
    base, metal, fabric = m["plastic_black_satin"], m["steel_black"], m["fabric_black"]
    for i in range(5):
        a = math.pi / 2 + i * 2 * math.pi / 5
        d = Vector((math.cos(a), math.sin(a), 0))
        _frustum(b, d * 0.04 + Vector((0, 0, 0.115)), d * 0.30 + Vector((0, 0, 0.085)),
                 (0.05, 0.045), (0.032, 0.028), base, radius=0.008)
        _caster(b, d * 0.30, a, base, metal)
    _lathe(b, [(0.06, 0.07), (0.065, 0.10), (0.06, 0.14), (0.035, 0.15)], base, cap_bottom=True)
    _lathe(b, [(0.035, 0.15), (0.031, 0.33), (0.024, 0.335)], base)  # telescopic shroud
    _lathe(b, [(0.014, 0.33), (0.014, 0.41)], metal, cap_top=True, segments=16)
    _rbox(b, (0.24, 0.26, 0.05), (0, 0.02, 0.425), base, 0.01)  # mechanism
    _frustum(b, (0.11, 0.0, 0.415), (0.2, -0.03, 0.41), (0.025, 0.01), (0.02, 0.008), base, 0.003)  # lever
    _rbox(b, (0.5, 0.48, 0.085), (0, 0, 0.49), fabric, 0.032)
    _rbox(b, (0.48, 0.05, 0.05), (0, -0.225, 0.47), fabric, 0.022)  # waterfall edge
    tilt = Matrix.Rotation(-0.14, 3, "X")
    _rbox(b, (0.46, 0.065, 0.5), (0, 0.29, 0.84), fabric, 0.03, rot=tilt, bend=0.35)
    _frustum(b, (0, 0.13, 0.44), (0, 0.28, 0.50), (0.07, 0.03), (0.06, 0.025), base, 0.008)  # spine
    _frustum(b, (0, 0.28, 0.50), (0, 0.33, 0.68), (0.06, 0.025), (0.08, 0.02), base, 0.008)
    for sx in (-1, 1):
        x = sx * 0.265
        _frustum(b, (x * 0.5, 0.05, 0.445), (x, 0.05, 0.455), (0.04, 0.012), (0.04, 0.012), base, 0.004)
        _frustum(b, (x, 0.07, 0.45), (x, 0.03, 0.665), (0.03, 0.05), (0.025, 0.04), base, 0.008)
        _rbox(b, (0.07, 0.25, 0.028), (x, -0.01, 0.68), base, 0.012)
    return _finish(b.build(name, col, loc, rot_z))


def _caster(b, p, a, body, metal):
    """Twin-wheel caster at the end of a base leg (leg direction angle ``a``)."""
    n = Vector((-math.sin(a), math.cos(a), 0))  # axle direction
    axle = Vector((0, 0, 1)).rotation_difference(n).to_euler()
    for s in (-1, 1):
        b.cyl(0.026, 0.014, p + n * s * 0.011 + Vector((0, 0, 0.026)), body, rot=axle, segments=20)
    _rbox(b, (0.05, 0.03, 0.026), p + Vector((0, 0, 0.05)), body, 0.009, rot=Matrix.Rotation(a, 3, "Z"))
    b.cyl(0.007, 0.03, p + Vector((0, 0, 0.075)), metal, segments=10)


# --------------------------------------------------------------------------- floor lamp

def floor_lamp(m, col, name, loc, height=1.75):
    """Black metal floor lamp: square base plate, slim stem, tapered square
    linen shade (open top and bottom) on a spider, a real bulb and a floor cable.
    The shade uses the shared "lampshade" material so the lamp glow still works."""
    b = Builder()
    steel, cable = m["steel_black"], m["plastic_black"]
    _rbox(b, (0.28, 0.28, 0.018), (0, 0, 0.009), steel, 0.004)
    _rbox(b, (0.05, 0.05, 0.01), (0, 0, 0.022), steel, 0.003)
    stem_top = height - 0.24
    _lathe(b, [(0.011, 0.02), (0.011, stem_top), (0.016, stem_top), (0.016, stem_top + 0.05),
               (0.012, stem_top + 0.06)], steel, cap_top=True, segments=16)  # stem + socket
    hi = height
    _shade(b, m["lampshade"], steel, (0.44, hi - 0.36), (0.34, hi))
    for k in range(4):  # spider arms from the socket to the top frame corners
        a = math.pi / 4 + k * math.pi / 2
        corner = Vector((math.cos(a), math.sin(a), 0)) * ((0.34 / 2 - 0.006) * math.sqrt(2))
        _tube(b, [(0, 0, stem_top + 0.05), (corner.x, corner.y, hi - 0.006)], 0.0018, steel, sides=6)
    _tube(b, [(0.0, 0.0, 0.02), (0.0, 0.1, 0.012), (0.0, 0.15, 0.004), (0.05, 0.3, 0.004),
              (0.22, 0.45, 0.004), (0.55, 0.52, 0.004), (0.9, 0.48, 0.004)], 0.0035, cable)
    lamp = b.build(name, col, loc)
    bulb = load("lightbulb_01", "lightbulb_01_1k.gltf", col, f"{name}_bulb_mesh",
                (loc[0], loc[1], loc[2] + stem_top + 0.04), height=0.1)
    _dim_emission(bulb, bpy.context.scene.get("lamp_glow", 0.0))  # filament glows only when the lamp is on
    return _finish(join([lamp, bulb], name))


def _dim_emission(obj, factor):
    for mat in {s.material for s in obj.material_slots if s.material and not s.material.get("dimmed")}:
        mat["dimmed"] = True
        for node in mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                node.inputs["Emission Strength"].default_value *= factor


def _shade(b, shade, steel, bottom, top, t=0.003):
    """Tapered square drum from (width, z) at the bottom to the top, closed thin
    walls with wire frames inside each lip."""
    (w0, z0), (w1, z1) = bottom, top
    sq = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    bm = bmesh.new()
    rings = [[bm.verts.new((sx * (w / 2 - i), sy * (w / 2 - i), z)) for sx, sy in sq]
             for w, z, i in ((w0, z0, 0), (w1, z1, 0), (w1, z1, t), (w0, z0, t))]
    for r0, r1 in zip(rings, rings[1:] + rings[:1]):
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    _merge(b, bm, shade)
    for w, z in ((w0, z0 + 0.004), (w1, z1 - 0.004)):
        c = w / 2 - t - 0.002
        _tube(b, [(sx * c, sy * c, z) for sx, sy in sq + sq[:1]], 0.0015, steel, sides=6)


# --------------------------------------------------------------------------- bins

def mesh_basket(m, col, name, loc, r0=0.14, r1=0.165, height=0.36):
    """Woven metal-mesh waste basket: diamond wire lattice between a solid base
    and a rolled top rim."""
    b = Builder()
    metal = _material("wire_mesh_grey", (0.3, 0.3, 0.3), 0.5, metallic=0.8)
    _lattice(b, r0 - 0.002, r1 - 0.002, 0.02, height - 0.006, metal)
    _lathe(b, [(0.004, 0.0), (r0 - 0.004, 0.0), (r0, 0.004), (r0, 0.022), (r0 - 0.004, 0.024),
               (0.004, 0.012)], metal, segments=64, cap_bottom=True, cap_top=True)
    rim = 0.0045
    _lathe(b, [(r1 + rim * math.cos(a), height - rim + rim * math.sin(a))
               for a in (2 * math.pi * i / 10 for i in range(10))], metal, segments=64, closed=True)
    return _finish(b.build(name, col, loc), sharp=math.radians(50))


def _lattice(b, r0, r1, z0, z1, mat, cols=84, wire=0.0024):
    """Diamond lattice on a tapered tube (row j is offset half a cell when j is
    odd), turned into wire."""
    bm = bmesh.new()
    cell = 2 * math.pi * (r0 + r1) / 2 / cols
    rows = max(2, round((z1 - z0) / (cell * 0.6)))
    grid = []
    for j in range(rows + 1):
        t = j / rows
        r, z = r0 + (r1 - r0) * t, z0 + (z1 - z0) * t
        off = 0.5 * (j % 2)
        grid.append([bm.verts.new((r * math.cos(2 * math.pi * (i + off) / cols),
                                   r * math.sin(2 * math.pi * (i + off) / cols), z)) for i in range(cols)])
    for j in range(rows - 1):
        o = j % 2
        for i in range(cols):
            bm.faces.new((grid[j][i], grid[j + 1][(i + o) % cols], grid[j + 2][i], grid[j + 1][(i - 1 + o) % cols]))
    top = rows % 2
    for i in range(cols):  # half diamonds along the bottom and top edges
        bm.faces.new((grid[0][i], grid[0][(i + 1) % cols], grid[1][i]))
        bm.faces.new((grid[rows][(i + 1) % cols], grid[rows][i], grid[rows - 1][(i + top) % cols]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.wireframe(bm, faces=bm.faces[:], thickness=wire, use_replace=True, use_boundary=True,
                        use_even_offset=True, use_relative_offset=False)
    _merge(b, bm, mat)


def white_drum(m, col, name, loc, radius=0.18, height=0.56):
    """White cylindrical drum stool: soft rounded edges, slightly dished top."""
    b = Builder()
    e = 0.012
    arc = [math.pi / 8 * i for i in range(5)]
    prof = [(radius - e + e * math.sin(a), e - e * math.cos(a)) for a in arc]
    prof += [(radius - e + e * math.cos(a), height - e + e * math.sin(a)) for a in arc]
    prof += [(radius - 0.03, height - 0.004), (0.02, height - 0.008)]
    _lathe(b, prof, m["plastic_white"], segments=64, cap_bottom=True, cap_top=True)
    return _finish(b.build(name, col, loc), sharp=math.radians(60))
