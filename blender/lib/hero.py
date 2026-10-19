"""Hero objects: detailed scripted models for the objects visitors can inspect.

Each hero is one mesh object (so it can be exported on its own as glTF), built
from bevelled bmesh parts. Shading is smooth with weighted normals, so flat
faces stay flat and bevels catch the light. Materials are plain Principled
BSDFs (prefixed ``hero_``) so they survive the glTF export as PBR.

All models are generic: no logos, badges or text.

Conventions match lib.furniture: ``loc`` is the base of the object, the front
faces -Y in local space, and ``rot_z`` turns it about Z.
"""

import math

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

SHARP_ANGLE = math.radians(42)


# --------------------------------------------------------------------------- materials

def _principled(name, color, roughness, metallic=0.0, **extra):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass  # Blender 5+: materials always use nodes
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    for key, value in extra.items():
        socket = bsdf.inputs[key]
        socket.default_value = (*value, 1) if isinstance(value, tuple) and len(value) == 3 else value
    mat.diffuse_color = (*color, 1)
    mat.roughness = roughness
    mat.metallic = metallic
    return mat


def _with_bump(mat, scale, strength, stretch=(1, 1, 1), distance=0.0005):
    """Fine procedural surface texture (Cycles only; glTF keeps the flat PBR values)."""
    nt = mat.node_tree
    if any(n.type == "BUMP" for n in nt.nodes):
        return mat
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = stretch
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 6
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def materials():
    """The hero material set (created once, reused)."""
    return {
        # bead-blasted / brushed aluminium, like a display enclosure
        "aluminium": _with_bump(
            _principled("hero_aluminium", (0.80, 0.80, 0.81), 0.3, 1.0),
            scale=900, strength=0.05, stretch=(1, 1, 60)),
        "screen": _principled("hero_screen_glass", (0.006, 0.006, 0.007), 0.04,
                              **{"Coat Weight": 1.0, "Coat Roughness": 0.02}),
        "screen_on": _screen_image(),
        "gloss_black": _principled("hero_gloss_black", (0.01, 0.01, 0.01), 0.18),
        "body": _with_bump(_principled("hero_leatherette", (0.022, 0.022, 0.022), 0.55),
                           scale=1500, strength=0.35),
        "plastic": _principled("hero_plastic_black", (0.025, 0.025, 0.026), 0.4),
        "rubber": _principled("hero_rubber", (0.015, 0.015, 0.015), 0.75),
        "metal_black": _principled("hero_anodised_black", (0.03, 0.03, 0.032), 0.32, 0.85),
        "metal_dark": _principled("hero_anodised_grey", (0.12, 0.12, 0.125), 0.35, 1.0),
        "chrome": _principled("hero_chrome", (0.86, 0.86, 0.85), 0.12, 1.0),
        "lens_glass": _principled("hero_lens_glass", (0.004, 0.006, 0.01), 0.02, 0.5,
                                  **{"Coat Weight": 1.0, "Coat Roughness": 0.0,
                                     "Coat Tint": (0.85, 0.95, 0.88)}),
        "marking": _principled("hero_marking_white", (0.85, 0.85, 0.82), 0.5),
    }


def _wallpaper(name="hero_wallpaper", w=480, h=300):
    """A calm abstract gradient for the lit screen, generated and packed into
    the .blend (and the .glb). No UI, text or logos."""
    img = bpy.data.images.get(name)
    if img:
        return img
    import numpy as np

    img = bpy.data.images.new(name, w, h, alpha=False)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = x / (w - 1), y / (h - 1)  # v = 0 at the bottom
    deep = np.array([0.015, 0.03, 0.06])
    teal = np.array([0.05, 0.20, 0.24])
    warm = np.array([0.55, 0.32, 0.18])
    t = np.clip(v * 0.9 + 0.15 * np.sin(u * 3.2 + 0.6), 0, 1)[..., None]
    col = deep * (1 - t) + teal * t
    # soft dune-like band and a warm glow, all very low frequency
    band = np.exp(-((v - 0.42 - 0.12 * np.sin(u * 4.0 + 1.2)) / 0.09) ** 2)[..., None]
    glow = np.exp(-(((u - 0.72) / 0.25) ** 2 + ((v - 0.62) / 0.3) ** 2))[..., None]
    col = col + band * teal * 0.9 + glow * warm * 0.55
    col = np.clip(col, 0, 1) ** (1 / 2.2)  # sRGB-ish
    rgba = np.concatenate([col, np.ones((h, w, 1), np.float32)], axis=2).astype(np.float32)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def _screen_image():
    mat = bpy.data.materials.get("hero_screen_image")
    if mat:
        return mat
    mat = _principled("hero_screen_image", (0.0, 0.0, 0.0), 0.12,
                      **{"Emission Color": (1.0, 1.0, 1.0), "Emission Strength": 0.9})
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = _wallpaper()
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    return mat


