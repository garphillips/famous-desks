#!/usr/bin/env node
/**
 * Cuts six rendered cube faces into the tile pyramid the website streams, plus a
 * preview strip and an equirectangular fallback. Called by blender/export.py after
 * it renders a viewpoint's faces; can also be run by hand:
 *
 *   node web/scripts/tile-pano.mjs --faces blender/build/cube/jobs-room/office \
 *        --out content/spaces/jobs-room/panos/office --equirect content/spaces/jobs-room/panos/office.webp
 *
 * Input: <faces>/{n,e,s,w,u,d}.png, square, rendered by perspective cameras with a 90° field
 * of view from the viewpoint (see CUBE_FACES in blender/lib/tour.py):
 *
 *   face  looks    image right  image up      (Blender axes: x east, y north, z up)
 *   n     north    east         up
 *   e     east     south        up
 *   s     south    west         up
 *   w     west     north        up
 *   u     up       east         south
 *   d     down     east         north
 *
 * Output (in --out):
 *   <level>/<face>-<row>-<col>.webp   tiles; <level> is the face size at that level. Each tile is up to
 *                                     tileSize² face pixels plus a 1 px border copied from its neighbours
 *                                     (clamped at face edges), so the viewer can filter across tiles seamlessly.
 *   preview.webp                      the six faces at --preview px (plus the 1 px border) side by side
 *   tiles.json                        { faceSize, tileSize, levels, bleed, format, previewSize }
 * and --equirect: the panorama reprojected to equirectangular (centre = north, yaw clockwise).
 *
 * Uses sharp (libvips) for resizing and WebP encoding; the reprojection is plain JS.
 */
import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { parseArgs } from 'node:util';
import sharp from 'sharp';

const FACES = ['n', 'e', 's', 'w', 'u', 'd'];
/** forward, right, up per face, Blender axes (x east, y north, z up). */
const FACE_AXES = {
	n: [[0, 1, 0], [1, 0, 0], [0, 0, 1]],
	e: [[1, 0, 0], [0, -1, 0], [0, 0, 1]],
	s: [[0, -1, 0], [-1, 0, 0], [0, 0, 1]],
	w: [[-1, 0, 0], [0, 1, 0], [0, 0, 1]],
	u: [[0, 0, 1], [1, 0, 0], [0, -1, 0]],
	d: [[0, 0, -1], [1, 0, 0], [0, 1, 0]]
};
const BLEED = 1;

const { values: opt } = parseArgs({
	options: {
		faces: { type: 'string' },
		out: { type: 'string' },
		equirect: { type: 'string' },
		'equirect-width': { type: 'string', default: '4096' },
		tile: { type: 'string', default: '512' },
		quality: { type: 'string', default: '85' },
		preview: { type: 'string', default: '256' }
	}
});
if (!opt.faces || !opt.out) {
	console.error('usage: tile-pano.mjs --faces <dir> --out <dir> [--equirect <file.webp>] [--equirect-width 4096] [--tile 512] [--quality 85] [--preview 256]');
	process.exit(2);
}
const tileSize = +opt.tile;
const quality = +opt.quality;
const previewSize = +opt.preview;
const started = Date.now();

/** Face images as raw RGB. */
const faces = {};
for (const f of FACES) {
	const { data, info } = await sharp(join(opt.faces, `${f}.png`))
		.removeAlpha()
		.raw()
		.toBuffer({ resolveWithObject: true });
	if (info.width !== info.height) throw new Error(`${f}.png is not square`);
	faces[f] = { data, size: info.width };
}
const faceSize = faces.n.size;
if (FACES.some((f) => faces[f].size !== faceSize)) throw new Error('faces differ in size');

/** tileSize·2^k below faceSize, then faceSize: e.g. 512, 1024, 2048, 2560. */
const levels = [];
for (let s = tileSize; s < faceSize; s *= 2) levels.push(s);
levels.push(faceSize);

/** A face (or a resized copy) with a `bleed` px border copied from its edge pixels. */
async function bordered(face, size) {
	let img = sharp(face.data, { raw: { width: face.size, height: face.size, channels: 3 } });
	if (size !== face.size) {
		// resize, then reload: sharp applies extend before resize otherwise
		const resized = await img.resize(size, size, { kernel: 'lanczos3' }).raw().toBuffer();
		img = sharp(resized, { raw: { width: size, height: size, channels: 3 } });
	}
	const data = await img
		.extend({ top: BLEED, bottom: BLEED, left: BLEED, right: BLEED, extendWith: 'copy' })
		.raw()
		.toBuffer();
	return { data, width: size + 2 * BLEED };
}

// Written to a side folder and swapped in at the end, so a site being browsed meanwhile
// keeps serving the old panorama whole instead of a half-deleted one.
const work = `${opt.out}.partial`;
await rm(work, { recursive: true, force: true });
let files = 0;
let bytes = 0;
const write = async (path, pipeline) => {
	const buf = await pipeline.toBuffer();
	await writeFile(path, buf);
	files++;
	bytes += buf.length;
};

