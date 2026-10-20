import * as THREE from 'three';
import type { PanoTiles } from '$lib/types';
import { levelTiles, previewGeometry, tileBox, tileCentre, tileGeometry, type Tile } from './cube';
import { TextureStore, type TextureOptions } from './textures';

/**
 * Renders a panorama and handles look-around input.
 *
 * Angles follow the export convention: yaw 0 = north (image centre), clockwise,
 * so east = 90. In viewer space north is +X, east is +Z and up is +Y (direction()).
 *
 * A panorama is either a cube-face tile pyramid (sharp, streamed by level of detail) or,
 * as a fallback, one equirectangular image:
 * - Tiles: a low-res preview of all six faces paints first, then the tiles in view at
 *   the level matching the screen's pixel density load, nearest the view centre first
 *   (plus the coarsest level of the faces in view, to refine quickly). Finer levels sit on
 *   slightly smaller cubes, and each layer draws with depth testing, so every pixel shows
 *   the finest loaded tile and is blended once (crossfades stay correct). Tiles carry a
 *   1 px border from their neighbours and are trilinear-mipmapped with anisotropy, so
 *   there are no seams and no shimmer.
 * - Equirect: an inside-out box whose shader samples u = atan2(z, x) / 2π + 0.5, with
 *   explicit gradients so mipmaps don't break where u wraps.
 *
 * Two layers (current and incoming) let viewpoint changes crossfade, each drawn
 * with its own field of view so the old view can zoom in while the new one settles.
 * Transitions crossfade as soon as the incoming preview is ready, then refine.
 */

export interface PanoSource {
	/** The equirectangular panorama: the fallback, and the panorama's identity. */
	url: string;
	/** Tile pyramid, with `path` and `preview` as URLs. */
	tiles?: PanoTiles;
}

export const MIN_FOV = 30;
const MAX_FOV = 90;
const MAX_PITCH = 85;
/** A yaw range keeps the frame's corners off the hidden wall up to this far above and below the horizon. */
const WALL_BAND = 50;
const RANGE_MARGIN = 2;
const SMALL_SCREEN =
	typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse), (max-width: 760px)').matches;
/** GPU memory for panorama textures: a 512 px tile is ~1.4 MB with mipmaps, a 4096 equirect ~45 MB. */
const TEXTURE_BUDGET = (SMALL_SCREEN ? 128 : 384) * 2 ** 20;
/** A level is fine enough once it has this fraction of the screen's pixels per degree. */
const LOD_BIAS = 0.9;
/** Tiles are requested for a slightly wider view than the screen, so turning finds them ready. */
const PREFETCH_FOV = 1.2;
const DRAG_THRESHOLD = 6;
const INERTIA_DECAY_MS = 260;
const INERTIA_MAX_SPEED = 0.5;
const INERTIA_MIN_SPEED = 0.003;

const TURN_MS_PER_DEGREE = 1.6;
const TURN_MAX_MS = 300;
const STEP_MS = 580;
const REDUCED_MS = 220;
const STEP_ZOOM_OUT = 0.6;
const STEP_ZOOM_IN = 0.8;
/** How long a transition waits for a (usually prefetched) panorama before turning without it. */
const READY_WAIT_MS = 120;

/** Cube half-sizes: the preview/equirect at the back, finer tile levels in front of coarser ones. */
const BACKGROUND_RADIUS = 5;
const tileRadius = (level: number) => 4.5 - 0.1 * level;

const PREVIEW: TextureOptions = { mipmaps: false };
const TILE: TextureOptions = { mipmaps: true };
const EQUIRECT: TextureOptions = { mipmaps: true, wrap: true };

export interface ScreenPoint {
	x: number;
	y: number;
	visible: boolean;
}

/**
 * Extra 3D drawn over the panorama with the same camera (e.g. a book pulled off a shelf).
 * Positions are viewer space relative to the viewpoint, in metres: see toViewerSpace().
 * Scenes draw in order, each with a fresh depth buffer, so a later scene is always in
 * front of an earlier one (e.g. a backdrop, then the object over it).
 * update(now) runs every frame; returning true keeps frames coming (it is animating).
 */
export interface Overlay {
	scenes: THREE.Scene[];
	update?: (now: number) => boolean;
}

/** Room axes (x east, y north, z up) to viewer axes (+X north, +Y up, +Z east). */
export const ROOM_TO_VIEWER = new THREE.Matrix4().set(0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1);

/** A room-space point relative to the viewpoint at `origin`, in viewer space. */
export function toViewerSpace([x, y, z]: number[], origin: number[], out = new THREE.Vector3()) {
	return out.set(y - origin[1], z - origin[2], x - origin[0]);
}

export function direction(yaw: number, pitch: number) {
	const y = THREE.MathUtils.degToRad(yaw);
	const p = THREE.MathUtils.degToRad(pitch);
	return new THREE.Vector3(Math.cos(p) * Math.cos(y), Math.sin(p), Math.cos(p) * Math.sin(y));
}

export const prefersReducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

const equirectVertexShader = /* glsl */ `
	varying vec3 vDir;
	void main() {
		vDir = position;
		gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	}
`;