# --------------------------------------------------------------------------- builder

class HeroBuilder:
    """Like geo.Builder, but every part can be bevelled and parts can be placed
    inside nested transforms (push/pop), so sub-assemblies such as a tilted
    display head or a splayed tripod leg are easy to describe."""

    def __init__(self):
        self.bm = bmesh.new()
        self.mats = []
        self.stack = [Matrix.Identity(4)]

    # transforms ----------------------------------------------------------
    @property
    def matrix(self):
        return self.stack[-1]

    def push(self, matrix):
        self.stack.append(self.stack[-1] @ matrix)

    def pop(self):
        self.stack.pop()

    # internals -----------------------------------------------------------
    def _finish(self, verts, mat, bevel=0.0, segments=3, edge_filter=None, angle=SHARP_ANGLE):
        verts = set(verts)
        if bevel > 0:
            edges = {e for v in verts for e in v.link_edges}
            edges = [e for e in edges if e.is_manifold and e.calc_face_angle(0) > angle
                     and (edge_filter is None or edge_filter(e))]
            if edges:
                res = bmesh.ops.bevel(self.bm, geom=edges, offset=bevel, offset_type="OFFSET",
                                      segments=segments, profile=0.5, affect="EDGES",
                                      clamp_overlap=True)
                verts |= set(res["verts"])
                verts = {v for v in verts if v.is_valid}
                for f in res["faces"]:
                    for v in f.verts:
                        verts.add(v)
        if mat not in self.mats:
            self.mats.append(mat)
        index = self.mats.index(mat)
        for face in {f for v in verts for f in v.link_faces}:
            face.material_index = index
            face.smooth = True
        return verts

    @staticmethod
    def _local(center, rot):
        return Matrix.Translation(center) @ Euler(rot).to_matrix().to_4x4()

    # primitives ----------------------------------------------------------
    def box(self, size, center, mat, rot=(0, 0, 0), bevel=0.0, segments=3, taper=None,
            edge_filter=None):
        """taper=(sx, sy) scales the top face, for wedge and prism shapes."""
        res = bmesh.ops.create_cube(self.bm, size=1.0)
        verts = res["verts"]
        if taper:
            for v in verts:
                if v.co.z > 0:
                    v.co.x *= taper[0]
                    v.co.y *= taper[1]
        m = self.matrix @ self._local(center, rot) @ Matrix.Diagonal((*size, 1.0))
        bmesh.ops.transform(self.bm, matrix=m, verts=verts)
        local_filter = None
        if edge_filter:
            inv = (self.matrix @ self._local(center, rot)).inverted()
            local_filter = lambda e: edge_filter(inv @ ((e.verts[0].co + e.verts[1].co) / 2))  # noqa: E731
        return self._finish(verts, mat, bevel, segments, local_filter)

    def cyl(self, radius, depth, center, mat, rot=(0, 0, 0), segments=48, radius2=None,
            bevel=0.0, bevel_segments=2, ribs=0, rib_depth=0.0):
        """Cylinder or cone along local Z. ribs>0 adds knurled grip ridges."""
        if ribs:
            segments = max(segments, ribs * 4)
        res = bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=segments, radius1=radius,
            radius2=radius if radius2 is None else radius2, depth=depth)
        verts = res["verts"]
        if ribs:
            for v in verts:
                r = math.hypot(v.co.x, v.co.y)
                if r < 1e-6:
                    continue
                a = math.atan2(v.co.y, v.co.x)
                k = 1 - rib_depth / r * (0.5 - 0.5 * math.cos(ribs * a))
                v.co.x *= k
                v.co.y *= k
        bmesh.ops.transform(self.bm, matrix=self.matrix @ self._local(center, rot), verts=verts)
        return self._finish(verts, mat, bevel, bevel_segments, angle=math.radians(60))

    def rod(self, p0, p1, radius, mat, segments=20, radius2=None, bevel=0.0):
        """Cylinder between two points (in the current transform's space)."""
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        rot = d.to_track_quat("Z", "Y").to_euler()
        return self.cyl(radius, d.length, (p0 + p1) / 2, mat, rot=tuple(rot), segments=segments,
                        radius2=radius2, bevel=bevel)

    def torus(self, major, minor, center, mat, rot=(0, 0, 0), u=24, v=10, arc=2 * math.pi):
        """Ring in the local XY plane; arc < 2*pi gives an open loop (strap lugs)."""
        closed = arc >= 2 * math.pi - 1e-6
        nu = u if closed else u + 1
        grid = []
        for i in range(nu):
            a = arc * i / u
            ring = []
            for j in range(v):
                b = 2 * math.pi * j / v
                r = major + minor * math.cos(b)
                ring.append(self.bm.verts.new((r * math.cos(a), r * math.sin(a), minor * math.sin(b))))
            grid.append(ring)
        segs = nu if closed else nu - 1
        for i in range(segs):
            r0, r1 = grid[i], grid[(i + 1) % nu]
            for j in range(v):
                self.bm.faces.new((r0[j], r1[j], r1[(j + 1) % v], r0[(j + 1) % v]))
        if not closed:
            self.bm.faces.new(list(reversed(grid[0])))
            self.bm.faces.new(grid[-1])
        verts = [vv for ring in grid for vv in ring]
        bmesh.ops.transform(self.bm, matrix=self.matrix @ self._local(center, rot), verts=verts)
        return self._finish(verts, mat)

    def strip(self, path, width, thickness, mat, bevel=0.0):
        """A bent plate: path is a list of (y, z) centreline points, extruded
        along X (width) with the given thickness. Gives clean quad topology."""
        pts = [Vector((0, y, z)) for y, z in path]
        normals = []
        for i, p in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, len(pts) - 1)]
            t = (b - a).normalized()
            normals.append(Vector((0, -t.z, t.y)))
        rows = []
        for p, n in zip(pts, normals):
            row = []
            for x in (-width / 2, width / 2):
                for s in (-1, 1):
                    row.append(self.bm.verts.new(p + n * s * thickness / 2 + Vector((x, 0, 0))))
            rows.append(row)  # [x-, in], [x-, out], [x+, in], [x+, out]
        for r0, r1 in zip(rows, rows[1:]):
            self.bm.faces.new((r0[1], r1[1], r1[3], r0[3]))  # outer
            self.bm.faces.new((r0[2], r1[2], r1[0], r0[0]))  # inner
            self.bm.faces.new((r0[0], r1[0], r1[1], r0[1]))  # x- side
            self.bm.faces.new((r0[3], r1[3], r1[2], r0[2]))  # x+ side
        self.bm.faces.new((rows[0][0], rows[0][1], rows[0][3], rows[0][2]))
        self.bm.faces.new((rows[-1][2], rows[-1][3], rows[-1][1], rows[-1][0]))
        verts = [v for row in rows for v in row]
        bmesh.ops.recalc_face_normals(self.bm, faces=list({f for v in verts for f in v.link_faces}))
        bmesh.ops.transform(self.bm, matrix=self.matrix, verts=verts)
        return self._finish(verts, mat, bevel, 2)

    def planar_uvs(self, verts, to_local, origin, size):
        """Project UVs onto the local XZ plane (for image-mapped faces)."""
        uv = self.bm.loops.layers.uv.verify()
        faces = {f for v in verts for f in v.link_faces}
        for f in faces:
            for loop in f.loops:
                p = to_local @ loop.vert.co
                loop[uv].uv = ((p.x - origin[0]) / size[0], (p.z - origin[1]) / size[1])

    # output --------------------------------------------------------------
    def build(self, name, col, location=(0, 0, 0), rot_z=0.0):
        mesh = bpy.data.meshes.new(name)
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-6)
        self.bm.normal_update()
        self.bm.to_mesh(mesh)
        self.bm.free()
        for mat in self.mats:
            mesh.materials.append(mat)
        mesh.set_sharp_from_angle(angle=SHARP_ANGLE)
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        obj.rotation_euler = (0, 0, rot_z)
        mod = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        mod.mode = "FACE_AREA"
        mod.keep_sharp = True
        mod.weight = 50
        col.objects.link(obj)
        obj["hero"] = True
        return obj


