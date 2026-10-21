#!/usr/bin/env node
// Headless-Chrome checks for the tour. `node tools/check/check.mjs help` lists the
// commands; README.md says when to use which. Each run prints what it did, then
// one JSON line summarising it, and exits 1 if anything failed (2 on bad usage).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import {
	SIZES, sizeNames, sleep, launch, openPage, goto, waitForPano, settle, waitFor, turn, onScreen,
	press, hover, park, outDir, slug, shot, filmstrip, inkPixels, screencast, contactSheet
} from './lib.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RIPPLES = 'canvas[aria-hidden="true"]';
const SPOTIFY = 'open.spotify.com/embed';

const OPTIONS = {
	base: { type: 'string', default: 'http://localhost:5180' },
	out: { type: 'string' },
	size: { type: 'string' },
	space: { type: 'string', default: 'jobs-room' },
	turn: { type: 'string' },
	hotspot: { type: 'string' },
	yaw: { type: 'string' },
	pitch: { type: 'string' },
	fov: { type: 'string' },
	name: { type: 'string' },
	from: { type: 'string' },
	viewpoint: { type: 'string' },
	frames: { type: 'string' },
	every: { type: 'string' },
	click: { type: 'string' },
	paths: { type: 'string' },
	labels: { type: 'string' },
	cols: { type: 'string' },
	width: { type: 'string' },
	title: { type: 'string' },
	clean: { type: 'boolean' },
	help: { type: 'boolean', short: 'h' }
};

// ---- the commands -------------------------------------------------------------