const equirectFragmentShader = /* glsl */ `
	#include <common>
	uniform sampler2D map;
	uniform float opacity;
	varying vec3 vDir;
	void main() {
		vec3 dir = normalize(vDir);
		// v = 0 is the top row (textures are uploaded unflipped)
		vec2 uv = vec2(atan(dir.z, dir.x) * RECIPROCAL_PI2 + 0.5, 0.5 - asin(clamp(dir.y, -1.0, 1.0)) * RECIPROCAL_PI);
		// Gradients from a copy of u that wraps elsewhere, wherever u itself jumps from 1 to 0,
		// so the mip level stays right along the seam (behind you, due south).
		float uw = fract(uv.x + 0.5);
		float dux = dFdx(uv.x), duy = dFdy(uv.x), dwx = dFdx(uw), dwy = dFdy(uw);
		vec2 gx = vec2(abs(dux) < abs(dwx) ? dux : dwx, dFdx(uv.y));
		vec2 gy = vec2(abs(duy) < abs(dwy) ? duy : dwy, dFdy(uv.y));
		gl_FragColor = vec4(textureGrad(map, uv, gx, gy).rgb, opacity);
		#include <colorspace_fragment>
	}
`;

const tileVertexShader = /* glsl */ `
	varying vec2 vUv;
	void main() {
		vUv = uv;
		gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	}
`;

const tileFragmentShader = /* glsl */ `
	uniform sampler2D map;
	uniform float opacity;
	varying vec2 vUv;
	void main() {
		gl_FragColor = vec4(texture2D(map, vUv).rgb, opacity);
		#include <colorspace_fragment>
	}
`;

interface Layer {
	group: THREE.Group;
	source: PanoSource | null;
	/** 'tiles' draws the preview + tiles; 'equirect' the fallback image. */
	mode: 'tiles' | 'equirect';
	/** Url of the background texture (preview or equirect). */
	background: string | null;
	backgroundMesh: THREE.Mesh | null;
	/** Shared by all of the layer's materials. */
	opacity: { value: number };
	/** Field of view multiplier while transitioning. */
	zoom: number;
	/** Tile url -> mesh, for every loaded tile added so far. */
	tiles: Map<string, THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>>;
	/** Tiles the layer's current view wants, in priority order. */
	wanted: string[];
}

interface Background {
	mode: Layer['mode'];
	url: string;
	texture: THREE.Texture;
}

interface Animation {
	duration: number;
	start: number | null;
	step: (t: number) => void;
	done: () => void;
}

interface TrackedPointer {
	x: number;
	y: number;
	startX: number;
	startY: number;
	/** False while a pointer that began on a marker hasn't moved far enough to count as a drag. */
	dragging: boolean;
}

const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const easeIn = (t: number) => t * t;
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const smoothstep = (a: number, b: number, t: number) => {
	const x = THREE.MathUtils.clamp((t - a) / (b - a), 0, 1);
	return x * x * (3 - 2 * x);
};
const wrap = (deg: number) => ((((deg + 180) % 360) + 360) % 360) - 180;
/** Between two fields of view at a steady rate of magnification (straight lerp rushes the end). */
const lerpFov = (a: number, b: number, e: number) => {
	const ta = Math.tan(THREE.MathUtils.degToRad(a) / 2);
	const tb = Math.tan(THREE.MathUtils.degToRad(b) / 2);
	return THREE.MathUtils.radToDeg(2 * Math.atan(ta * (tb / ta) ** e));
};
/** Time to zoom between two fields of view: about 700 ms per doubling of magnification. */
const zoomDuration = (a: number, b: number) => {
	const ratio = Math.tan(THREE.MathUtils.degToRad(a) / 2) / Math.tan(THREE.MathUtils.degToRad(b) / 2);
	return Math.min(1600, Math.abs(Math.log2(ratio)) * 700);
};
const wait = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));
const toSource = (source: PanoSource | string): PanoSource => (typeof source === 'string' ? { url: source } : source);

interface TileInfo {
	tile: Tile;
	box: THREE.Box3;
	centre: THREE.Vector3;
}

export class PanoViewer {
	yaw = 0;
	pitch = 0;
	fov = 75;

	private renderer: THREE.WebGLRenderer;
	private scene = new THREE.Scene();
	private camera: THREE.PerspectiveCamera;
	private cullCamera = new THREE.PerspectiveCamera();
	private frustum = new THREE.Frustum();
	private box = new THREE.BoxGeometry(2 * BACKGROUND_RADIUS, 2 * BACKGROUND_RADIUS, 2 * BACKGROUND_RADIUS);
	private store: TextureStore;
	/** Per tile pyramid (by path) and level: tiles with their culling boxes. */
	private tileInfo = new Map<string, TileInfo[][]>();
	/** Shared geometries: tile quads and preview cubes. */
	private geometries = new Map<string, THREE.BufferGeometry>();
	/** Panoramas whose tiles turned out to be missing: shown from the equirect instead. */
	private broken = new Set<string>();
	private current: Layer;
	private incoming: Layer;
	/** Panorama a pending load or transition is heading to; never evicted. */
	private target: PanoSource | null = null;
	private token = 0;
	private disposed = false;
	private animation: Animation | null = null;
	private dirty = true;
	private frame = 0;
	private lastFrame = 0;
	private pointers = new Map<number, TrackedPointer>();
	private pinch: { distance: number; fov: number } | null = null;
	private pinched = false;
	private velocity = { yaw: 0, pitch: 0, time: 0 };
	private inertia: { yaw: number; pitch: number } | null = null;
	private resizeObserver: ResizeObserver;
	private onChange: () => void;
	private onInteract: () => void;
	private onTap: (e: PointerEvent) => void;
	private overlays = new Set<Overlay>();