def _fillet(points, radius, steps=8):
    """Round the interior corners of a 2D polyline with arcs of the given radius."""
    pts = [Vector(p) for p in points]
    out = [pts[0]]
    for a, b_, c in zip(pts, pts[1:], pts[2:]):
        u1, u2 = (a - b_).normalized(), (c - b_).normalized()
        half = u1.angle(u2) / 2
        d = radius / math.tan(half)
        t1, t2 = b_ + u1 * d, b_ + u2 * d
        centre = b_ + (u1 + u2).normalized() * radius / math.sin(half)
        a0 = math.atan2(*(t1 - centre).yx)
        a1 = math.atan2(*(t2 - centre).yx)
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for i in range(steps + 1):
            ang = a0 + sweep * i / steps
            out.append(centre + Vector((math.cos(ang), math.sin(ang))) * radius)
    out.append(pts[-1])
    return [tuple(p) for p in out]


# --------------------------------------------------------------------------- display

def display(col, name, loc, rot_z=0.0, width=0.66, height=0.46, lift=0.12, tilt_deg=5.0):
    """Aluminium widescreen display: thin bezel, rounded rear shell, and a single
    bent aluminium foot that leans back from a hinge and runs forward under the
    screen. loc is on the desk surface; the screen faces -Y."""
    m = materials()
    b = HeroBuilder()
    zc = lift + height / 2
    hinge = Vector((0, 0.058, zc - 0.03))

    # --- head, tilted back about the hinge
    b.push(Matrix.Translation(hinge) @ Matrix.Rotation(math.radians(-tilt_deg), 4, "X")
           @ Matrix.Translation(-hinge))
    frame_d = 0.012
    b.box((width, frame_d, height), (0, 0, zc), m["aluminium"], bevel=0.0035, segments=3)
    # edge-to-edge glass with a thin black border, and the lit image area
    b.box((width - 0.008, 0.002, height - 0.008), (0, -frame_d / 2 - 0.0008, zc), m["screen"],
          bevel=0.0008, segments=1)
    border = 0.014
    image_verts = b.box((width - 2 * border, 0.0004, height - 2 * border),
                        (0, -frame_d / 2 - 0.0019, zc), m["screen_on"])
    b.planar_uvs(image_verts, b.matrix.inverted(), (-width / 2 + border, zc - height / 2 + border),
                 (width - 2 * border, height - 2 * border))
    # rounded rear shell: big radius on the back edges only
    shell_d = 0.04
    b.box((width - 0.04, shell_d, height - 0.04), (0, frame_d / 2 + shell_d / 2 - 0.001, zc),
          m["aluminium"], bevel=0.034, segments=10,
          edge_filter=lambda c: c.y > 0.004)
    # a soft central bulge where the electronics live
    b.box((width * 0.55, 0.03, height * 0.6), (0, frame_d / 2 + shell_d - 0.012, zc - 0.02),
          m["aluminium"], bevel=0.026, segments=8, edge_filter=lambda c: c.y > 0.004)
    # ventilation slots along the top of the shell
    for i in range(18):
        x = (i - 8.5) * 0.022
        b.box((0.012, 0.016, 0.002), (x, frame_d / 2 + 0.014, zc + height / 2 - 0.0255),
              m["gloss_black"], rot=(0.5, 0, 0))
    # hinge boss
    b.cyl(0.02, width * 0.24, (0, hinge.y - 0.008, hinge.z), m["aluminium"],
          rot=(0, math.pi / 2, 0), bevel=0.003)
    b.pop()

    # --- the foot: one bent plate, hinge -> down and back -> forward along the desk
    t, foot_w = 0.008, 0.17
    back_y, front_y = 0.2, -0.075
    top = (hinge.y + 0.004, hinge.z)
    path = _fillet([top, (back_y, t / 2), (front_y, t / 2)], radius=0.04, steps=10)
    b.strip(path, foot_w, t, m["aluminium"], bevel=0.0015)
    # cable pass-through: a dark ring on the incline
    mid = Vector((0, (path[0][0] + path[1][0]) / 2, (path[0][1] + path[1][1]) / 2))
    d = Vector((0, path[1][0] - path[0][0], path[1][1] - path[0][1])).normalized()
    nrm = Vector((0, d.z, -d.y))
    if nrm.y < 0:
        nrm = -nrm
    b.rod(mid + d * 0.03 - nrm * 0.006, mid + d * 0.03 + nrm * 0.006, 0.017, m["gloss_black"],
          segments=40)
    # soft pads under the foot
    for y in (front_y + 0.02, back_y - 0.06):
        b.box((foot_w - 0.03, 0.02, 0.0015), (0, y, 0.00075), m["rubber"])
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- camera

