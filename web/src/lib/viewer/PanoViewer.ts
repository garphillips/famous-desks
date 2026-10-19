import * as THREE from 'three';

/**
 * Renders an equirectangular panorama and handles look-around input.
 *
 * Angles follow the export convention: yaw 0 = north (image centre), clockwise,
 * so east = 90. Panoramas are drawn on an inside-out box whose shader samples
 * u = atan2(z, x) / 2π + 0.5 (as Three.js does for equirect backgrounds), so
 * north maps to +X and east to +Z.
 *
 * Two layers (current and incoming) let viewpoint changes crossfade, each drawn
 * with its own field of view so the old view can zoom in while the new one settles.
 */

const MIN_FOV = 30;
const MAX_FOV = 90;
const MAX_PITCH = 85;
// Each 4096x2048 panorama is ~32MB of GPU memory, so phones keep fewer.
const CACHE_SIZE =
	typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse), (max-width: 760px)').matches ? 3 : 6;
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

export interface ScreenPoint {
	x: number;
	y: number;
	visible: boolean;
}

export function direction(yaw: number, pitch: number) {
	const y = THREE.MathUtils.degToRad(yaw);
	const p = THREE.MathUtils.degToRad(pitch);
	return new THREE.Vector3(Math.cos(p) * Math.cos(y), Math.sin(p), Math.cos(p) * Math.sin(y));
}

export const prefersReducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

const vertexShader = /* glsl */ `
	varying vec3 vDir;
	void main() {
		vDir = position;
		gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	}
`;

const fragmentShader = /* glsl */ `
	#include <common>
	uniform sampler2D map;
	uniform float opacity;
	varying vec3 vDir;
	void main() {
		vec3 dir = normalize(vDir);
		vec2 uv = vec2(atan(dir.z, dir.x) * RECIPROCAL_PI2 + 0.5, asin(clamp(dir.y, -1.0, 1.0)) * RECIPROCAL_PI + 0.5);
		gl_FragColor = vec4(texture2D(map, uv).rgb, opacity);
		#include <colorspace_fragment>
	}
`;

interface Layer {
	mesh: THREE.Mesh<THREE.BoxGeometry, THREE.ShaderMaterial>;
	url: string | null;
	/** Field of view multiplier while transitioning. */
	zoom: number;
	opacity: number;
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

export class PanoViewer {
	yaw = 0;
	pitch = 0;
	fov = 75;

	private renderer: THREE.WebGLRenderer;
	private scene = new THREE.Scene();
	private camera: THREE.PerspectiveCamera;
	private loader = new THREE.TextureLoader();
	private geometry = new THREE.BoxGeometry(10, 10, 10);
	private current: Layer;
	private incoming: Layer;
	/** url -> texture, least recently used first. */
	private cache = new Map<string, Promise<THREE.Texture>>();
	/** Panorama a pending load or transition is heading to; never evicted. */
	private target: string | null = null;
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

