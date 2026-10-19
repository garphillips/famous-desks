import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { HotspotItem, ItemPatch } from '$lib/types';
import { quad, toGeometry } from './cube';
import { ROOM_TO_VIEWER, prefersReducedMotion, toViewerSpace, type Overlay, type PanoViewer } from './PanoViewer';

/**
 * Featured books on a shelf (HotspotItem): picking them in the panorama and flying one out.
 *
 * Each book is a box in its own axes (Blender's: x thickness with the front cover at +x,
 * y depth with the spine at -y, z up from the middle of its bottom), placed in viewer space
 * relative to the viewpoint, so it lines up with the rendered book in the panorama.
 *
 * Flying out: the 3D book fades in exactly over the panorama's book while a patch of the
 * panorama rendered without it fades in behind (the empty slot), slides forward out of the
 * shelf, then turns its cover to the camera and settles beside the info panel. Returning
 * plays the same timeline backwards, so both ends match exactly.
 */

const FLY_MS = 1150;
const SLIDE_END = 0.3;
const FADE_END = 0.12;
/** Turn of the book at rest, so the spine shows next to the cover. */
const REST_TURN = THREE.MathUtils.degToRad(38);
const REST_TILT = THREE.MathUtils.degToRad(4);
/** Patches sit in front of every tile layer (tile cubes are 4.0-4.5). */
const PATCH_RADIUS = 3.8;
const PATCH_FEATHER_PX = 16;
/** How much the room dims behind a book at rest. */
const DIM = 0.5;

const smootherstep = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const clamp01 = (t: number) => Math.min(1, Math.max(0, t));

/** Where the info panel sits: on the right (desktop) or a sheet at the bottom (phone), and the share of the screen it covers. */
export interface Panel {
	side: 'right' | 'bottom';
	fraction: number;
}

interface Pose {
	position: THREE.Vector3;
	quaternion: THREE.Quaternion;
}

interface Book {
	item: HotspotItem;
	/** Shelf pose in viewer space. */
	home: Pose;
	/** Viewer space -> book axes, for picking. */
	inverse: THREE.Matrix4;
	box: THREE.Box3;
}

interface Flight {
	book: Book;
	group: THREE.Group;
	materials: THREE.Material[];
	patches: THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>[];
	/** Darkens the room behind the book while it is out. */
	dim: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
	rest: Pose;
	/** 0 on the shelf, 1 at rest by the panel. */
	t: number;
	from: number;
	to: number;
	start: number | null;
	done: (() => void) | null;
}

const patchVertex = /* glsl */ `
	varying vec2 vUv;
	void main() {
		vUv = uv;
		gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	}
`;

const patchFragment = /* glsl */ `
	uniform sampler2D map;
	uniform float opacity;
	/** Feather width in uv per edge: left, right, top, bottom (0 where the patch meets a face edge). */
	uniform vec4 feather;
	varying vec2 vUv;
	float edge(float d, float w) { return w > 0.0 ? smoothstep(0.0, w, d) : 1.0; }
	void main() {
		float a = edge(vUv.x, feather.x) * edge(1.0 - vUv.x, feather.y) * edge(vUv.y, feather.z) * edge(1.0 - vUv.y, feather.w);
		gl_FragColor = vec4(texture2D(map, vUv).rgb, opacity * a);
		#include <colorspace_fragment>
	}
`;

/** Paper edges: fine lines, one per few pages, running along v. */
function pageEdgeTexture(lines: 'u' | 'v' = 'u') {
	const canvas = document.createElement('canvas');
	canvas.width = lines === 'u' ? 256 : 1024;
	canvas.height = lines === 'u' ? 1024 : 256;
	const ctx = canvas.getContext('2d')!;
	ctx.fillStyle = '#e4dccb';
	ctx.fillRect(0, 0, canvas.width, canvas.height);
	let seed = 7;
	const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
	const n = lines === 'u' ? canvas.width : canvas.height;
	for (let i = 0; i < n; i += 1.6) {
		const shade = Math.round(150 + random() * 60);
		ctx.fillStyle = `rgba(${shade},${shade - 6},${shade - 16},${0.25 + random() * 0.3})`;
		if (lines === 'u') ctx.fillRect(i, 0, 0.7, canvas.height);
		else ctx.fillRect(0, i, canvas.width, 0.7);
	}
	const texture = new THREE.CanvasTexture(canvas);
	texture.colorSpace = THREE.SRGBColorSpace;
	texture.anisotropy = 8;
	return texture;
}

