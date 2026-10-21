// Shared helpers for check.mjs: launching headless Chrome, the sizes we test at,
// waiting for the panorama, turning the view, tapping/clicking, screenshots and
// collecting what went wrong on a page.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

export const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// Phone gets touch (and the mobile layout); tablet is a mouse-driven narrow desktop,
// which is how the earlier checks treated it.
export const SIZES = {
	desktop: { width: 1400, height: 860 },
	tablet: { width: 900, height: 1000 },
	phone: { width: 390, height: 844, isMobile: true, hasTouch: true }
};

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** --size desktop|tablet|phone|all (or a comma list) -> [name, ...]. */
export function sizeNames(arg = 'desktop') {
	const names = arg === 'all' ? Object.keys(SIZES) : arg.split(',');
	for (const n of names) if (!SIZES[n]) throw new Error(`unknown size "${n}" (desktop, tablet, phone or all)`);
	return names;
}

/** Headless Chrome with a throwaway profile. WebGL needs swiftshader when headless. */
export async function launch({ autoplay = false } = {}) {
	const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fd-check-'));
	const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--hide-scrollbars'];
	// Lets the Spotify embed start without a real user gesture.
	if (autoplay) args.push('--autoplay-policy=no-user-gesture-required');
	const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', userDataDir, args });
	const close = async () => {
		await browser.close().catch(() => {});
		fs.rmSync(userDataDir, { recursive: true, force: true });
	};
	return { browser, close };
}

/**
 * A page at one of SIZES that records page errors, console errors and failed
 * requests. Only requests to `origin` count as failures: third-party embeds
 * (Spotify) are noisy and outside our control.
 */
export async function openPage(browser, sizeName, origin) {
	const page = await browser.newPage();
	const size = SIZES[sizeName];
	await page.setViewport({ isMobile: false, hasTouch: false, ...size });
	page.size = { name: sizeName, ...size, touch: !!size.hasTouch };
	const log = (page.problems = { pageErrors: [], consoleErrors: [], failed: [] });
	page.on('pageerror', (e) => log.pageErrors.push(String(e.message ?? e)));
	page.on('console', async (m) => {
		if (m.type() !== 'error') return;
		// m.text() prints Error objects as "JSHandle@error"; ask the page for their stack instead.
		const parts = await Promise.all(
			m.args().map((a) => a.evaluate((v) => (v instanceof Error ? v.stack : String(v))).catch(() => null))
		);
		log.consoleErrors.push(parts.some((p) => p != null) ? parts.join(' ').slice(0, 2000) : m.text());
	});
	const ours = (url) => !origin || url.startsWith(origin);
	page.on('response', (r) => {
		if (r.status() >= 400 && ours(r.url())) log.failed.push(`${r.status()} ${r.url()}`);
	});
	page.on('requestfailed', (r) => {
		const why = r.failure()?.errorText ?? 'failed';
		// The viewer cancels tile requests it no longer needs; that's not a failure.
		if (why !== 'net::ERR_ABORTED' && ours(r.url())) log.failed.push(`${why} ${r.url()}`);
	});
	return page;
}

/** Navigate and wait for the network to calm down (not fully idle: the Spotify embed keeps a connection open). */
export async function goto(page, url, timeout = 60000) {
	await page.goto(url, { waitUntil: 'networkidle2', timeout });
}

/**
 * Wait until the main canvas reports every wanted tile loaded:
 * data-pano="<level>:<loaded>/<wanted>" with loaded == wanted, or "equirect".
 * Returns the last value seen (and ok: false on timeout) rather than throwing,
 * so a slow load shows up in the report instead of killing the run.
 */
export async function waitForPano(page, timeout = 30000) {
	const start = Date.now();
	let value = null;
	while (Date.now() - start < timeout) {
		value = await page.evaluate(() => document.querySelector('canvas[data-pano]')?.dataset.pano ?? null);
		const m = value?.match(/^\d+:(\d+)\/(\d+)$/);
		if (value === 'equirect' || (m && m[1] === m[2] && Number(m[2]) > 0)) {
			await sleep(400); // tiles fade in
			return { ok: true, pano: value, ms: Date.now() - start };
		}
		await sleep(150);
	}
	return { ok: false, pano: value, ms: Date.now() - start };
}