for (const level of levels) {
	const dir = join(work, String(level));
	await mkdir(dir, { recursive: true });
	const n = Math.ceil(level / tileSize);
	for (const f of FACES) {
		const src = await bordered(faces[f], level);
		const raw = { raw: { width: src.width, height: src.width, channels: 3 } };
		const jobs = [];
		for (let row = 0; row < n; row++) {
			for (let col = 0; col < n; col++) {
				const w = Math.min(tileSize, level - col * tileSize);
				const h = Math.min(tileSize, level - row * tileSize);
				// In bordered coordinates the tile's content starts at +BLEED, so its border starts at col*tileSize.
				const region = { left: col * tileSize, top: row * tileSize, width: w + 2 * BLEED, height: h + 2 * BLEED };
				jobs.push(
					write(join(dir, `${f}-${row}-${col}.webp`), sharp(src.data, raw).extract(region).webp({ quality, effort: 4 }))
				);
			}
		}
		await Promise.all(jobs);
	}
}

// Preview strip: n e s w u d, each previewSize + 2·BLEED square.
const cell = previewSize + 2 * BLEED;
const composite = [];
for (const [i, f] of FACES.entries()) {
	const src = await bordered(faces[f], previewSize);
	composite.push({ input: src.data, raw: { width: cell, height: cell, channels: 3 }, left: i * cell, top: 0 });
}
await write(
	join(work, 'preview.webp'),
	sharp({ create: { width: cell * 6, height: cell, channels: 3, background: '#000' } })
		.composite(composite)
		.webp({ quality: 80, effort: 4 })
);

const meta = { faceSize, tileSize, levels, bleed: BLEED, format: 'webp', previewSize };
await writeFile(join(work, 'tiles.json'), JSON.stringify(meta, null, 2));
await rm(opt.out, { recursive: true, force: true });
await rename(work, opt.out);

if (opt.equirect) {
	const W = +opt['equirect-width'];
	const H = W / 2;
	const out = Buffer.alloc(W * H * 3);
	const N = faceSize;
	const axes = FACES.map((f) => FACE_AXES[f]);
	const dot = (a, x, y, z) => a[0] * x + a[1] * y + a[2] * z;
	for (let py = 0; py < H; py++) {
		const pitch = Math.PI / 2 - ((py + 0.5) / H) * Math.PI;
		const cp = Math.cos(pitch);
		const z = Math.sin(pitch);
		for (let px = 0; px < W; px++) {
			const yaw = ((px + 0.5) / W) * 2 * Math.PI - Math.PI; // centre = north, clockwise
			const x = cp * Math.sin(yaw);
			const y = cp * Math.cos(yaw);
			let best = 0;
			let bestDot = -2;
			for (let i = 0; i < 6; i++) {
				const d = dot(axes[i][0], x, y, z);
				if (d > bestDot) {
					bestDot = d;
					best = i;
				}
			}
			const [, r, u] = axes[best];
			const a = dot(r, x, y, z) / bestDot;
			const b = dot(u, x, y, z) / bestDot;
			// pixel centres: a = 2(i+0.5)/N - 1, b = 1 - 2(j+0.5)/N
			const fx = Math.min(N - 1, Math.max(0, ((a + 1) / 2) * N - 0.5));
			const fy = Math.min(N - 1, Math.max(0, ((1 - b) / 2) * N - 0.5));
			const x0 = Math.floor(fx);
			const y0 = Math.floor(fy);
			const x1 = Math.min(N - 1, x0 + 1);
			const y1 = Math.min(N - 1, y0 + 1);
			const tx = fx - x0;
			const ty = fy - y0;
			const data = faces[FACES[best]].data;
			const o = (py * W + px) * 3;
			for (let c = 0; c < 3; c++) {
				const top = data[(y0 * N + x0) * 3 + c] * (1 - tx) + data[(y0 * N + x1) * 3 + c] * tx;
				const bottom = data[(y1 * N + x0) * 3 + c] * (1 - tx) + data[(y1 * N + x1) * 3 + c] * tx;
				out[o + c] = Math.round(top * (1 - ty) + bottom * ty);
			}
		}
	}
	await mkdir(dirname(opt.equirect), { recursive: true });
	const part = `${opt.equirect}.partial.webp`;
	await sharp(out, { raw: { width: W, height: H, channels: 3 } }).webp({ quality, effort: 4 }).toFile(part);
	await rename(part, opt.equirect);
}

console.log(
	`tile-pano: ${opt.out}: ${files} files, ${(bytes / 1e6).toFixed(2)} MB, levels ${levels.join('/')}` +
		` (${((Date.now() - started) / 1000).toFixed(1)} s)`
);
