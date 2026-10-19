"""Low-level geometry helpers shared by every room."""

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    return scene


def collection(name, parent=None):
    col = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if col.name not in parent.children:
        parent.children.link(col)
    return col


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


class Builder:
    """Collects boxes and cylinders into a single mesh object.

    Parts are given in the object's local space; materials are assigned per part.
    One Builder = one object, so each piece of furniture stays selectable and
    exportable on its own.
    """

    def __init__(self):
        self.bm = bmesh.new()
        self.mats = []

    def _assign(self, verts, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        index = self.mats.index(mat)
        for face in {f for v in verts for f in v.link_faces}:
            face.material_index = index

    def box(self, size, center, mat, rot=(0, 0, 0)):
        m = (
            Matrix.Translation(center)
            @ Euler(rot).to_matrix().to_4x4()
            @ Matrix.Diagonal((*size, 1.0))
        )
        result = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        self._assign(result["verts"], mat)

    def cyl(self, radius, depth, center, mat, rot=(0, 0, 0), segments=32, radius2=None):
        m = Matrix.Translation(center) @ Euler(rot).to_matrix().to_4x4()
        result = bmesh.ops.create_cone(
            self.bm,
            cap_ends=True,
            cap_tris=False,
            segments=segments,
            radius1=radius,
            radius2=radius if radius2 is None else radius2,
            depth=depth,
            matrix=m,
        )
        self._assign(result["verts"], mat)

    def build(self, name, col, location=(0, 0, 0), rot_z=0.0):
        mesh = bpy.data.meshes.new(name)
        self.bm.normal_update()
        self.bm.to_mesh(mesh)
        self.bm.free()
        for mat in self.mats:
            mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        obj.rotation_euler = (0, 0, rot_z)
        col.objects.link(obj)
        return obj
