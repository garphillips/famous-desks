import * as THREE from 'three';
import type { PanoTiles } from '$lib/types';

/**
 * Cube-face geometry for tiled panoramas.
 *
 * Viewer axes (see direction() in PanoViewer): +X north, +Y up, +Z east, camera at the origin.
 * Faces are the six 90° views blender/lib/tour.py renders (CUBE_FACES there, in Blender axes
 * x east / y north / z up, which map to viewer axes as (y, z, x)). A point on a face is
 * forward + a·right + b·up, with a, b in -1..1; pixel (col i, row j) of an N px face is centred
 * at a = 2(i+0.5)/N - 1, b = 1 - 2(j+0.5)/N, so image row 0 is the top (b = 1).
 */
export type Face = 'n' | 'e' | 's' | 'w' | 'u' | 'd';
type Vec3 = [number, number, number];

/** Order of the faces in the preview strip. */
export const FACES: Face[] = ['n', 'e', 's', 'w', 'u', 'd'];

/** forward, image right, image up per face, viewer axes. */
export const FACE_AXES: Record<Face, [Vec3, Vec3, Vec3]> = {
	n: [[1, 0, 0], [0, 0, 1], [0, 1, 0]],
	e: [[0, 0, 1], [-1, 0, 0], [0, 1, 0]],
	s: [[-1, 0, 0], [0, 0, -1], [0, 1, 0]],
	w: [[0, 0, -1], [1, 0, 0], [0, 1, 0]],
	u: [[0, 1, 0], [0, 0, 1], [-1, 0, 0]],
	d: [[0, -1, 0], [0, 0, 1], [1, 0, 0]]
};

/** Point on face `face` at (a, b), on a cube of half-size `radius`. */
export function facePoint(face: Face, a: number, b: number, radius = 1, out = new THREE.Vector3()) {
	const [f, r, u] = FACE_AXES[face];
	return out.set(
		(f[0] + a * r[0] + b * u[0]) * radius,
		(f[1] + a * r[1] + b * u[1]) * radius,
		(f[2] + a * r[2] + b * u[2]) * radius
	);
}

export interface Tile {
	url: string;
	face: Face;
	/** Index into tiles.levels. */
	level: number;
	row: number;
	col: number;
	/** Face coordinates of the tile's content: left/right (a) and top/bottom (b). */
	a0: number;
	a1: number;
	b0: number;
	b1: number;
	/** Content size in px (edge tiles can be smaller than tileSize). */
	w: number;
	h: number;
}

/** All tiles of one level, row by row per face. */
export function levelTiles(tiles: PanoTiles, level: number): Tile[] {
	const size = tiles.levels[level];
	const n = Math.ceil(size / tiles.tileSize);
	const out: Tile[] = [];
	for (const face of FACES) {
		for (let row = 0; row < n; row++) {
			for (let col = 0; col < n; col++) {
				const x = col * tiles.tileSize;
				const y = row * tiles.tileSize;
				const w = Math.min(tiles.tileSize, size - x);
				const h = Math.min(tiles.tileSize, size - y);
				out.push({
					url: `${tiles.path}/${size}/${face}-${row}-${col}.${tiles.format}`,
					face,
					level,
					row,
					col,
					a0: (2 * x) / size - 1,
					a1: (2 * (x + w)) / size - 1,
					b0: 1 - (2 * y) / size,
					b1: 1 - (2 * (y + h)) / size,
					w,
					h
				});
			}
		}
	}
	return out;
}

/**
 * A quad covering face rectangle a0..a1 × b0..b1 (b0 top) at `radius`, textured with
 * uv rectangle u0..u1 × v0..v1 (v0 = image top row: textures are uploaded without a flip).
 * Faces are planar, so perspective-correct interpolation of uv on the quad is exact.
 */
export function quad(
	face: Face,
	[a0, a1, b0, b1]: [number, number, number, number],
	[u0, u1, v0, v1]: [number, number, number, number],
	radius: number,
	into?: { positions: number[]; uvs: number[]; index: number[] }
) {
	const target = into ?? { positions: [], uvs: [], index: [] };
	const base = target.positions.length / 3;
	const p = new THREE.Vector3();
	for (const [a, b, u, v] of [
		[a0, b0, u0, v0],
		[a1, b0, u1, v0],
		[a0, b1, u0, v1],
		[a1, b1, u1, v1]
	]) {
		facePoint(face, a, b, radius, p);
		target.positions.push(p.x, p.y, p.z);
		target.uvs.push(u, v);
	}
	target.index.push(base, base + 2, base + 1, base + 2, base + 3, base + 1);
	return target;
}

export function toGeometry({ positions, uvs, index }: { positions: number[]; uvs: number[]; index: number[] }) {
	const g = new THREE.BufferGeometry();
	g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
	g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
	g.setIndex(index);
	g.computeBoundingSphere();
	return g;
}

/** Geometry of one tile: its content area, skipping the bleed border in the texture. */
export function tileGeometry(tile: Tile, bleed: number, radius: number) {
	const tw = tile.w + 2 * bleed;
	const th = tile.h + 2 * bleed;
	return toGeometry(
		quad(
			tile.face,
			[tile.a0, tile.a1, tile.b0, tile.b1],
			[bleed / tw, (bleed + tile.w) / tw, bleed / th, (bleed + tile.h) / th],
			radius
		)
	);
}

/** The whole cube textured from the preview strip (faces side by side in FACES order). */
export function previewGeometry(size: number, bleed: number, radius: number) {
	const cell = size + 2 * bleed;
	const width = cell * FACES.length;
	const target = { positions: [] as number[], uvs: [] as number[], index: [] as number[] };
	FACES.forEach((face, i) => {
		const x = i * cell + bleed;
		quad(face, [-1, 1, 1, -1], [x / width, (x + size) / width, bleed / cell, (bleed + size) / cell], radius, target);
	});
	return toGeometry(target);
}

/** Bounding box of a tile on the unit cube, for frustum tests from the origin. */
export function tileBox(tile: Tile) {
	const box = new THREE.Box3();
	const p = new THREE.Vector3();
	for (const [a, b] of [
		[tile.a0, tile.b0],
		[tile.a1, tile.b0],
		[tile.a0, tile.b1],
		[tile.a1, tile.b1]
	])
		box.expandByPoint(facePoint(tile.face, a, b, 1, p));
	return box;
}

/** Unit direction through the middle of a tile. */
export function tileCentre(tile: Tile) {
	return facePoint(tile.face, (tile.a0 + tile.a1) / 2, (tile.b0 + tile.b1) / 2).normalize();
}