	constructor(
		private canvas: HTMLCanvasElement,
		{ onChange, onInteract = () => {} }: { onChange: () => void; onInteract?: () => void }
	) {
		this.onChange = onChange;
		this.onInteract = onInteract;
		this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		this.renderer.outputColorSpace = THREE.SRGBColorSpace;
		this.renderer.autoClear = false;
		this.camera = new THREE.PerspectiveCamera(this.fov, 1, 0.1, 100);
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

	/** Url of the panorama on screen (after any transition settles). */
	get url() {
		return this.current.url;
	}

	/** True while a viewpoint transition is running. */
	get busy() {
		return this.target !== null;
	}

	/** Loads (or reuses) a panorama texture and uploads it to the GPU. */
	preload(url: string): Promise<THREE.Texture> {
		const cached = this.cache.get(url);
		if (cached) {
			this.cache.delete(url);
			this.cache.set(url, cached);
			return cached;
		}
		const promise = this.loader.loadAsync(url).then((texture) => {
			if (this.disposed) {
				texture.dispose();
				throw new Error('Viewer disposed');
			}
			texture.colorSpace = THREE.SRGBColorSpace;
			// Sampled by direction in the shader: no mipmaps (they'd show a seam where u wraps).
			texture.generateMipmaps = false;
			texture.minFilter = THREE.LinearFilter;
			texture.wrapS = THREE.RepeatWrapping;
			this.renderer.initTexture(texture);
			return texture;
		});
		promise.catch(() => {
			if (this.cache.get(url) === promise) this.cache.delete(url);
		});
		this.cache.set(url, promise);
		this.evict();
		return promise;
	}

	/** Warms the cache in the background, one panorama at a time. */
	prefetch(urls: string[]) {
		const token = this.token;
		const next = (i: number) => {
			if (i >= urls.length || token !== this.token) return;
			const run = () => {
				if (token !== this.token) return;
				this.preload(urls[i])
					.catch(() => {})
					.then(() => next(i + 1));
			};
			if ('requestIdleCallback' in window) requestIdleCallback(run, { timeout: 1500 });
			else setTimeout(run, 200);
		};
		next(0);
	}

	/** Shows a panorama straight away, no transition. */
	async setPanorama(url: string) {
		this.settle();
		const token = ++this.token;
		this.target = url;
		try {
			const texture = await this.preload(url);
			if (token !== this.token) return;
			this.assign(this.current, texture, url);
			this.invalidate();
		} finally {
			if (token === this.token) this.target = null;
		}
	}

	/**
	 * Moves to another panorama: turn to `yaw`, zoom in while crossfading, settle.
	 * With `reduced`, just a quick crossfade at the current heading. Resolves false
	 * if another transition replaced this one.
	 */
	async transitionTo(url: string, { yaw, reduced = false }: { yaw: number; reduced?: boolean }) {
		this.settle();
		const token = ++this.token;
		this.target = url;
		this.inertia = null;
		this.pinch = null;
		const texture = this.preload(url);
		try {
			if (!reduced) {
				const from = { yaw: this.yaw, pitch: this.pitch };
				const turn = wrap(yaw - from.yaw);
				const ms = Math.min(TURN_MAX_MS, (Math.abs(turn) + Math.abs(from.pitch)) * TURN_MS_PER_DEGREE);
				await this.animate(ms, (t) => {
					const e = easeInOut(t);
					this.yaw = from.yaw + turn * e;
					this.pitch = from.pitch * (1 - e);
				});
				if (token !== this.token) return false;
			}
			const tex = await texture;
			if (token !== this.token) return false;
			this.assign(this.incoming, tex, url);
			await this.animate(reduced ? REDUCED_MS : STEP_MS, (t) => {
				if (reduced) {
					this.incoming.opacity = t;
					return;
				}
				this.current.zoom = THREE.MathUtils.lerp(1, STEP_ZOOM_OUT, easeIn(t));
				this.incoming.opacity = smoothstep(0.25, 0.85, t);
				this.incoming.zoom = THREE.MathUtils.lerp(STEP_ZOOM_IN, 1, easeOut(smoothstep(0.25, 1, t)));
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
		if (this.incoming.url) this.commit();
		this.current.zoom = 1;
		this.current.opacity = 1;
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
		this.fov = THREE.MathUtils.clamp(this.fov + deltaDegrees, MIN_FOV, MAX_FOV);
		this.invalidate();
	}

	/**
	 * A still of part of the panorama, as a data URL. Renders through the main
	 * canvas (so colour management matches the live view), copies the centre
	 * out, then restores the live view.
	 */
	snapshot(yaw: number, pitch: number, fov: number, width: number, height: number) {
		if (!this.current.url) return '';
		const { width: cw, height: ch } = this.renderer.domElement;
		const cam = this.camera.clone();
		// Fit the requested aspect inside the canvas, then size fov to that crop.
		const scale = Math.min(cw / width, ch / height);
		const crop = { w: width * scale, h: height * scale };
		const cropFovRad = THREE.MathUtils.degToRad(fov) * (ch / crop.h);
		cam.lookAt(direction(yaw, pitch));
		cam.updateMatrixWorld();
		this.renderer.clear();
		this.drawLayer(this.current, cam, THREE.MathUtils.radToDeg(Math.min(cropFovRad, Math.PI * 0.95)), 1);
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

	lookAt(yaw: number, pitch = 0) {
		this.yaw = yaw;
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
		for (const promise of this.cache.values()) promise.then((t) => t.dispose(), () => {});
		this.cache.clear();
		for (const layer of [this.current, this.incoming]) layer.mesh.material.dispose();
		this.geometry.dispose();
		this.renderer.dispose();
	}

	private createLayer(): Layer {
		const material = new THREE.ShaderMaterial({
			uniforms: { map: { value: null }, opacity: { value: 1 } },
			vertexShader,
			fragmentShader,
			side: THREE.BackSide,
			transparent: true,
			depthTest: false,
			depthWrite: false
		});
		const mesh = new THREE.Mesh(this.geometry, material);
		mesh.frustumCulled = false;
		mesh.visible = false;
		this.scene.add(mesh);
		return { mesh, url: null, zoom: 1, opacity: 1 };
	}

	private assign(layer: Layer, texture: THREE.Texture | null, url: string | null) {
		layer.mesh.material.uniforms.map.value = texture;
		layer.url = url;
		layer.zoom = 1;
		layer.opacity = layer === this.incoming ? 0 : 1;
	}

	/** Incoming becomes current; the old texture stays in the cache. */
	private commit() {
		[this.current, this.incoming] = [this.incoming, this.current];
		this.current.zoom = 1;
		this.current.opacity = 1;
		this.assign(this.incoming, null, null);
		this.evict();
		this.invalidate();
	}

	private evict() {
		for (const [url, promise] of this.cache) {
			if (this.cache.size <= CACHE_SIZE) break;
			if (url === this.current.url || url === this.incoming.url || url === this.target) continue;
			this.cache.delete(url);
			promise.then((t) => t.dispose(), () => {});
		}
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

		if (!this.dirty) return;
		this.dirty = false;
		this.pitch = THREE.MathUtils.clamp(this.pitch, -MAX_PITCH, MAX_PITCH);
		this.yaw = wrap(this.yaw);
		this.camera.fov = this.fov;
		this.camera.updateProjectionMatrix();
		this.camera.lookAt(direction(this.yaw, this.pitch));
		this.camera.updateMatrixWorld();
		this.draw();
		this.onChange();
	};

	private draw() {
		this.renderer.clear();
		if (this.current.url) this.drawLayer(this.current, this.camera, this.fov * this.current.zoom, this.current.opacity);
		if (this.incoming.url && this.incoming.opacity > 0)
			this.drawLayer(this.incoming, this.camera, this.fov * this.incoming.zoom, this.incoming.opacity);
	}

	/** Draws one layer alone with the given fov, leaving `camera` as it was. */
	private drawLayer(layer: Layer, camera: THREE.PerspectiveCamera, fov: number, opacity: number) {
		const fov0 = camera.fov;
		camera.fov = fov;
		camera.updateProjectionMatrix();
		layer.mesh.material.uniforms.opacity.value = opacity;
		layer.mesh.visible = true;
		this.renderer.render(this.scene, camera);
		layer.mesh.visible = false;
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
			this.fov = THREE.MathUtils.clamp((this.pinch.fov * this.pinch.distance) / this.pointerDistance(), MIN_FOV, MAX_FOV);
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
			'+': () => (this.fov = Math.max(MIN_FOV, this.fov - step)),
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