	constructor(
		private canvas: HTMLCanvasElement,
		{
			onChange,
			onInteract = () => {},
			onTap = () => {}
		}: { onChange: () => void; onInteract?: () => void; onTap?: (e: PointerEvent) => void }
	) {
		this.onChange = onChange;
		this.onInteract = onInteract;
		this.onTap = onTap;
		this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		this.renderer.outputColorSpace = THREE.SRGBColorSpace;
		this.renderer.autoClear = false;
		this.camera = new THREE.PerspectiveCamera(this.fov, 1, 0.1, 100);
		this.store = new TextureStore(
			this.renderer,
			TEXTURE_BUDGET,
			() => this.invalidate(),
			(url) => this.forget(url)
		);
		this.current = this.createLayer();
		this.incoming = this.createLayer();

		canvas.addEventListener('pointerdown', this.onPointerDown);
		window.addEventListener('pointermove', this.onPointerMove);
		window.addEventListener('pointerup', this.onPointerUp);
		window.addEventListener('pointercancel', this.onPointerUp);
		canvas.addEventListener('wheel', this.onWheel, { passive: false });
		canvas.addEventListener('keydown', this.onKeyDown);

		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(canvas);
		this.resize();
		this.frame = requestAnimationFrame(this.loop);
	}

	/** Url (PanoSource.url) of the panorama on screen (after any transition settles). */
	get url() {
		return this.current.source?.url ?? null;
	}

	/** True while a viewpoint transition is running. */
	get busy() {
		return this.target !== null;
	}

	/**
	 * Loads (or reuses) what a panorama needs to appear: its tile preview, or the equirect
	 * when it has no tiles or they're missing.
	 */
	preload(source: PanoSource | string): Promise<Background> {
		const src = toSource(source);
		if (src.tiles && !this.broken.has(src.url)) {
			const url = src.tiles.preview;
			return this.store.load(url, PREVIEW).then(
				(texture): Background => ({ mode: 'tiles', url, texture }),
				(err) => {
					if (this.disposed) throw err;
					console.warn(`No tiles for ${src.url}, using the equirect`, err);
					this.broken.add(src.url);
					return this.preload(src);
				}
			);
		}
		return this.store.load(src.url, EQUIRECT).then((texture): Background => ({ mode: 'equirect', url: src.url, texture }));
	}

	/**
	 * Warms the cache in the background, one panorama at a time: its preview, or
	 * equirect, plus the coarsest tile level (six 512 px tiles), so a step lands sharp-ish
	 * straight away and refines from there.
	 */
	prefetch(sources: (PanoSource | string)[]) {
		const token = this.token;
		const next = (i: number) => {
			if (i >= sources.length || token !== this.token) return;
			const run = () => {
				if (token !== this.token) return;
				// The tiles in view come first.
				if (this.store.busy) return void setTimeout(() => next(i), 300);
				const src = toSource(sources[i]);
				this.preload(src)
					.then((bg) => {
						if (bg.mode !== 'tiles' || token !== this.token) return;
						const coarse = this.tilesOf(src.tiles!, 0).map(({ tile }) => this.store.load(tile.url, TILE));
						return Promise.allSettled(coarse);
					})
					.catch(() => {})
					.then(() => next(i + 1));
			};
			if ('requestIdleCallback' in window) requestIdleCallback(run, { timeout: 1500 });
			else setTimeout(run, 200);
		};
		next(0);
	}

	/** Shows a panorama straight away, no transition. Resolves once its preview is on screen. */
	async setPanorama(source: PanoSource | string) {
		const src = toSource(source);
		this.settle();
		const token = ++this.token;
		this.target = src;
		try {
			const background = await this.preload(src);
			if (token !== this.token) return;
			this.assign(this.current, src, background);
			this.invalidate();
		} finally {
			if (token === this.token) this.target = null;
		}
	}

	/**
	 * Moves to another panorama: turn to `yaw`, zoom in while crossfading, settle.
	 * `pitch` and `fov` (default level, unchanged) are where the view ends up, so a move
	 * can land on a close-up in one motion. With `reduced`, just a quick crossfade at the
	 * current heading. Resolves false if another transition replaced this one.
	 */
	async transitionTo(
		source: PanoSource | string,
		{ yaw, pitch = 0, fov, reduced = false }: { yaw: number; pitch?: number; fov?: number; reduced?: boolean }
	) {
		const src = toSource(source);
		this.settle();
		const token = ++this.token;
		this.target = src;
		this.inertia = null;
		this.pinch = null;
		const background = this.preload(src);
		const toFov = THREE.MathUtils.clamp(fov ?? this.fov, this.minFov, MAX_FOV);
		const to = { yaw: this.clampYaw(yaw, pitch, toFov), pitch, fov: toFov };
		try {
			// A prefetched panorama is ready at once: turn, step and zoom as one motion.
			// Otherwise turn towards it while it loads, then step.
			let bg = await Promise.race([background, wait(READY_WAIT_MS).then(() => null)]);
			if (token !== this.token) return false;
			if (!bg && !reduced) {
				const from = { yaw: this.yaw, pitch: this.pitch };
				const turn = this.turn(from.yaw, to.yaw);
				const ms = Math.min(TURN_MAX_MS, (Math.abs(turn) + Math.abs(from.pitch - pitch)) * TURN_MS_PER_DEGREE);
				await this.animate(ms, (t) => {
					const e = easeInOut(t);
					this.yaw = from.yaw + turn * e;
					this.pitch = THREE.MathUtils.lerp(from.pitch, pitch, e);
				});
				if (token !== this.token) return false;
			}
			bg ??= await background;
			if (token !== this.token) return false;
			this.assign(this.incoming, src, bg);
			if (reduced) {
				await this.animate(REDUCED_MS, (t) => (this.incoming.opacity.value = t));
				if (token !== this.token) return false;
				this.commit();
				return true;
			}
			const from = { yaw: this.yaw, pitch: this.pitch, fov: this.fov };
			const turn = this.turn(from.yaw, to.yaw);
			const turnMs = Math.min(TURN_MAX_MS, (Math.abs(turn) + Math.abs(from.pitch - to.pitch)) * TURN_MS_PER_DEGREE);
			const zoomMs = zoomDuration(from.fov, to.fov);
			const ms = turnMs + Math.max(STEP_MS, zoomMs);
			// the step (crossfade) starts once the turn is mostly done
			const s0 = (turnMs * 0.6) / ms;
			await this.animate(ms, (t) => {
				const e = easeInOut(t);
				this.yaw = from.yaw + turn * e;
				this.pitch = THREE.MathUtils.lerp(from.pitch, to.pitch, e);
				this.fov = lerpFov(from.fov, to.fov, e);
				const s = THREE.MathUtils.clamp((t - s0) / (1 - s0), 0, 1);
				this.current.zoom = THREE.MathUtils.lerp(1, STEP_ZOOM_OUT, easeIn(s));
				this.incoming.opacity.value = smoothstep(0.2, 0.8, s);
				this.incoming.zoom = THREE.MathUtils.lerp(STEP_ZOOM_IN, 1, easeOut(smoothstep(0.2, 1, s)));
			});
			if (token !== this.token) return false;
			this.commit();
			return true;
		} finally {
			if (token === this.token) this.target = null;
		}
	}