def camera(col, name, loc, rot_z=0.0):
    """DSLR-style body with a deep grip, prism hump, top dials, rear screen,
    strap lugs and a standard zoom with ribbed rings. Lens points -Y."""
    m = materials()
    b = HeroBuilder()
    bw, bd, bh = 0.134, 0.052, 0.088
    y0 = 0.006  # body centre
    front = y0 - bd / 2
    back = y0 + bd / 2
    axis_z = 0.046

    # body shell and deep grip on the camera's right (-X when the lens faces -Y)
    b.box((bw, bd, bh), (0, y0, bh / 2), m["plastic"], bevel=0.007, segments=4)
    b.box((bw - 0.02, 0.004, bh - 0.022), (0.006, front - 0.0015, bh / 2 - 0.004), m["body"],
          bevel=0.0015, segments=2)
    b.box((0.04, 0.034, bh - 0.006), (-bw / 2 + 0.018, front - 0.011, bh / 2 - 0.002), m["body"],
          bevel=0.014, segments=5)
    b.box((0.03, 0.02, 0.05), (-bw / 2 + 0.014, back - 0.006, bh / 2 + 0.012), m["body"],
          bevel=0.008, segments=3)  # thumb rest
    # prism hump, hot shoe, eyepiece
    b.box((0.066, 0.05, 0.03), (0, y0 - 0.002, bh + 0.013), m["plastic"],
          taper=(0.62, 0.7), bevel=0.004, segments=3)
    b.box((0.022, 0.02, 0.003), (0, y0 + 0.002, bh + 0.029), m["chrome"], bevel=0.0006, segments=1)
    b.box((0.042, 0.016, 0.03), (0, back + 0.006, bh + 0.002), m["rubber"], bevel=0.005, segments=3)
    b.box((0.022, 0.002, 0.014), (0, back + 0.0142, bh + 0.003), m["lens_glass"])
    # top: mode dial (left), shutter + command dial on the grip, small status screen
    b.cyl(0.015, 0.012, (0.042, y0, bh + 0.006), m["plastic"], ribs=36, rib_depth=0.0008,
          bevel=0.0008)
    b.cyl(0.0018, 0.0016, (0.042 + 0.010, y0 - 0.006, bh + 0.0125), m["marking"], segments=12)
    b.cyl(0.011, 0.004, (-bw / 2 + 0.02, front - 0.012, bh + 0.002), m["plastic"], ribs=24,
          rib_depth=0.0006)
    b.cyl(0.0055, 0.004, (-bw / 2 + 0.02, front - 0.012, bh + 0.006), m["chrome"], bevel=0.001)
    b.box((0.03, 0.018, 0.0012), (-0.038, y0 + 0.006, bh + 0.0004), m["screen"])
    # back: screen and buttons
    b.box((0.078, 0.003, 0.056), (0.014, back + 0.0012, 0.042), m["gloss_black"], bevel=0.001,
          segments=1)
    b.box((0.072, 0.0006, 0.05), (0.014, back + 0.0028, 0.042), m["screen"])
    for i, z in enumerate((0.066, 0.05, 0.034, 0.018)):
        b.cyl(0.0036, 0.003, (0.061 - 0.004, back + 0.0012, z), m["plastic"], rot=(math.pi / 2, 0, 0),
              segments=16, bevel=0.0006)
    b.cyl(0.011, 0.003, (-bw / 2 + 0.03, back + 0.0012, 0.04), m["plastic"], rot=(math.pi / 2, 0, 0),
          ribs=20, rib_depth=0.0005)
    # strap lugs on both shoulders
    for sx in (-1, 1):
        x = sx * (bw / 2 - 0.002)
        b.box((0.006, 0.012, 0.012), (x + sx * 0.002, y0, bh - 0.008), m["metal_black"],
              bevel=0.002, segments=2)
        b.torus(0.0065, 0.0016, (x + sx * 0.007, y0, bh - 0.002), m["chrome"],
                rot=(math.pi / 2, 0, 0), u=16, v=8)
    # lens mount and lens (along -Y)
    b.push(Matrix.Translation((0, front, axis_z)) @ Euler((math.pi / 2, 0, 0)).to_matrix().to_4x4())
    # in this frame local +Z points out of the body along -Y, +Y is up
    b.cyl(0.031, 0.004, (0, 0, 0.002), m["chrome"], bevel=0.0008)
    b.cyl(0.0335, 0.012, (0, 0, 0.010), m["metal_black"], bevel=0.0012)
    b.cyl(0.033, 0.052, (0, 0, 0.042), m["plastic"])
    b.cyl(0.0355, 0.03, (0, 0, 0.034), m["rubber"], ribs=60, rib_depth=0.0012, bevel=0.0015)
    b.box((0.0016, 0.004, 0.0004), (0, 0.0332, 0.054), m["marking"], rot=(math.pi / 2, 0, 0))
    b.cyl(0.034, 0.016, (0, 0, 0.078), m["rubber"], ribs=48, rib_depth=0.0009, bevel=0.001)
    b.cyl(0.036, 0.012, (0, 0, 0.092), m["plastic"], radius2=0.0375, bevel=0.0015)
    b.cyl(0.0372, 0.003, (0, 0, 0.0995), m["metal_black"], bevel=0.0008)
    b.cyl(0.03, 0.0015, (0, 0, 0.1003), m["metal_black"])
    b.cyl(0.028, 0.004, (0, 0, 0.1012), m["lens_glass"], radius2=0.02, segments=48)
    b.pop()
    return b.build(name, col, loc, rot_z)


