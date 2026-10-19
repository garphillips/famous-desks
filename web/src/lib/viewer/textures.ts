import * as THREE from 'three';

/**
 * GPU texture cache for panorama images and tiles, with a GPU-memory budget.
 *
 * Images are uploaded as soon as they load (so the first draw doesn't stall), without
 * a flip: v = 0 is the top row of the image. Tiles go through a priority queue with a few requests in flight;
 * backgrounds (previews, equirects) load immediately.
 */

export interface TextureOptions {
	/** Trilinear mipmaps + anisotropic filtering (tiles, equirects); off for previews. */
	mipmaps: boolean;
	/** Repeat horizontally (equirects wrap around at the back). */
	wrap?: boolean;
}

interface Entry {
	promise: Promise<THREE.Texture>;
	texture: THREE.Texture | null;
	/** Given up on (after MAX_ATTEMPTS tries). */
	failed: boolean;
	/** This attempt failed (a retry may follow). */
	rejected: boolean;
	bytes: number;
	used: number;
}

const MAX_IN_FLIGHT = 6;
const MAX_ATTEMPTS = 3;
const MAX_ANISOTROPY = 8;

export class TextureStore {
	private entries = new Map<string, Entry>();
	/** Failed attempts per url. */
	private failures = new Map<string, number>();
	private queue: { url: string; options: TextureOptions }[] = [];
	private inFlight = 0;
	private bytes = 0;
	private clock = 0;
	private disposed = false;
	private anisotropy: number;

	constructor(
		private renderer: THREE.WebGLRenderer,
		/** GPU bytes to stay under; textures in use are never evicted. */
		private budget: number,
		private onLoad: (url: string) => void,
		private onEvict: (url: string) => void
	) {
		this.anisotropy = Math.min(MAX_ANISOTROPY, renderer.capabilities.getMaxAnisotropy());
	}

	/** The texture if it's loaded (and marks it used), else null. */
	get(url: string): THREE.Texture | null {
		const entry = this.entries.get(url);
		if (!entry?.texture) return null;
		entry.used = ++this.clock;
		return entry.texture;
	}

	/** True while tiles are queued or loading. */
	get busy() {
		return this.queue.length > 0 || this.inFlight > 0;
	}

	failed(url: string) {
		return this.entries.get(url)?.failed ?? false;
	}

	/** True once loaded, failed or on its way. */
	known(url: string) {
		return this.entries.has(url);
	}

	/** Loads now, bypassing the queue; retries a failed load a couple of times. */
	async load(url: string, options: TextureOptions): Promise<THREE.Texture> {
		for (let attempt = 1; ; attempt++) {
			const entry = this.entries.get(url);
			if (entry && !entry.rejected) entry.used = ++this.clock;
			else if (entry) this.entries.delete(url); // failed before: try again
			try {
				return await (entry && !entry.rejected ? entry.promise : this.start(url, options));
			} catch (err) {
				if (attempt >= MAX_ATTEMPTS || this.disposed) throw err;
				await new Promise((r) => setTimeout(r, 500 * attempt));
			}
		}
	}

	/** Replaces the tile queue: `urls` in priority order; ones already known are skipped. */
	request(urls: string[], options: TextureOptions) {
		this.queue = urls.filter((url) => !this.entries.has(url)).map((url) => ({ url, options }));
		this.pump();
	}

	/** Frees least recently used textures not in `keep` until under budget. */
	evict(keep: Set<string>) {
		if (this.bytes <= this.budget) return;
		const candidates = [...this.entries].filter(([url, e]) => (e.texture || e.failed) && !keep.has(url));
		candidates.sort((a, b) => a[1].used - b[1].used);
		for (const [url, entry] of candidates) {
			if (this.bytes <= this.budget) break;
			this.drop(url, entry);
		}
	}

	dispose() {
		this.disposed = true;
		this.queue = [];
		for (const [url, entry] of this.entries) this.drop(url, entry, false);
	}

	private drop(url: string, entry: Entry, notify = true) {
		this.entries.delete(url);
		this.bytes -= entry.bytes;
		if (entry.texture) {
			entry.texture.dispose();
		}
		if (notify) this.onEvict(url);
	}

	private pump() {
		while (this.inFlight < MAX_IN_FLIGHT && this.queue.length) {
			const { url, options } = this.queue.shift()!;
			if (this.entries.has(url)) continue;
			this.inFlight++;
			this.start(url, options)
				.catch(() => {})
				.finally(() => {
					this.inFlight--;
					this.pump();
				});
		}
	}

	private start(url: string, options: TextureOptions) {
		const entry: Entry = { promise: null!, texture: null, failed: false, rejected: false, bytes: 0, used: ++this.clock };
		entry.promise = this.fetchTexture(url, options).then(
			(texture) => {
				if (this.disposed || this.entries.get(url) !== entry) {
					texture.dispose();
					throw new Error('Texture no longer wanted');
				}
				const { naturalWidth: width, naturalHeight: height } = texture.image as HTMLImageElement;
				entry.texture = texture;
				entry.bytes = width * height * 4 * (options.mipmaps ? 4 / 3 : 1);
				this.bytes += entry.bytes;
				this.onLoad(url);
				return texture;
			},
			(err) => {
				entry.rejected = true;
				if (this.entries.get(url) === entry) {
					// Retry a couple of times (a dropped request shouldn't cost the whole pyramid),
					// then report it failed for good.
					const attempts = (this.failures.get(url) ?? 0) + 1;
					this.failures.set(url, attempts);
					if (attempts >= MAX_ATTEMPTS) entry.failed = true;
					else
						setTimeout(() => {
							if (this.entries.get(url) !== entry || this.disposed) return;
							this.entries.delete(url);
							this.onLoad(url); // redraw, which asks for it again
						}, 500 * attempts);
				}
				throw err;
			}
		);
		this.entries.set(url, entry);
		return entry.promise;
	}

	private async fetchTexture(url: string, { mipmaps, wrap }: TextureOptions) {
		// An <img> rather than fetch + createImageBitmap: headless Chrome's virtual time (used
		// for screenshots) waits for image loads reliably, but not for bitmap decodes.
		const image = new Image();
		image.decoding = 'async';
		await new Promise<void>((resolve, reject) => {
			image.onload = () => resolve();
			image.onerror = () => reject(new Error(`Couldn't load ${url}`));
			image.src = url;
		});
		if (this.disposed) throw new Error('Viewer disposed');
		const texture = new THREE.Texture(image);
		texture.flipY = false;
		texture.colorSpace = THREE.SRGBColorSpace;
		texture.generateMipmaps = mipmaps;
		texture.minFilter = mipmaps ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
		texture.magFilter = THREE.LinearFilter;
		texture.anisotropy = mipmaps ? this.anisotropy : 1;
		texture.wrapS = wrap ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
		texture.wrapT = THREE.ClampToEdgeWrapping;
		texture.needsUpdate = true;
		this.renderer.initTexture(texture);
		return texture;
	}
}