/** A quad from four corners (top-left, top-right, bottom-left, bottom-right), uv 0..1 with v up. */
function face(tl: number[], tr: number[], bl: number[], br: number[]) {
	const g = new THREE.BufferGeometry();
	g.setAttribute('position', new THREE.Float32BufferAttribute([...tl, ...tr, ...bl, ...br], 3));
	g.setAttribute('uv', new THREE.Float32BufferAttribute([0, 1, 1, 1, 0, 0, 1, 0], 2));
	g.setIndex([0, 2, 1, 2, 3, 1]);
	g.computeVertexNormals();
	return g;
}

export class ShelfItems implements Overlay {
	/** The empty slot and the dimmed room, then the book on top (see Overlay). */
	private backdrop = new THREE.Scene();
	private scene = new THREE.Scene();
	scenes = [this.backdrop, this.scene];
	private environment: THREE.Texture;
	private books: Book[];
	private loader = new THREE.TextureLoader();
	private flight: Flight | null = null;
	private key: THREE.DirectionalLight;

	constructor(
		private viewer: PanoViewer,
		items: HotspotItem[],
		private viewpoint: { slug: string; position: [number, number, number] },
		private url: (path: string) => string
	) {
		this.books = items.map((item) => {
			const [t, h, d] = item.size;
			const [w, x, y, z] = item.rotation;
			const room = new THREE.Matrix4().makeRotationFromQuaternion(new THREE.Quaternion(x, y, z, w));
			const quaternion = new THREE.Quaternion().setFromRotationMatrix(ROOM_TO_VIEWER.clone().multiply(room));
			const position = toViewerSpace(item.position, viewpoint.position);
			const matrix = new THREE.Matrix4().compose(position, quaternion, new THREE.Vector3(1, 1, 1));
			return {
				item,
				home: { position, quaternion },
				inverse: matrix.clone().invert(),
				box: new THREE.Box3(new THREE.Vector3(-t / 2, -d / 2, 0), new THREE.Vector3(t / 2, d / 2, h))
			};
		});
		// soft studio light: a room environment for reflections and fill, plus a warm key
		// from above the camera's left, so the cover reads bright against the dimmed room
		const pmrem = new THREE.PMREMGenerator(viewer.gl);
		this.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
		pmrem.dispose();
		this.scene.environment = this.environment;
		this.scene.environmentIntensity = 0.45;
		this.scene.add(new THREE.HemisphereLight(0xfff6ea, 0x40382c, 0.7));
		this.key = new THREE.DirectionalLight(0xfff1de, 1.9);
		this.scene.add(this.key, this.key.target);
	}

	/** The book whose shelf box the ray from the viewpoint along `dir` hits first. */
	pick(dir: THREE.Vector3): HotspotItem | null {
		let best: { item: HotspotItem; d: number } | null = null;
		const hit = new THREE.Vector3();
		for (const book of this.books) {
			const ray = new THREE.Ray(new THREE.Vector3(), dir.clone()).applyMatrix4(book.inverse);
			if (!ray.intersectBox(book.box, hit)) continue;
			const d = hit.length();
			if (!best || d < best.d) best = { item: book.item, d };
		}
		return best?.item ?? null;
	}