# --------------------------------------------------------------------------- tripod

def tripod(col, name, loc, height=1.35, spread=0.38, rot_z=0.0):
    """Three-section tripod with flip-lock leg clamps, a geared centre column and
    a fluid pan head with a handle. loc is the floor point under the column."""
    m = materials()
    b = HeroBuilder()
    yoke_z = height - 0.36
    head_base = height - 0.11

    # yoke (spider) casting with hinge lugs
    b.cyl(0.048, 0.05, (0, 0, yoke_z), m["metal_dark"], bevel=0.004, segments=36)
    b.cyl(0.03, 0.03, (0, 0, yoke_z + 0.038), m["metal_dark"], bevel=0.003, segments=36)
    b.cyl(0.006, 0.03, (0.034, 0, yoke_z + 0.04), m["plastic"], rot=(0, math.pi / 2, 0),
          ribs=10, rib_depth=0.001, segments=40)  # column lock knob stem
    b.cyl(0.014, 0.012, (0.05, 0, yoke_z + 0.04), m["plastic"], rot=(0, math.pi / 2, 0),
          ribs=12, rib_depth=0.002, bevel=0.002)

    for i in range(3):
        a = i * 2 * math.pi / 3
        dirx, diry = math.cos(a), math.sin(a)
        top = Vector((dirx * 0.06, diry * 0.06, yoke_z))
        foot = Vector((dirx * (spread - 0.012), diry * (spread - 0.012), 0.024))
        leg = foot - top
        rot = leg.to_track_quat("Z", "Y").to_matrix().to_4x4()
        # hinge lug on the yoke
        b.box((0.03, 0.03, 0.04), (dirx * 0.05, diry * 0.05, yoke_z), m["metal_dark"],
              rot=(0, 0, a), bevel=0.004, segments=2)
        b.cyl(0.008, 0.036, (dirx * 0.06, diry * 0.06, yoke_z), m["chrome"],
              rot=(math.pi / 2, 0, a), segments=16)
        # leg in its own frame: local Z runs from the hinge (0) to the foot (L)
        L = leg.length
        b.push(Matrix.Translation(top) @ rot)
        sections = [(0.0, 0.43, 0.0145, m["metal_black"]),
                    (0.40, 0.72, 0.0118, m["metal_black"]),
                    (0.69, 0.985, 0.0095, m["metal_black"])]
        for t0, t1, r, mat in sections:
            b.cyl(r, (t1 - t0) * L, (0, 0, (t0 + t1) / 2 * L), mat, segments=24, bevel=0.0012)
        # foam grip on the upper section
        b.cyl(0.019, 0.22 * L, (0, 0, 0.17 * L), m["rubber"], segments=28, bevel=0.003)
        # flip-lock clamps at the joints
        for t, r in ((0.425, 0.0145), (0.715, 0.0118)):
            z = t * L
            b.cyl(r + 0.0045, 0.03, (0, 0, z), m["plastic"], segments=28, bevel=0.002)
            b.box((0.016, 0.012, 0.042), (0, -(r + 0.009), z - 0.004), m["plastic"],
                  bevel=0.003, segments=2)
            b.cyl(0.0025, 0.022, (0, -(r + 0.006), z + 0.013), m["chrome"], rot=(0, math.pi / 2, 0),
                  segments=12)
        # rubber foot
        b.cyl(0.0125, 0.03, (0, 0, L + 0.006), m["rubber"], radius2=0.016, segments=24, bevel=0.003)
        b.pop()

    # centre column with a collar, rising to the head
    col_bottom = yoke_z - 0.22
    b.cyl(0.0165, head_base - col_bottom, (0, 0, (head_base + col_bottom) / 2), m["metal_black"],
          segments=28)
    b.cyl(0.02, 0.012, (0, 0, col_bottom + 0.006), m["plastic"], segments=28, bevel=0.002)
    b.cyl(0.026, 0.02, (0, 0, head_base - 0.01), m["metal_dark"], bevel=0.002, segments=36)

    # fluid head: pan base, tilt body, quick-release plate, handle. Built with the
    # pan bar towards +Y, then turned so it points between two legs.
    z = head_base
    b.push(Matrix.Rotation(math.radians(-30), 4, "Z"))
    b.cyl(0.04, 0.018, (0, 0, z + 0.009), m["metal_black"], bevel=0.002, segments=48)
    b.cyl(0.041, 0.006, (0, 0, z + 0.004), m["plastic"], ribs=48, rib_depth=0.001)
    b.cyl(0.035, 0.03, (0, 0, z + 0.033), m["metal_black"], bevel=0.003, segments=48)
    b.box((0.078, 0.064, 0.056), (0, 0, z + 0.074), m["metal_black"], bevel=0.008, segments=3)
    b.cyl(0.02, 0.012, (0.044, 0, z + 0.074), m["plastic"], rot=(0, math.pi / 2, 0),
          ribs=16, rib_depth=0.0015, bevel=0.002)  # tilt lock
    b.cyl(0.012, 0.012, (-0.044, 0, z + 0.074), m["chrome"], rot=(0, math.pi / 2, 0), bevel=0.002)
    b.box((0.062, 0.12, 0.012), (0, -0.006, z + 0.108), m["metal_dark"], bevel=0.003, segments=2)
    b.box((0.05, 0.1, 0.008), (0, -0.006, z + 0.118), m["metal_black"], bevel=0.002, segments=2)
    b.box((0.04, 0.02, 0.003), (0, -0.006, z + 0.1235), m["rubber"])
    b.cyl(0.0042, 0.003, (0, 0.03, z + 0.103 + 0.005), m["lens_glass"], segments=16)  # bubble
    # pan bar: from the back of the head, down and away, with a foam grip
    p0 = Vector((0.03, 0.02, z + 0.078))
    p1 = Vector((0.07, 0.15, z + 0.03))
    p2 = Vector((0.1, 0.30, z - 0.04))
    b.cyl(0.012, 0.016, (0.034, 0.016, z + 0.078), m["plastic"], rot=(0, math.pi / 2, 0), bevel=0.002)
    b.rod(p0, p1, 0.0075, m["metal_black"], segments=18)
    b.rod(p1 - (p1 - p0).normalized() * 0.002, p2, 0.0075, m["metal_black"], segments=18)
    b.rod(p1 + (p2 - p1) * 0.2, p2 + (p2 - p1).normalized() * 0.012, 0.012, m["rubber"],
          segments=20, bevel=0.003)
    b.pop()
    return b.build(name, col, loc, rot_z)
