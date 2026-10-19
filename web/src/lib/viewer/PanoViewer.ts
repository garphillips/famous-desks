import * as THREE from 'three';

/**
 * Renders an equirectangular panorama and handles look-around input.
 *
 * Angles follow the export convention: yaw 0 = north (image centre), clockwise,
 * so east = 90. Three.js samples equirect backgrounds with
 * u = atan2(z, x) / 2π + 0.5, so north maps to +X and east to +Z.
 */

const MIN_FOV = 30;
const MAX_FOV = 90;
const MAX_PITCH = 85;

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

export class PanoViewer {
	yaw = 0;
	pitch = 0;
	fov = 75;

	private renderer: THREE.WebGLRenderer;
	private scene = new THREE.Scene();
	private camera: THREE.PerspectiveCamera;
	private loader = new THREE.TextureLoader();
	private texture: THREE.Texture | null = null;
	private dirty = true;
	private frame = 0;
	private drag: { x: number; y: number } | null = null;
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
		this.camera = new THREE.PerspectiveCamera(this.fov, 1, 0.1, 100);

		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointermove', this.onPointerMove);
		canvas.addEventListener('pointerup', this.onPointerUp);
		canvas.addEventListener('pointercancel', this.onPointerUp);
		canvas.addEventListener('wheel', this.onWheel, { passive: false });
		canvas.addEventListener('keydown', this.onKeyDown);

		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(canvas);
		this.resize();
		this.loop();
	}

	async setPanorama(url: string) {
		const texture = await this.loader.loadAsync(url);
		texture.mapping = THREE.EquirectangularReflectionMapping;
		texture.colorSpace = THREE.SRGBColorSpace;
		texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
		this.scene.background = texture;
		this.texture?.dispose();
		this.texture = texture;
		this.invalidate();
	}

	/** Horizontal field of view in degrees. */
	get hfov() {
		const v = THREE.MathUtils.degToRad(this.fov) / 2;
		return THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(v) * this.camera.aspect));
	}

	zoomBy(deltaDegrees: number) {
		this.fov = THREE.MathUtils.clamp(this.fov + deltaDegrees, MIN_FOV, MAX_FOV);
		this.invalidate();
	}

	/**
	 * A still of part of the panorama, as a data URL. Renders through the main
	 * canvas (so colour management matches the live view), copies the centre
	 * out, then restores the live view.
	 */
	snapshot(yaw: number, pitch: number, fov: number, width: number, height: number) {
		if (!this.scene.background) return '';
		const { width: cw, height: ch } = this.renderer.domElement;
		const cam = this.camera.clone();
		// Fit the requested aspect inside the canvas, then size fov to that crop.
		const scale = Math.min(cw / width, ch / height);
		const crop = { w: width * scale, h: height * scale };
		const cropFovRad = THREE.MathUtils.degToRad(fov) * (ch / crop.h);
		cam.fov = THREE.MathUtils.radToDeg(Math.min(cropFovRad, Math.PI * 0.95));
		cam.updateProjectionMatrix();
		cam.lookAt(direction(yaw, pitch));
		cam.updateMatrixWorld();
		this.renderer.render(this.scene, cam);
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
		this.renderer.render(this.scene, this.camera);
		return out.toDataURL('image/jpeg', 0.85);
	}

	lookAt(yaw: number, pitch = 0) {
		this.yaw = yaw;
		this.pitch = pitch;
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

	dispose() {
		cancelAnimationFrame(this.frame);
		this.resizeObserver.disconnect();
		this.canvas.removeEventListener('pointerdown', this.onPointerDown);
		this.canvas.removeEventListener('pointermove', this.onPointerMove);
		this.canvas.removeEventListener('pointerup', this.onPointerUp);
		this.canvas.removeEventListener('pointercancel', this.onPointerUp);
		this.canvas.removeEventListener('wheel', this.onWheel);
		this.canvas.removeEventListener('keydown', this.onKeyDown);
		this.texture?.dispose();
		this.renderer.dispose();
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

	private loop = () => {
		this.frame = requestAnimationFrame(this.loop);
		if (!this.dirty) return;
		this.dirty = false;
		this.pitch = THREE.MathUtils.clamp(this.pitch, -MAX_PITCH, MAX_PITCH);
		this.yaw = ((((this.yaw + 180) % 360) + 360) % 360) - 180;
		this.camera.fov = this.fov;
		this.camera.updateProjectionMatrix();
		this.camera.lookAt(direction(this.yaw, this.pitch));
		this.camera.updateMatrixWorld();
		this.renderer.render(this.scene, this.camera);
		this.onChange();
	};

	/** Degrees of view per CSS pixel, so dragging tracks the pointer at any zoom. */
	private degreesPerPixel() {
		return this.fov / this.canvas.clientHeight;
	}

	private onPointerDown = (e: PointerEvent) => {
		this.drag = { x: e.clientX, y: e.clientY };
		this.canvas.setPointerCapture(e.pointerId);
		this.onInteract();
	};

	private onPointerMove = (e: PointerEvent) => {
		if (!this.drag) return;
		const k = this.degreesPerPixel();
		this.yaw -= (e.clientX - this.drag.x) * k;
		this.pitch += (e.clientY - this.drag.y) * k;
		this.drag = { x: e.clientX, y: e.clientY };
		this.invalidate();
	};

	private onPointerUp = (e: PointerEvent) => {
		this.drag = null;
		if (this.canvas.hasPointerCapture(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
	};

	private onWheel = (e: WheelEvent) => {
		e.preventDefault();
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
		move();
		this.invalidate();
	};
}