/**
 * Wait until the view stops moving (a walk, a flight, drag inertia): two strips
 * across the middle of the screen, 250 ms apart, come out identical. Returns
 * how long that took, or null if it was still moving after `timeout`.
 */
export async function settle(page, timeout = 8000) {
	const { width, height } = page.size;
	const clip = { x: 0, y: Math.round(height * 0.3), width, height: Math.round(height * 0.4) };
	const start = Date.now();
	let last = null;
	while (Date.now() - start < timeout) {
		const now = Buffer.from(await page.screenshot({ clip, type: 'jpeg', quality: 60 }));
		if (last && now.equals(last)) return Date.now() - start;
		last = now;
		await sleep(250);
	}
	return null;
}

/** Poll fn() in the page until it's truthy; returns its value or null on timeout. */
export async function waitFor(page, fn, timeout = 10000, ...args) {
	try {
		const h = await page.waitForFunction(fn, { timeout, polling: 100 }, ...args);
		return await h.jsonValue();
	} catch {
		return null;
	}
}

/** CDP session per page, for raw touch events (puppeteer's touchscreen can't drag). */
const sessions = new WeakMap();
async function cdp(page) {
	if (!sessions.has(page)) sessions.set(page, await page.createCDPSession());
	return sessions.get(page);
}

/**
 * Drag the view by (dx, dy) px from (x, y) (default: centre) in ~16 ms steps, like
 * a hand would; dragging right turns the view left. Touch on phone, mouse elsewhere.
 */
export async function turn(page, dx, dy = 0, { x, y, step = 40 } = {}) {
	const { width, height, touch } = page.size;
	x ??= width / 2;
	y ??= height / 2;
	const steps = Math.max(2, Math.ceil(Math.hypot(dx, dy) / step));
	if (touch) {
		const c = await cdp(page);
		const at = (type, px, py) => c.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x: px, y: py }] });
		await at('touchStart', x, y);
		for (let i = 1; i <= steps; i++) {
			await at('touchMove', x + (dx * i) / steps, y + (dy * i) / steps);
			await sleep(16);
		}
		await at('touchEnd');
	} else {
		await page.mouse.move(x, y);
		await page.mouse.down();
		for (let i = 1; i <= steps; i++) {
			await page.mouse.move(x + (dx * i) / steps, y + (dy * i) / steps);
			await sleep(16);
		}
		await page.mouse.up();
	}
}

/** Centre of an element (selector or handle), or null if it isn't rendered. */
export async function centre(page, target) {
	const el = typeof target === 'string' ? await page.$(target) : target;
	const box = await el?.boundingBox();
	return box && { x: box.x + box.width / 2, y: box.y + box.height / 2, box };
}

/** True if the element's centre is inside the viewport (so a real click can reach it). */
export async function onScreen(page, target) {
	const c = await centre(page, target);
	return !!c && c.x >= 0 && c.y >= 0 && c.x <= page.size.width && c.y <= page.size.height;
}

/** Tap (phone) or click (otherwise) the centre of an element. Returns false if it isn't there. */
export async function press(page, target) {
	const c = await centre(page, target);
	if (!c) return false;
	if (page.size.touch) await page.touchscreen.tap(c.x, c.y);
	else await page.mouse.click(c.x, c.y);
	return true;
}

/** Hover an element (no-op on touch). */
export async function hover(page, target) {
	if (page.size.touch) return false;
	const c = await centre(page, target);
	if (c) await page.mouse.move(c.x, c.y);
	return !!c;
}

/** Move the mouse into a corner so hover cards and highlights don't end up in a screenshot. */
export async function park(page) {
	if (!page.size.touch) {
		await page.mouse.move(5, 5);
		await sleep(300);
	}
}

/** Output directory (created) and a namer for files in it. */
export function outDir(dir) {
	fs.mkdirSync(dir, { recursive: true });
	return (name) => path.join(dir, name);
}

/** Filesystem-safe name fragment. */
export const slug = (s) =>
	String(s)
		.toLowerCase()
		.replace(/^https?:\/\/[^/]+/, '')
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '') || 'root';

export async function shot(page, file, clip) {
	await page.screenshot({ path: file, ...(clip && { clip }) });
	return file;
}