	/** Screen corners of a book's spine (CSS px), for its highlight; null when off screen. */
	outline(slug: string) {
		const book = this.books.find((b) => b.item.slug === slug);
		if (!book || this.flight?.book === book) return null;
		const [t, h, d] = book.item.size;
		const m = new THREE.Matrix4().compose(book.home.position, book.home.quaternion, new THREE.Vector3(1, 1, 1));
		const pts = [
			[-t / 2, -d / 2, h],
			[t / 2, -d / 2, h],
			[t / 2, -d / 2, 0],
			[-t / 2, -d / 2, 0]
		].map(([x, y, z]) => this.viewer.projectPoint(new THREE.Vector3(x, y, z).applyMatrix4(m)));
		return pts.every((p) => p.visible) ? pts : null;
	}

	get flying() {
		return this.flight?.book.item ?? null;
	}

	/**
	 * Flies a book off the shelf to rest beside a panel. `panel` is the screen area to keep
	 * clear: 'right' (desktop, panel on the right) or 'bottom' (phone, sheet at the bottom).
	 */
	fly(slug: string, panel: Panel) {
		const book = this.books.find((b) => b.item.slug === slug);
		if (!book) return Promise.resolve();
		if (this.flight) this.land();
		const { group, materials } = this.build(book.item);
		const patches = this.patchMeshes(book.item.patches);
		// between the panorama (and patches, further out) and the book
		const dim = new THREE.Mesh(
			new THREE.SphereGeometry(3, 16, 8),
			new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0, side: THREE.BackSide, depthTest: false, depthWrite: false })
		);
		dim.renderOrder = 0.5;
		dim.frustumCulled = false;
		this.scene.add(group);
		this.backdrop.add(dim);
		for (const p of patches) this.backdrop.add(p);
		this.flight = {
			book,
			group,
			materials,
			patches,
			dim,
			rest: this.restPose(book.item, panel),
			t: 0,
			from: 0,
			to: 1,
			start: null,
			done: null
		};
		return this.run(1);
	}

	/** Re-aims the resting book after the view or window changes. */
	relayout(panel: Panel) {
		if (!this.flight) return;
		this.flight.rest = this.restPose(this.flight.book.item, panel);
		this.viewer.requestFrame();
	}

	/** Sends the flying book back to its slot. */
	async putBack() {
		if (!this.flight) return;
		await this.run(0);
		this.land();
	}

	update(now: number) {
		const f = this.flight;
		if (!f) return false;
		let animating = false;
		if (f.from !== f.to) {
			f.start ??= now;
			const span = Math.abs(f.to - f.from) * (prefersReducedMotion() ? 200 : FLY_MS);
			const k = clamp01((now - f.start) / span);
			f.t = THREE.MathUtils.lerp(f.from, f.to, k);
			animating = true;
			if (k >= 1) {
				f.from = f.to;
				const done = f.done;
				f.done = null;
				done?.();
			}
		}
		this.pose(f, now);
		// at rest the book breathes a little, so keep drawing
		return animating || f.t === 1;
	}

	dispose() {
		this.land();
		this.environment.dispose();
	}

	private run(to: number) {
		const f = this.flight!;
		f.done?.();
		f.from = f.t;
		f.to = to;
		f.start = null;
		this.viewer.requestFrame();
		return new Promise<void>((resolve) => (f.done = resolve));
	}

	private land() {
		const f = this.flight;
		if (!f) return;
		this.scene.remove(f.group);
		f.group.traverse((o) => {
			if (o instanceof THREE.Mesh) o.geometry.dispose();
		});
		for (const m of f.materials) m.dispose();
		this.backdrop.remove(f.dim);
		f.dim.geometry.dispose();
		f.dim.material.dispose();
		for (const p of f.patches) {
			this.backdrop.remove(p);
			p.geometry.dispose();
			p.material.uniforms.map.value?.dispose();
			p.material.dispose();
		}
		f.done?.();
		this.flight = null;
		this.viewer.requestFrame();
	}

	private pose(f: Flight, now: number) {
		const { home } = f.book;
		const { rest } = f;
		const [, h, d] = f.book.item.size;
		const t = f.t;
		const out = new THREE.Vector3(0, -1, 0).applyQuaternion(home.quaternion);
		const slid = home.position.clone().addScaledVector(out, d * 0.8);
		const position = new THREE.Vector3();
		const quaternion = new THREE.Quaternion();
		if (t <= SLIDE_END) {
			position.lerpVectors(home.position, slid, easeOut(t / SLIDE_END));
			quaternion.copy(home.quaternion);
		} else {
			const e = smootherstep((t - SLIDE_END) / (1 - SLIDE_END));
			position.lerpVectors(slid, rest.position, e);
			// a little lift on the way, so it arcs rather than slides
			position.y += Math.sin(Math.PI * e) * h * 0.25;
			quaternion.slerpQuaternions(home.quaternion, rest.quaternion, e);
		}
		if (t === 1 && !prefersReducedMotion()) {
			const s = now / 1000;
			position.y += Math.sin(s * 1.3) * 0.002;
			quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.sin(s * 0.7) * 0.03));
		}
		f.group.position.copy(position);
		f.group.quaternion.copy(quaternion);
		const cam = this.viewer.view;
		this.key.position.copy(position).add(
			new THREE.Vector3(-0.6, 0.9, 0.8).applyQuaternion(cam.quaternion)
		);
		this.key.target.position.copy(position);
		this.key.target.updateMatrixWorld();
		const fade = clamp01(t / FADE_END);
		for (const m of f.materials) {
			m.opacity = fade;
			m.transparent = fade < 1;
			m.depthWrite = fade >= 1;
		}
		for (const p of f.patches) p.material.uniforms.opacity.value = fade;
		f.dim.material.opacity = DIM * smootherstep(clamp01((t - SLIDE_END) / (1 - SLIDE_END)));
	}

	/** Beside the panel, cover to the camera, turned a little to show the spine. */
	private restPose(item: HotspotItem, panel: Panel): Pose {
		const camera = this.viewer.view;
		camera.updateMatrixWorld();
		const [t, h, d] = item.size;
		const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
		const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
		const forward = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 2).negate();
		const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
		const tanH = tanV * camera.aspect;
		// the free area beside the panel, as a fraction of the screen, and its centre in NDC
		const rest = Math.max(0.3, 1 - panel.fraction);
		const free =
			panel.side === 'right' ? { w: rest, h: 1, x: rest - 1, y: 0.02 } : { w: 1, h: rest, x: 0, y: 1 - rest };
		const width = d * Math.cos(REST_TURN) + t * Math.abs(Math.sin(REST_TURN));
		// as large as fits: 58% of the free height, 70% of the free width
		const byHeight = h / (0.58 * free.h * 2 * tanV);
		const byWidth = width / (0.7 * free.w * 2 * tanH);
		const dist = Math.max(byHeight, byWidth, 0.3);
		const centre = forward
			.clone()
			.multiplyScalar(dist)
			.addScaledVector(right, free.x * dist * tanH)
			.addScaledVector(up, free.y * dist * tanV);
		// book x (front) towards the camera, y to screen right, z up
		const basis = new THREE.Matrix4().makeBasis(forward.clone().negate(), right, up);
		const quaternion = new THREE.Quaternion()
			.setFromRotationMatrix(basis)
			.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), REST_TURN))
			.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -REST_TILT));
		const position = centre.sub(new THREE.Vector3(0, 0, h / 2).applyQuaternion(quaternion));
		return { position, quaternion };
	}

	private texture(path: string) {
		const t = this.loader.load(this.url(path), () => this.viewer.requestFrame());
		t.colorSpace = THREE.SRGBColorSpace;
		t.anisotropy = 8;
		return t;
	}

	private build(item: HotspotItem) {
		const [t, h, d] = item.size;
		const x0 = -t / 2, x1 = t / 2, y0 = -d / 2, y1 = d / 2;
		// pages sit a touch inside the covers on a hardback
		const inset = item.kind === 'hardback' ? 0.0025 : 0.0006;
		const board = item.kind === 'hardback' ? 0.0024 : 0.0008;
		const common = { roughness: 0.55, metalness: 0, transparent: true, opacity: 0 };
		// covers double-sided: their backs are the insides of the boards, beside the page block
		const cover = new THREE.MeshStandardMaterial({ ...common, map: this.texture(item.cover), roughness: 0.42, side: THREE.DoubleSide });
		const spine = new THREE.MeshStandardMaterial({ ...common, map: this.texture(item.spine), roughness: 0.45 });
		const back = new THREE.MeshStandardMaterial({
			...common,
			color: new THREE.Color(item.coverColour).multiplyScalar(0.85),
			side: THREE.DoubleSide
		});
		const edgeU = new THREE.MeshStandardMaterial({ ...common, map: pageEdgeTexture(), roughness: 0.85 });
		const boardEdge = new THREE.MeshStandardMaterial({ ...common, color: new THREE.Color(item.spineColour) });
		const group = new THREE.Group();
		const add = (g: THREE.BufferGeometry, m: THREE.Material) => group.add(new THREE.Mesh(g, m));
		// covers and spine: front (+x, seen from +x: right = +y), back (-x), spine (-y, right = +x)
		add(face([x1, y0, h], [x1, y1, h], [x1, y0, 0], [x1, y1, 0]), cover);
		add(face([x0, y1, h], [x0, y0, h], [x0, y1, 0], [x0, y0, 0]), back);
		add(face([x0, y0, h], [x1, y0, h], [x0, y0, 0], [x1, y0, 0]), spine);
		// page block: fore-edge (+y), top (+z) and bottom (-z), inset between the boards
		const px0 = x0 + board, px1 = x1 - board, py1 = y1 - inset;
		add(face([px1, py1, h - inset], [px0, py1, h - inset], [px1, py1, inset], [px0, py1, inset]), edgeU);
		add(face([px0, py1, h - inset], [px1, py1, h - inset], [px0, y0, h - inset], [px1, y0, h - inset]), edgeU);
		add(face([px0, y0, inset], [px1, y0, inset], [px0, py1, inset], [px1, py1, inset]), edgeU);
		// the boards' thin edges around the page block
		for (const x of [x0, px1]) {
			const xb = x + board;
			add(face([xb, y1, h], [x, y1, h], [xb, y1, 0], [x, y1, 0]), boardEdge);
			add(face([x, y1, h], [xb, y1, h], [x, y0, h], [xb, y0, h]), boardEdge);
			add(face([x, y0, 0], [xb, y0, 0], [x, y1, 0], [xb, y1, 0]), boardEdge);
		}
		for (const m of group.children) (m as THREE.Mesh).renderOrder = 1;
		return { group, materials: [cover, spine, back, edgeU, boardEdge] };
	}

	private patchMeshes(patches: ItemPatch[]) {
		return patches
			.filter((p) => p.viewpoint === this.viewpoint.slug)
			.map((p) => {
				const [x, y, w, h] = p.rect;
				const n = p.faceSize;
				const a0 = (2 * x) / n - 1, a1 = (2 * (x + w)) / n - 1;
				const b0 = 1 - (2 * y) / n, b1 = 1 - (2 * (y + h)) / n;
				const map = this.texture(p.image);
				map.flipY = false;
				const fx = PATCH_FEATHER_PX / w, fy = PATCH_FEATHER_PX / h;
				const material = new THREE.ShaderMaterial({
					uniforms: {
						map: { value: map },
						opacity: { value: 0 },
						feather: {
							value: new THREE.Vector4(x > 0 ? fx : 0, x + w < n ? fx : 0, y > 0 ? fy : 0, y + h < n ? fy : 0)
						}
					},
					vertexShader: patchVertex,
					fragmentShader: patchFragment,
					transparent: true,
					depthTest: false,
					depthWrite: false
				});
				const mesh = new THREE.Mesh(toGeometry(quad(p.face, [a0, a1, b0, b1], [0, 1, 0, 1], PATCH_RADIUS)), material);
				mesh.renderOrder = 0;
				mesh.frustumCulled = false;
				return mesh;
			});
	}
}