const COMMANDS = {
	shot: {
		usage: 'shot <url-or-path> [--size desktop|tablet|phone|all]',
		about: 'Screenshot a page once its panorama (if any) has loaded.',
		async run(ctx, [target = '/']) {
			await ctx.eachSize(async (page, size) => {
				await goto(page, ctx.url(target));
				await ctx.pano(page, size);
				await park(page);
				await ctx.shot(page, `shot-${slug(target)}-${size}.png`);
			});
		}
	},

	view: {
		usage: 'view <viewpoint> [--yaw <deg> [--pitch <deg>] | --hotspot <slug>] [--turn <px>] [--fov <deg>] [--name <file-tag>] [--size ...]',
		about: 'Screenshot a viewpoint, optionally aimed at a compass bearing or a hotspot, zoomed, or turned by dragging.',
		async run(ctx, [vp]) {
			if (!vp) throw new Usage('view needs a viewpoint (office, bookshelf, desk, window, entrance)');
			const { yaw, pitch, hotspot, fov } = ctx.opts;
			if (yaw && hotspot) throw new Usage('view takes --yaw or --hotspot, not both');
			for (const [k, v] of Object.entries({ yaw, pitch, fov })) if (v != null && !Number.isFinite(Number(v))) throw new Usage(`--${k} must be a number of degrees`);
			const q = new URLSearchParams();
			if (hotspot) q.set('h', hotspot);
			if (yaw != null) q.set('yaw', yaw);
			if (pitch != null) q.set('pitch', pitch);
			if (fov) q.set('fov', fov);
			const route = `/${ctx.opts.space}/${vp}${q.size ? `?${q}` : ''}`;
			const dx = Number(ctx.opts.turn ?? 0);
			const name = ctx.opts.name ?? [vp, hotspot, yaw != null && `y${yaw}`, pitch != null && `p${pitch}`, fov && `fov${fov}`, dx && `t${dx}`].filter(Boolean).join('-');
			await ctx.eachSize(async (page, size) => {
				await goto(page, ctx.url(route));
				await ctx.pano(page, size);
				if (dx) {
					await turn(page, dx);
					await ctx.pano(page, size, 'after turn');
				}
				await park(page);
				await ctx.shot(page, `view-${name}-${size}.png`);
				ctx.check(`${size}: on ${vp}`, (await page.evaluate(() => location.pathname)).endsWith(`/${vp}`));
			});
		}
	},

	closeup: {
		usage: 'closeup <hotspot title or slug> [--from <viewpoint>] [--size ...]',
		about: 'Click a hotspot pin, wait for the flight into its close-up, then open "Close-ups and 3D" (or a book) if it has one.',
		async run(ctx, [name]) {
			if (!name) throw new Usage('closeup needs a hotspot title or slug, e.g. "The display" or bookshelf');
			const space = await ctx.space();
			const hs = space?.hotspots.find((h) => h.slug === name || h.title.toLowerCase() === name.toLowerCase());
			const title = hs?.title ?? name;
			const from = ctx.opts.from ?? space?.viewpoints[0]?.slug ?? 'office';
			// ?h= turns to face the pin, so it's on screen for a real click.
			const route = `/${ctx.opts.space}/${from}${hs ? `?h=${hs.slug}` : ''}`;
			const pin = `.hotspot button.badge[aria-label="${title.replace(/"/g, '\\"')}"]`;
			const tag = slug(hs?.slug ?? name);
			await ctx.eachSize(async (page, size) => {
				await goto(page, ctx.url(route));
				await ctx.pano(page, size);
				if (!(await page.$(pin))) return ctx.check(`${size}: pin "${title}" on ${from}`, false, 'not found (hidden hotspot?)');
				await park(page);
				await ctx.shot(page, `closeup-${tag}-${size}-0-before.png`);
				// A real click if we can reach it; a DOM click otherwise (and say so).
				const real = await onScreen(page, pin);
				if (real) await press(page, pin);
				else await page.$eval(pin, (b) => b.click());
				ctx.note(`${size}: ${real ? 'clicked' : 'DOM-clicked (off screen)'} "${title}"`);
				const bar = await waitFor(page, () => document.querySelector('.focus-bar')?.textContent.trim().replace(/\s+/g, ' '), 10000);
				ctx.check(`${size}: close-up bar`, !!bar, bar ?? 'no .focus-bar after 10 s');
				await sleep(500); // let the flight begin before waiting for it to end
				await ctx.pano(page, size, 'after flight');
				await park(page);
				ctx.note(`${size}: now at ${await page.evaluate(() => location.pathname + location.search)}`);
				await ctx.shot(page, `closeup-${tag}-${size}-1-closeup.png`);
				// Then whatever the close-up offers: the detail panel, or (bookshelf) a book.
				const panel = () => !!document.querySelector('aside.panel, .panel[role=dialog]');
				if (await page.$('.focus-bar .more')) {
					await press(page, '.focus-bar .more');
					ctx.check(`${size}: "Close-ups and 3D" panel`, await waitFor(page, panel, 5000));
					await sleep(1500); // panel slides in, model loads
					await ctx.shot(page, `closeup-${tag}-${size}-2-panel.png`);
				} else if (await page.$('.sr-only button')) {
					// The books' real targets are outlines in the panorama; their sr-only twins are easier to hit.
					const book = await page.$eval('.sr-only button', (b) => (b.click(), b.textContent.trim()));
					ctx.check(`${size}: book panel for "${book}"`, await waitFor(page, panel, 5000));
					await sleep(1500);
					await ctx.shot(page, `closeup-${tag}-${size}-2-book.png`);
				} else ctx.note(`${size}: nothing more to open in this close-up`);
			});
		}
	},

	minimap: {
		usage: 'minimap [--size ...]',
		about: 'Grow the minimap (hover on desktop, first tap on phone), visit every viewpoint through it, check it closes.',
		async run(ctx) {
			const space = await ctx.space();
			if (!space) throw new Error('could not load space.json for the viewpoint list');
			const state = (page) =>
				page.evaluate(() => ({ open: !!document.querySelector('.minimap.open'), path: location.pathname, disc: Math.round(document.querySelector('.disc')?.getBoundingClientRect().width ?? 0) }));
			await ctx.eachSize(async (page, size) => {
				const { width, height, touch } = page.size;
				await goto(page, ctx.url(`/${ctx.opts.space}`));
				await ctx.pano(page, size);
				const closed = await state(page);
				// Order: everywhere else, then back to the start.
				// (/<space> itself shows the first viewpoint without changing the URL.)
				const start = Math.max(0, space.viewpoints.findIndex((v) => closed.path.endsWith(`/${v.slug}`)));
				const order = [...space.viewpoints.slice(start + 1), ...space.viewpoints.slice(0, start + 1)];
				for (const [i, v] of order.entries()) {
					const mark = `g[aria-label="Go to ${v.title}"] .mark`;
					if (touch) {
						// First tap only opens the map; the second goes.
						await press(page, mark);
						await sleep(600);
						const s = await state(page);
						if (i === 0) {
							ctx.check(`${size}: first tap opens without moving`, s.open && s.path === closed.path, `disc ${closed.disc} -> ${s.disc}px`);
							await ctx.shot(page, `minimap-${size}-open.png`);
						}
					} else {
						await hover(page, '.disc');
						if (i === 0) {
							// Filmstrip of the grow, cropped to the bottom-left corner.
							const clip = { x: 0, y: height - 420, width: Math.min(460, width), height: 420 };
							await filmstrip(page, (n) => ctx.file(`minimap-${size}-grow-${n}.png`), 4, 80, { clip });
							await sleep(400);
							const s = await state(page);
							ctx.check(`${size}: hover grows it`, s.open, `disc ${closed.disc} -> ${s.disc}px`);
							await ctx.shot(page, `minimap-${size}-open.png`);
						} else await sleep(500);
					}
					await press(page, mark);
					if (!touch) await page.mouse.move(width - 200, 150);
					await sleep(500); // let the walk begin before waiting for it to end
					await ctx.pano(page, size, `at ${v.slug}`);
					const s = await state(page);
					ctx.check(`${size}: minimap -> ${v.slug}`, s.path.endsWith(`/${v.slug}`), s.path);
					await ctx.shot(page, `minimap-${size}-arrive-${i}-${v.slug}.png`);
				}
				// Leaving (or tapping outside) shrinks it again.
				if (touch) await page.touchscreen.tap(width / 2, 120);
				else await page.mouse.move(width - 300, 200);
				await sleep(700);
				ctx.check(`${size}: closes again`, !(await state(page)).open);
			});
		}
	},

	edges: {
		usage: 'edges [--viewpoint <slug>] [--size ...]',
		about: 'At each viewpoint push the view to its left and right yaw limits (and look down at the right one).',
		async run(ctx) {
			const space = await ctx.space();
			const vps = ctx.opts.viewpoint ? [ctx.opts.viewpoint] : (space?.viewpoints.map((v) => v.slug) ?? ['office', 'bookshelf', 'desk', 'window', 'entrance']);
			await ctx.eachSize(async (page, size) => {
				const push = async (dx, dy, times) => {
					for (let n = 0; n < times; n++) {
						await turn(page, dx, dy, { step: Math.max(Math.abs(dx), Math.abs(dy)) / 10 });
						await sleep(300);
					}
				};
				// Drags scale with the screen so they stay on it; enough of them to hit any limit.
				const dx = Math.round(page.size.width * 0.35);
				for (const vp of vps) {
					await goto(page, ctx.url(`/${ctx.opts.space}/${vp}`));
					await ctx.pano(page, size, vp);
					for (const [d, side] of [[dx, 'left'], [-dx, 'right']]) {
						await push(d, 0, Math.ceil(4000 / dx));
						await ctx.pano(page, size, `${vp} ${side}`);
						await park(page);
						await ctx.shot(page, `edges-${vp}-${side}-${size}.png`);
					}
					await push(0, -Math.round(page.size.height * 0.4), 3); // dragging up looks down
					await ctx.pano(page, size, `${vp} right, down`);
					await ctx.shot(page, `edges-${vp}-right-down-${size}.png`);
				}
			});
		}
	},

	music: {
		usage: 'music [--viewpoint <slug>] [--frames N] [--every ms] [--size ...]',
		about: 'Play the Spotify embed, filmstrip the speaker ripples, pause, and check the ripples canvas empties.',
		async run(ctx) {
			const frames = Number(ctx.opts.frames ?? 8);
			const every = Number(ctx.opts.every ?? 400);
			const vp = ctx.opts.viewpoint ?? '';
			await ctx.eachSize(async (page, size) => {
				await goto(page, ctx.url(`/${ctx.opts.space}${vp && `/${vp}`}`));
				await ctx.pano(page, size);
				// The player normally docks on load; older builds needed the speaker pin.
				if (!(await page.$('.music iframe'))) await press(page, '.badge.play');
				const frame = await pollFrame(page, 20000);
				if (!ctx.check(`${size}: Spotify embed loaded`, !!frame)) return;
				const button = '[data-testid="play-pause-button"]';
				const ready = await frame.waitForSelector(button, { timeout: 15000 }).catch(() => null);
				if (!ctx.check(`${size}: play button`, !!ready)) return;
				const toggle = () => frame.evaluate((sel) => { const b = document.querySelector(sel); b.click(); return b.getAttribute('aria-label'); }, button);
				await park(page);
				await ctx.shot(page, `music-${size}-0-idle.png`);
				ctx.note(`${size}: pressed "${await toggle()}"`);
				const strip = await filmstrip(page, (n) => ctx.file(`music-${size}-play-${n}.png`), frames, every, { probe: () => inkPixels(page, RIPPLES) });
				const peak = Math.max(0, ...strip.map((f) => f.probe ?? 0));
				ctx.check(`${size}: ripples drawn while playing`, peak > 0, `peak ${peak} px`);
				ctx.note(`${size}: pressed "${await toggle()}"`);
				// Ripples fade out over a couple of seconds; give them up to 8.
				let left = null;
				for (let t = 0; t < 8000 && left !== 0; t += 500) {
					await sleep(500);
					left = await inkPixels(page, RIPPLES);
				}
				ctx.check(`${size}: ripples canvas empty after pause`, left === 0, `${left} px left`);
				await ctx.shot(page, `music-${size}-9-paused.png`);
				ctx.files.push(await contactSheet(ctx.browser, strip.map((f) => f.file), {
					out: ctx.file(`music-${size}-sheet.png`), labels: strip.map((f) => `+${f.t} ms, ripples ${f.probe} px`), title: `music ${size}: playing`
				}));
			});
		}
	},

	filmstrip: {
		usage: 'filmstrip <url-or-path> [--frames N] [--every ms] [--turn px | --click <selector>] [--size ...]',
		about: 'Record the screen during a drag or after a click (or idle) to judge smoothness; samples N frames into a contact sheet.',
		async run(ctx, [target = `/${ctx.opts.space}`]) {
			const frames = Number(ctx.opts.frames ?? 12);
			const every = Number(ctx.opts.every ?? 100);
			const dx = Number(ctx.opts.turn ?? 0);
			await ctx.eachSize(async (page, size) => {
				await goto(page, ctx.url(target));
				await ctx.pano(page, size);
				await park(page);
				const action = async () => {
					if (dx) await turn(page, dx, 0, { step: 15 });
					else if (ctx.opts.click) ctx.check(`${size}: click ${ctx.opts.click}`, await press(page, ctx.opts.click));
				};
				const all = await screencast(page, frames * every, action);
				if (!ctx.check(`${size}: screencast frames`, all.length > 0, all.length)) return;
				// What was on screen at each tick: the latest frame drawn by then.
				const picked = Array.from({ length: frames }, (_, i) => all.findLast((f) => f.t <= i * every) ?? all[0]);
				// Gaps between drawn frames: a long one during motion is a visible hitch.
				const gaps = all.slice(1).map((f, i) => f.t - all[i].t);
				const span = all.at(-1).t || 1;
				ctx.note(`${size}: ${all.length} frames drawn in ${span} ms (~${Math.round((all.length * 1000) / span)} fps), longest gap ${Math.max(0, ...gaps)} ms`);
				const tag = `filmstrip-${slug(target)}-${size}`;
				const files = picked.map((f, i) => {
					const file = ctx.file(`${tag}-${String(i).padStart(2, '0')}.jpg`);
					fs.writeFileSync(file, f.jpeg);
					return file;
				});
				ctx.files.push(...files);
				ctx.files.push(await contactSheet(ctx.browser, files, {
					out: ctx.file(`${tag}-sheet.png`), labels: picked.map((f, i) => `${i}  tick ${i * every} ms, frame @${f.t} ms`), cols: 4, title: `${target} (${size})`
				}));
			});
		}
	},

	smoke: {
		usage: 'smoke [--base https://famousdesks.com] [--paths /,/jobs-room/desk] [--size ...]',
		about: 'Load the home page and a deep link; check tiles load, viewpoints render, no failed requests or page errors.',
		async run(ctx) {
			const paths = (ctx.opts.paths ?? '/,/jobs-room/desk').split(',');
			await ctx.eachSize(async (page, size) => {
				for (const p of paths) {
					await goto(page, ctx.url(p));
					const pano = await ctx.pano(page, size, p);
					const info = await page.evaluate(() => ({
						path: location.pathname,
						name: document.querySelector('.name')?.textContent.trim(),
						viewpoints: document.querySelectorAll('.vp').length,
						pins: document.querySelectorAll('.hotspot button.badge').length,
						player: !!document.querySelector('.music iframe')
					}));
					ctx.note(`${size} ${p}: ${JSON.stringify({ ...info, pano: pano.pano, ms: pano.ms })}`);
					ctx.check(`${size} ${p}: minimap viewpoints`, info.viewpoints > 0, String(info.viewpoints));
					await park(page);
					await ctx.shot(page, `smoke-${slug(p)}-${size}.png`);
				}
			});
		}
	},

	sheet: {
		usage: 'sheet <img...> [--out file.png] [--labels "a,b,..."] [--cols N] [--width px] [--title text]',
		about: 'Compose images into a labelled contact sheet (e.g. a render next to its reference photo); "-" leaves a cell empty.',
		async run(ctx, args) {
			if (!args.length) throw new Usage('sheet needs at least one image');
			const images = args.map((f) => (f === '-' ? null : f));
			const missing = images.filter((f) => f && !fs.existsSync(f));
			if (missing.length) throw new Usage(`no such image: ${missing.join(', ')}`);
			const out = ctx.opts.out ?? path.join(HERE, 'out', 'sheet.png');
			ctx.files.push(await contactSheet(ctx.browser, images, {
				out,
				labels: ctx.opts.labels?.split(',') ?? [],
				cols: ctx.opts.cols && Number(ctx.opts.cols),
				width: Number(ctx.opts.width ?? 1800),
				title: ctx.opts.title
			}));
		}
	}
};