/**
 * Screenshots `frames` times, at most every `every` ms (swiftshader screenshots
 * take ~100 ms, so that's a floor). Returns [{ file, t, probe }] with t in ms from
 * the start and probe the result of the optional probe() taken with each frame.
 */
export async function filmstrip(page, fileFor, frames, every, { clip, probe } = {}) {
	const out = [];
	const start = Date.now();
	for (let i = 0; i < frames; i++) {
		const due = start + i * every;
		if (Date.now() < due) await sleep(due - Date.now());
		const t = Date.now() - start;
		out.push({ file: await shot(page, fileFor(i), clip), t, probe: probe && (await probe()) });
	}
	return out;
}

/**
 * Record what the compositor actually draws for `ms` while `action()` runs, via
 * CDP's screencast (a PNG screenshot per frame is far too slow under swiftshader
 * to judge smoothness). Returns every frame as { jpeg, t } with t in ms from the start.
 */
export async function screencast(page, ms, action = async () => {}) {
	const c = await cdp(page);
	const frames = [];
	let start = null;
	const onFrame = ({ data, metadata, sessionId }) => {
		c.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
		const at = metadata.timestamp * 1000;
		start ??= at;
		frames.push({ jpeg: Buffer.from(data, 'base64'), t: Math.round(at - start) });
	};
	c.on('Page.screencastFrame', onFrame);
	await c.send('Page.startScreencast', { format: 'jpeg', quality: 85, everyNthFrame: 1 });
	await Promise.all([action(), sleep(ms)]);
	await c.send('Page.stopScreencast');
	c.off('Page.screencastFrame', onFrame);
	return frames;
}

/** Pixels with any alpha in a 2D canvas: used to tell whether the speaker ripples are drawing. */
export function inkPixels(page, selector) {
	return page.evaluate((sel) => {
		const c = document.querySelector(sel);
		if (!c || !c.width || !c.height) return null;
		const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
		let n = 0;
		for (let i = 3; i < d.length; i += 4) if (d[i]) n++;
		return n;
	}, selector);
}

/**
 * Compose images into a labelled contact sheet, laid out as an HTML grid in the
 * same headless Chrome and screenshotted (no Python/PIL needed). Images go in
 * as data URIs because about:blank can't load file:// URLs.
 */
export async function contactSheet(browser, images, { out, labels = [], cols, width = 1800, title = '' }) {
	cols ??= Math.min(images.length, images.length <= 4 ? 2 : 3);
	const type = (f) => ({ '.jpg': 'jpeg', '.jpeg': 'jpeg', '.webp': 'webp', '.gif': 'gif' })[path.extname(f).toLowerCase()] ?? 'png';
	const esc = (s) => String(s).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
	const cells = images
		.map((f, i) => {
			// null: an empty cell (keeps a grid's rows aligned, e.g. a render with no photo)
			if (f == null) return `<figure class="empty"><figcaption>${esc(labels[i] ?? '')}</figcaption></figure>`;
			const src = `data:image/${type(f)};base64,${fs.readFileSync(f).toString('base64')}`;
			return `<figure><img src="${src}"><figcaption>${esc(labels[i] ?? path.basename(f))}</figcaption></figure>`;
		})
		.join('');
	const html = `<!doctype html><meta charset="utf-8"><style>
		body { margin: 0; padding: 16px; background: #111; color: #eee; font: 14px/1.3 ui-monospace, Menlo, monospace; width: ${width - 32}px; }
		h1 { font-size: 16px; margin: 0 0 12px; font-weight: 600; }
		.grid { display: grid; grid-template-columns: repeat(${cols}, 1fr); gap: 12px; }
		figure { margin: 0; }
		img { display: block; width: 100%; height: auto; background: #222; }
		figcaption { padding: 6px 2px 0; }
		.empty { display: flex; align-items: center; justify-content: center; background: #1a1a1a; color: #888; min-height: 120px; }
	</style>${title ? `<h1>${esc(title)}</h1>` : ''}<div class="grid">${cells}</div>`;
	const page = await browser.newPage();
	await page.setViewport({ width, height: 400 });
	await page.setContent(html, { waitUntil: 'load' });
	fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
	await page.screenshot({ path: out, fullPage: true });
	await page.close();
	return out;
}