	/** Ends any running transition immediately, landing on its destination if it was already showing. */
	settle() {
		const animation = this.animation;
		this.animation = null;
		if (this.incoming.source) this.commit();
		this.current.zoom = 1;
		this.current.opacity.value = 1;
		this.target = null;
		this.token++;
		animation?.done();
		this.invalidate();
	}

	/** Horizontal field of view in degrees. */
	get hfov() {
		const v = THREE.MathUtils.degToRad(this.fov) / 2;
		return THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(v) * this.camera.aspect));
	}

	zoomBy(deltaDegrees: number) {
		if (this.busy) return;
		this.fov = THREE.MathUtils.clamp(this.fov + deltaDegrees, this.minFov, MAX_FOV);
		this.invalidate();
	}

	/** Sets the vertical field of view (degrees, clamped to the zoom range). */
	setFov(fov: number) {
		this.fov = THREE.MathUtils.clamp(fov, this.minFov, MAX_FOV);
		this.invalidate();
	}

	/**
	 * A still of part of the panorama, as a data URL. Renders through the main
	 * canvas (so colour management matches the live view), copies the centre
	 * out, then restores the live view. Uses whatever tiles are already loaded.
	 */
	snapshot(yaw: number, pitch: number, fov: number, width: number, height: number) {
		if (!this.current.source) return '';
		const { width: cw, height: ch } = this.renderer.domElement;
		const cam = this.camera.clone();
		// Fit the requested aspect inside the canvas, then size fov to that crop.
		const scale = Math.min(cw / width, ch / height);
		const crop = { w: width * scale, h: height * scale };
		const cropFovRad = THREE.MathUtils.degToRad(fov) * (ch / crop.h);
		cam.lookAt(direction(yaw, pitch));
		cam.updateMatrixWorld();
		this.renderer.clear();
		this.drawLayer(this.current, cam, THREE.MathUtils.radToDeg(Math.min(cropFovRad, Math.PI * 0.95)), false);
		const out = document.createElement('canvas');
		out.width = width;
		out.height = height;
		out.getContext('2d')!.drawImage(
			this.renderer.domElement,
			(cw - crop.w) / 2,
			(ch - crop.h) / 2,
			crop.w,
			crop.h,
			0,
			0,
			width,
			height
		);
		this.draw();
		return out.toDataURL('image/jpeg', 0.85);
	}

	/**
	 * Turns and zooms to a view over `ms` (by default, longer for a bigger move);
	 * resolves false if something else took over.
	 */
	async zoomTo(yaw: number, pitch: number, fov: number, ms?: number) {
		if (this.busy) return false;
		this.inertia = null;
		const from = { yaw: this.yaw, pitch: this.pitch, fov: this.fov };
		const to = THREE.MathUtils.clamp(fov, this.minFov, MAX_FOV);
		const turn = this.turn(from.yaw, this.clampYaw(yaw, pitch, to));
		const token = this.token;
		ms ??= Math.max(zoomDuration(from.fov, to), Math.min(1400, 500 + (Math.abs(turn) + Math.abs(pitch - from.pitch)) * 4));
		await this.animate(prefersReducedMotion() ? 0 : ms, (t) => {
			const e = easeInOut(t);
			this.yaw = from.yaw + turn * e;
			this.pitch = THREE.MathUtils.lerp(from.pitch, pitch, e);
			this.fov = lerpFov(from.fov, to, e);
		});
		return token === this.token;
	}

	addOverlay(overlay: Overlay) {
		this.overlays.add(overlay);
		this.invalidate();
	}

	removeOverlay(overlay: Overlay) {
		this.overlays.delete(overlay);
		this.invalidate();
	}

	/** Redraw on the next frame (e.g. an overlay changed). */
	requestFrame() {
		this.invalidate();
	}

	/** The live camera: at the origin of viewer space, looking along the view. */
	/** The renderer, e.g. for overlays to prepare environment maps. */
	get gl() {
		return this.renderer;
	}

	get view() {
		return this.camera;
	}

	/** Direction (viewer space, unit) through a point on the canvas (client px). */
	pointerDirection(clientX: number, clientY: number) {
		const r = this.canvas.getBoundingClientRect();
		const ndc = new THREE.Vector3(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1, 0.5);
		return ndc.unproject(this.camera).normalize();
	}

	/** Screen position (CSS px) of a point in viewer space. */
	projectPoint(p: THREE.Vector3): ScreenPoint {
		const forward = this.camera.getWorldDirection(new THREE.Vector3());
		const ndc = p.clone().project(this.camera);
		const { clientWidth: w, clientHeight: h } = this.canvas;
		return {
			x: ((ndc.x + 1) / 2) * w,
			y: ((1 - ndc.y) / 2) * h,
			visible: p.dot(forward) > 0
		};
	}

	/** How far in you can zoom (vertical field of view, degrees): MIN_FOV, or tighter in a close-up whose
	 *  panorama is sharp enough for it (the display, from the bookshelf's 4096 px faces). */
	minFov = MIN_FOV;

	/**
	 * The directions the view may face: [from, to] in degrees, clockwise (e.g. to keep a
	 * wall there are no photos of out of the frame). Dragging, zooming and moves all stay inside.
	 */
	yawRange: [number, number] | null = null;

	/** How far the frame reaches either side of where it faces (degrees), over the band the wall shows in. */
	private reach(pitch: number, fov: number) {
		const tv = Math.tan(THREE.MathUtils.degToRad(fov) / 2);
		const a = tv * this.camera.aspect;
		const p = THREE.MathUtils.degToRad(pitch);
		const band = THREE.MathUtils.degToRad(WALL_BAND);
		// along the frame's side edge (b from -tv to tv): sideways reach and height above the horizon
		const side = (b: number) => Math.atan2(a, Math.cos(p) - b * Math.sin(p));
		const elevation = (b: number) => Math.atan2(Math.sin(p) + b * Math.cos(p), Math.hypot(a, Math.cos(p) - b * Math.sin(p)));
		// the part of the edge inside the band (elevation rises with b), found by halving
		const solve = (target: number) => {
			let lo = -tv;
			let hi = tv;
			if (elevation(lo) >= target) return lo;
			if (elevation(hi) <= target) return hi;
			for (let i = 0; i < 24; i++) {
				const mid = (lo + hi) / 2;
				if (elevation(mid) < target) lo = mid;
				else hi = mid;
			}
			return (lo + hi) / 2;
		};
		const ends = [solve(-band), solve(band)].filter((b) => Math.cos(p) - b * Math.sin(p) > 0);
		const reach = ends.length ? Math.max(...ends.map(side)) : Math.PI / 2;
		return THREE.MathUtils.radToDeg(Math.min(reach, Math.PI / 2));
	}

	/** `yaw` moved just far enough that the frame stays inside the yaw range. */
	private clampYaw(yaw: number, pitch = this.pitch, fov = this.fov) {
		if (!this.yawRange) return wrap(yaw);
		const [from, to] = this.yawRange;
		const r = this.reach(pitch, fov) + RANGE_MARGIN;
		const lo = from + r;
		const hi = to - r;
		if (lo > hi) return wrap((from + to) / 2);
		const y = from + ((((yaw - from) % 360) + 360) % 360);
		if (y < lo) return wrap(lo);
		if (y <= hi) return wrap(y);
		// past the far edge: back to whichever edge is nearer across the hidden side
		return wrap(y - hi < lo + 360 - y ? hi : lo);
	}

	/** The turn from one yaw to another: the short way, unless that would sweep across the hidden side. */
	private turn(from: number, to: number) {
		if (!this.yawRange) return wrap(to - from);
		const start = this.yawRange[0];
		const inside = (y: number) => start + ((((y - start) % 360) + 360) % 360);
		return inside(to) - inside(from);
	}

	lookAt(yaw: number, pitch = 0) {
		this.yaw = this.clampYaw(yaw, pitch);
		this.pitch = pitch;
		this.inertia = null;
		this.invalidate();
	}

	/** Screen position (CSS px) of a yaw/pitch direction. */
	project(yaw: number, pitch: number): ScreenPoint {
		const dir = direction(yaw, pitch);
		const forward = this.camera.getWorldDirection(new THREE.Vector3());
		const ndc = dir.clone().project(this.camera);
		const { clientWidth: w, clientHeight: h } = this.canvas;
		return {
			x: ((ndc.x + 1) / 2) * w,
			y: ((1 - ndc.y) / 2) * h,
			visible: dir.dot(forward) > 0 && Math.abs(ndc.x) <= 1.1 && Math.abs(ndc.y) <= 1.1
		};
	}

	/**
	 * Lets a pointer that went down on an overlay (a hotspot pin) drag the view
	 * once it moves past a small threshold; a tap stays a tap.
	 */
	grab(e: PointerEvent) {
		this.track(e, false);
	}

	dispose() {
		this.disposed = true;
		cancelAnimationFrame(this.frame);
		this.resizeObserver.disconnect();
		this.canvas.removeEventListener('pointerdown', this.onPointerDown);
		window.removeEventListener('pointermove', this.onPointerMove);
		window.removeEventListener('pointerup', this.onPointerUp);
		window.removeEventListener('pointercancel', this.onPointerUp);
		this.canvas.removeEventListener('wheel', this.onWheel);
		this.canvas.removeEventListener('keydown', this.onKeyDown);
		this.token++;
		this.animation = null;
		for (const layer of [this.current, this.incoming]) this.clear(layer);
		this.store.dispose();
		for (const g of this.geometries.values()) g.dispose();
		this.box.dispose();
		this.renderer.dispose();
	}

	private createLayer(): Layer {
		const group = new THREE.Group();
		group.visible = false;
		this.scene.add(group);
		return {
			group,
			source: null,
			mode: 'equirect',
			background: null,
			backgroundMesh: null,
			opacity: { value: 1 },
			zoom: 1,
			tiles: new Map(),
			wanted: []
		};
	}

	private material(map: THREE.Texture, opacity: { value: number }, equirect = false) {
		return new THREE.ShaderMaterial({
			uniforms: { map: { value: map }, opacity },
			vertexShader: equirect ? equirectVertexShader : tileVertexShader,
			fragmentShader: equirect ? equirectFragmentShader : tileFragmentShader,
			side: THREE.DoubleSide,
			transparent: true,
			depthTest: true,
			depthWrite: true
		});
	}

	private geometry(key: string, make: () => THREE.BufferGeometry) {
		let g = this.geometries.get(key);
		if (!g) {
			g = make();
			this.geometries.set(key, g);
		}
		return g;
	}

	/** Removes a layer's meshes (textures stay in the store). */
	private clear(layer: Layer) {
		for (const mesh of layer.tiles.values()) {
			layer.group.remove(mesh);
			mesh.material.dispose();
		}
		layer.tiles.clear();
		if (layer.backgroundMesh) {
			layer.group.remove(layer.backgroundMesh);
			(layer.backgroundMesh.material as THREE.Material).dispose();
			layer.backgroundMesh = null;
		}
		layer.source = null;
		layer.background = null;
		layer.wanted = [];
	}

	private assign(layer: Layer, source: PanoSource | null, background: Background | null) {
		this.clear(layer);
		layer.zoom = 1;
		layer.opacity.value = layer === this.incoming ? 0 : 1;
		if (!source || !background) return;
		layer.source = source;
		layer.mode = background.mode;
		layer.background = background.url;
		let mesh: THREE.Mesh;
		if (background.mode === 'tiles') {
			const { previewSize, bleed } = source.tiles!;
			const geometry = this.geometry(`preview:${previewSize}:${bleed}`, () =>
				previewGeometry(previewSize, bleed, BACKGROUND_RADIUS)
			);
			mesh = new THREE.Mesh(geometry, this.material(background.texture, layer.opacity));
		} else {
			mesh = new THREE.Mesh(this.box, this.material(background.texture, layer.opacity, true));
		}
		mesh.frustumCulled = false;
		mesh.renderOrder = 0;
		layer.backgroundMesh = mesh;
		layer.group.add(mesh);
	}

	/** Swaps a tiled layer to its equirect once its tiles turn out to be missing. */
	private fallBack(layer: Layer) {
		const source = layer.source!;
		if (this.broken.has(source.url)) return;
		this.broken.add(source.url);
		this.preload(source)
			.then((bg) => {
				if (layer.source !== source) return;
				const { zoom, opacity } = { zoom: layer.zoom, opacity: layer.opacity.value };
				this.assign(layer, source, bg);
				layer.zoom = zoom;
				layer.opacity.value = opacity;
				this.invalidate();
			})
			.catch((err) => console.error(`Couldn't load ${source.url}`, err));
	}

	/** A texture was evicted: drop meshes that used it. */
	private forget(url: string) {
		for (const layer of [this.current, this.incoming]) {
			const mesh = layer.tiles.get(url);
			if (!mesh) continue;
			layer.group.remove(mesh);
			mesh.material.dispose();
			layer.tiles.delete(url);
		}
	}

	/** Incoming becomes current; the old textures stay in the cache. */
	private commit() {
		[this.current, this.incoming] = [this.incoming, this.current];
		this.current.zoom = 1;
		this.current.opacity.value = 1;
		this.assign(this.incoming, null, null);
		this.evict();
		this.invalidate();
	}

	private evict() {
		const keep = new Set<string>();
		for (const layer of [this.current, this.incoming]) {
			if (layer.background) keep.add(layer.background);
			for (const url of layer.wanted) keep.add(url);
		}
		const target = this.target;
		if (target) {
			keep.add(target.url);
			if (target.tiles) keep.add(target.tiles.preview);
		}
		this.store.evict(keep);
	}

	private tilesOf(tiles: PanoTiles, level: number) {
		let levels = this.tileInfo.get(tiles.path);
		if (!levels) {
			levels = [];
			this.tileInfo.set(tiles.path, levels);
		}
		return (levels[level] ??= levelTiles(tiles, level).map((tile) => ({
			tile,
			box: tileBox(tile),
			centre: tileCentre(tile)
		})));
	}

	/** Index of the coarsest level with enough pixels per degree for `fov` on this canvas. */
	private levelFor(tiles: PanoTiles, fov: number) {
		// Device pixels per radian at the centre of the screen; a cube face of N px has N / 2
		// per radian at its centre (and more towards its edges).
		const need = this.renderer.domElement.height / 2 / Math.tan(THREE.MathUtils.degToRad(fov) / 2);
		const i = tiles.levels.findIndex((size) => size / 2 >= need * LOD_BIAS);
		return i < 0 ? tiles.levels.length - 1 : i;
	}

	/**
	 * Works out which tiles `layer` needs for `camera` (the target level in view, plus the
	 * coarsest level for the faces in view) and adds meshes for the loaded ones.
	 */
	private updateTiles(layer: Layer, camera: THREE.PerspectiveCamera) {
		const tiles = layer.source?.tiles;
		if (layer.mode !== 'tiles' || !tiles) {
			layer.wanted = [];
			return;
		}
		this.cullCamera.copy(camera);
		this.cullCamera.fov = Math.min(150, camera.fov * PREFETCH_FOV);
		this.cullCamera.updateProjectionMatrix();
		this.frustum.setFromProjectionMatrix(
			new THREE.Matrix4().multiplyMatrices(this.cullCamera.projectionMatrix, this.cullCamera.matrixWorldInverse)
		);
		const forward = camera.getWorldDirection(new THREE.Vector3());
		const target = this.levelFor(tiles, camera.fov);
		const levels = target > 0 ? [0, target] : [0];
		const wanted: string[] = [];
		for (const level of levels) {
			const inView = this.tilesOf(tiles, level).filter((t) => this.frustum.intersectsBox(t.box));
			inView.sort((a, b) => b.centre.dot(forward) - a.centre.dot(forward));
			for (const { tile } of inView) {
				wanted.push(tile.url);
				if (this.store.failed(tile.url)) {
					if (!this.broken.has(layer.source!.url)) console.warn(`Missing tile ${tile.url}, using the equirect`);
					this.fallBack(layer);
					layer.wanted = [];
					return;
				}
				if (layer.tiles.has(tile.url)) continue;
				const texture = this.store.get(tile.url);
				if (!texture) continue;
				const geometry = this.geometry(`${tile.url}`, () =>
					tileGeometry(tile, tiles.bleed, tileRadius(tile.level))
				);
				const mesh = new THREE.Mesh(geometry, this.material(texture, layer.opacity));
				// Finest first: with depth testing, coarser tiles (and the preview) only fill the gaps.
				mesh.renderOrder = -1 - tile.level;
				layer.tiles.set(tile.url, mesh);
				layer.group.add(mesh);
			}
		}
		layer.wanted = wanted;
	}

	/** Runs `step(t)` for t in 0..1 over `duration` ms; resolves early if settled. */
	private animate(duration: number, step: (t: number) => void) {
		if (duration <= 0) {
			step(1);
			return Promise.resolve();
		}
		return new Promise<void>((done) => {
			this.animation = { duration, start: null, step, done };
			this.invalidate();
		});
	}

	private invalidate() {
		this.dirty = true;
	}

	private resize() {
		const { clientWidth: w, clientHeight: h } = this.canvas;
		if (!w || !h) return;
		this.renderer.setSize(w, h, false);
		this.camera.aspect = w / h;
		this.invalidate();
	}

	private loop = (now: number) => {
		this.frame = requestAnimationFrame(this.loop);
		const dt = Math.min(50, now - (this.lastFrame || now));
		this.lastFrame = now;

		const animation = this.animation;
		if (animation) {
			animation.start ??= now;
			const t = Math.min(1, (now - animation.start) / animation.duration);
			animation.step(t);
			this.invalidate();
			if (t >= 1) {
				this.animation = null;
				animation.done();
			}
		}

		if (this.inertia) {
			this.yaw += this.inertia.yaw * dt;
			this.pitch += this.inertia.pitch * dt;
			const decay = Math.exp(-dt / INERTIA_DECAY_MS);
			this.inertia.yaw *= decay;
			this.inertia.pitch *= Math.abs(this.pitch) >= MAX_PITCH ? 0 : decay;
			if (Math.hypot(this.inertia.yaw, this.inertia.pitch) < INERTIA_MIN_SPEED) this.inertia = null;
			this.invalidate();
		}

		for (const overlay of this.overlays) if (overlay.update?.(now)) this.invalidate();

		if (!this.dirty) return;
		this.dirty = false;
		this.pitch = THREE.MathUtils.clamp(this.pitch, -MAX_PITCH, MAX_PITCH);
		this.yaw = wrap(this.yaw);
		// moves aim inside the yaw range themselves; everything else (drag, inertia, keys, zoom) stops at its edge
		if (!this.animation) {
			const yaw = this.clampYaw(this.yaw);
			if (Math.abs(wrap(yaw - this.yaw)) > 1e-6) {
				this.yaw = yaw;
				if (this.inertia) this.inertia.yaw = 0;
			}
		}
		this.camera.fov = this.fov;
		this.camera.updateProjectionMatrix();
		this.camera.lookAt(direction(this.yaw, this.pitch));
		this.camera.updateMatrixWorld();
		this.draw();
		// Current layer's tiles first, then the incoming one's.
		this.store.request([...new Set([...this.current.wanted, ...this.incoming.wanted])], TILE);
		this.evict();
		// For tests and debugging: data-pano="<level wanted>:<tiles loaded>/<tiles wanted>" or "equirect".
		const tiles = this.current.mode === 'tiles' ? this.current.source?.tiles : undefined;
		const loaded = this.current.wanted.filter((url) => this.current.tiles.has(url)).length;
		this.canvas.dataset.pano = tiles
			? `${tiles.levels[this.levelFor(tiles, this.fov)]}:${loaded}/${this.current.wanted.length}`
			: this.current.source
				? this.current.mode
				: 'none';
		this.onChange();
	};

	private draw() {
		this.renderer.clear();
		if (this.current.source) this.drawLayer(this.current, this.camera, this.fov * this.current.zoom);
		if (this.incoming.source && this.incoming.opacity.value > 0)
			this.drawLayer(this.incoming, this.camera, this.fov * this.incoming.zoom);
		for (const overlay of this.overlays) {
			for (const scene of overlay.scenes) {
				this.renderer.clearDepth();
				this.renderer.render(scene, this.camera);
			}
		}
	}

	/**
	 * Draws one layer alone with the given fov, leaving `camera` as it was. Its own depth
	 * buffer keeps finer tiles in front, so each pixel is blended once at the layer's opacity.
	 */
	private drawLayer(layer: Layer, camera: THREE.PerspectiveCamera, fov: number, refine = true) {
		const fov0 = camera.fov;
		camera.fov = fov;
		camera.updateProjectionMatrix();
		if (refine) this.updateTiles(layer, camera);
		this.renderer.clearDepth();
		layer.group.visible = true;
		this.renderer.render(this.scene, camera);
		layer.group.visible = false;
		camera.fov = fov0;
		camera.updateProjectionMatrix();
	}

	/** Degrees of view per CSS pixel, so dragging tracks the pointer at any zoom. */
	private degreesPerPixel() {
		return this.fov / this.canvas.clientHeight;
	}

	private track(e: PointerEvent, dragging: boolean) {
		this.inertia = null;
		this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY, dragging });
		this.velocity = { yaw: 0, pitch: 0, time: e.timeStamp };
		if (dragging) this.capture(e.pointerId);
		if (this.pointers.size === 2) {
			this.pinch = { distance: this.pointerDistance(), fov: this.fov };
			this.pinched = true;
		}
	}

	private capture(pointerId: number) {
		try {
			this.canvas.setPointerCapture(pointerId);
		} catch {
			// Pointer already gone.
		}
		this.onInteract();
	}

	private pointerDistance() {
		const [a, b] = [...this.pointers.values()];
		return Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
	}

	private onPointerDown = (e: PointerEvent) => {
		if (e.pointerType === 'mouse' && e.button !== 0) return;
		this.track(e, true);
	};

	private onPointerMove = (e: PointerEvent) => {
		const p = this.pointers.get(e.pointerId);
		if (!p) return;
		if (e.pointerType === 'mouse' && e.buttons === 0) {
			// Released somewhere we didn't hear about.
			this.pointers.delete(e.pointerId);
			this.pinch = null;
			return;
		}
		if (!p.dragging) {
			if (Math.hypot(e.clientX - p.startX, e.clientY - p.startY) < DRAG_THRESHOLD) return;
			p.dragging = true;
			this.capture(e.pointerId);
		}
		const dx = e.clientX - p.x;
		const dy = e.clientY - p.y;
		p.x = e.clientX;
		p.y = e.clientY;
		if (this.busy) return;

		if (this.pinch && this.pointers.size >= 2) {
			this.fov = THREE.MathUtils.clamp((this.pinch.fov * this.pinch.distance) / this.pointerDistance(), this.minFov, MAX_FOV);
			this.invalidate();
			return;
		}

		const k = this.degreesPerPixel();
		const dYaw = -dx * k;
		const dPitch = dy * k;
		this.yaw += dYaw;
		this.pitch += dPitch;
		const dt = Math.max(8, e.timeStamp - this.velocity.time);
		this.velocity = {
			yaw: 0.8 * (dYaw / dt) + 0.2 * this.velocity.yaw,
			pitch: 0.8 * (dPitch / dt) + 0.2 * this.velocity.pitch,
			time: e.timeStamp
		};
		this.invalidate();
	};

	private onPointerUp = (e: PointerEvent) => {
		const p = this.pointers.get(e.pointerId);
		if (!p) return;
		this.pointers.delete(e.pointerId);
		if (this.canvas.hasPointerCapture(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
		if (this.pointers.size < 2) this.pinch = null;
		if (this.pointers.size > 0) return;

		const moved = Math.hypot(e.clientX - p.startX, e.clientY - p.startY);
		if (e.type === 'pointerup' && !this.pinched && moved < DRAG_THRESHOLD) this.onTap(e);

		const fresh = e.timeStamp - this.velocity.time < 80;
		const speed = Math.hypot(this.velocity.yaw, this.velocity.pitch);
		if (e.type === 'pointerup' && p.dragging && !this.pinched && !this.busy && fresh && speed > 0.02 && !prefersReducedMotion()) {
			const k = Math.min(1, INERTIA_MAX_SPEED / speed);
			this.inertia = { yaw: this.velocity.yaw * k, pitch: this.velocity.pitch * k };
		}
		this.pinched = false;
	};

	private onWheel = (e: WheelEvent) => {
		e.preventDefault();
		this.inertia = null;
		this.zoomBy(e.deltaY * 0.05);
		this.onInteract();
	};

	private onKeyDown = (e: KeyboardEvent) => {
		const step = 5;
		const moves: Record<string, () => void> = {
			ArrowLeft: () => (this.yaw -= step),
			ArrowRight: () => (this.yaw += step),
			ArrowUp: () => (this.pitch += step),
			ArrowDown: () => (this.pitch -= step),
			'+': () => (this.fov = Math.max(this.minFov, this.fov - step)),
			'-': () => (this.fov = Math.min(MAX_FOV, this.fov + step))
		};
		const move = moves[e.key];
		if (!move) return;
		e.preventDefault();
		if (this.busy) return;
		this.inertia = null;
		move();
		this.invalidate();
	};
}