/** The Spotify embed is a cross-origin iframe: find its frame once it has loaded. */
async function pollFrame(page, timeout) {
	for (const end = Date.now() + timeout; Date.now() < end; await sleep(250)) {
		const f = page.frames().find((fr) => fr.url().includes(SPOTIFY));
		if (f) return f;
	}
	return null;
}

// ---- running a command --------------------------------------------------------

class Usage extends Error {}

function help() {
	console.log('usage: node tools/check/check.mjs <command> [options]\n');
	for (const c of Object.values(COMMANDS)) console.log(`  ${c.usage}\n      ${c.about}`);
	console.log(`
common options:
  --base <url>     site to test (default http://localhost:5180)
  --size <name>    ${Object.keys(SIZES).join(', ')}, a comma list, or all (default desktop)
  --out <dir>      output root (default tools/check/out); files go in <dir>/<command>/
  --clean          empty <dir>/<command>/ first
  --space <slug>   which space (default jobs-room)`);
}

async function main() {
	// parseArgs rejects "--turn -500" as ambiguous; negative numbers are common here, so glue them on.
	const argv = [];
	for (const a of process.argv.slice(2)) {
		const prev = argv.at(-1);
		if (/^-\d/.test(a) && /^--\w+$/.test(prev ?? '')) argv[argv.length - 1] = `${prev}=${a}`;
		else argv.push(a);
	}
	const { values: opts, positionals } = parseArgs({ args: argv, options: OPTIONS, allowPositionals: true });
	const [name, ...args] = positionals;
	if (!name || opts.help || name === 'help') return help(), 0;
	const command = COMMANDS[name];
	if (!command) throw new Usage(`unknown command "${name}"`);

	const base = opts.base.replace(/\/$/, '');
	const origin = new URL(base).origin;
	// Each command writes to its own folder; --clean empties it first so stale frames can't mislead.
	const dir = name === 'sheet' ? null : path.join(opts.out ?? path.join(HERE, 'out'), name);
	if (dir && opts.clean) fs.rmSync(dir, { recursive: true, force: true });
	const file = dir ? outDir(dir) : (n) => n;
	const checks = [];
	const problems = { pageErrors: [], consoleErrors: [], failed: [] };
	const { browser, close } = await launch({ autoplay: name === 'music' });

	const ctx = {
		opts, browser, files: [], file,
		url: (t) => (/^https?:/.test(t) ? t : base + (t.startsWith('/') ? t : `/${t}`)),
		note: (s) => console.log(`  ${s}`),
		check(label, ok, detail) {
			checks.push({ label, ok: !!ok, ...(detail != null && { detail: String(detail) }) });
			console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail != null ? ` (${detail})` : ''}`);
			return !!ok;
		},
		async shot(page, n, clip) {
			ctx.files.push(await shot(page, file(n), clip));
		},
		/** Wait for the view to stop moving, then for its tiles; recorded as a check. */
		async pano(page, size, where = '') {
			const still = await settle(page);
			const r = await waitForPano(page);
			const detail = `${r.pano}; still after ${still ?? '>8000'} ms, tiles after ${r.ms} ms`;
			ctx.check(`${size}: panorama loaded${where && ` (${where})`}`, r.ok, detail);
			return r;
		},
		/** space.json for --space, from the site itself (null if it isn't served). */
		async space() {
			if (ctx._space === undefined) {
				ctx._space = await fetch(`${base}/spaces/${opts.space}/space.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
			}
			return ctx._space;
		},
		/** Run fn(page, sizeName) once per --size, each in a fresh page, gathering its problems. */
		async eachSize(fn) {
			for (const size of sizeNames(opts.size ?? 'desktop')) {
				console.log(`[${size}]`);
				const page = await openPage(browser, size, origin);
				try {
					await fn(page, size);
				} catch (e) {
					ctx.check(`${size}: ran without throwing`, false, e.message.split('\n')[0]);
				}
				for (const k of Object.keys(problems)) problems[k].push(...page.problems[k].map((s) => `[${size}] ${s}`));
				await page.close();
			}
		}
	};

	console.log(`${name} ${args.join(' ')}`.trim() + `  (base ${base}${dir ? `, out ${path.relative(process.cwd(), dir) || '.'}` : ''})`);
	try {
		await command.run(ctx, args);
	} finally {
		await close();
	}

	for (const [k, label] of [['failed', 'failed requests'], ['pageErrors', 'page errors'], ['consoleErrors', 'console errors (not fatal)']]) {
		console.log(`${label}: ${problems[k].length ? '\n  ' + problems[k].join('\n  ') : 'none'}`);
	}
	const failedChecks = checks.filter((c) => !c.ok);
	const ok = !failedChecks.length && !problems.failed.length && !problems.pageErrors.length;
	console.log(`${ok ? 'PASS' : 'FAIL'}: ${checks.length - failedChecks.length}/${checks.length} checks, ${ctx.files.length} files`);
	// The machine-readable line: always last, always one line of JSON.
	console.log(JSON.stringify({
		command: name, args, base, ok,
		checks: { passed: checks.length - failedChecks.length, failed: failedChecks.map((c) => c.label + (c.detail ? `: ${c.detail}` : '')) },
		failedRequests: problems.failed, pageErrors: problems.pageErrors, consoleErrors: problems.consoleErrors.length,
		files: ctx.files
	}));
	return ok ? 0 : 1;
}

main().then(
	(code) => process.exit(code),
	(e) => {
		const usage = e instanceof Usage || e.code?.startsWith('ERR_PARSE_ARGS');
		console.error(usage ? `${e.message}\n` : e);
		if (usage) help();
		process.exit(usage ? 2 : 1);
	}
);
