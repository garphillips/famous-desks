#!/usr/bin/env node
// Preview a room change: draft-render the viewpoints you care about, screenshot the
// comparison views listed in blender/rooms/<room>.views.json, and put each beside its
// reference photo on one contact sheet. Run it through scripts/preview.sh; --help for options.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHECK = path.join(ROOT, 'tools/check/check.mjs');
const OUT = path.join(ROOT, 'tools/check/out/preview'); // gitignored: the photos are private

const USAGE = `usage: scripts/preview.sh <room> [viewpoint,...] [options]

Draft-renders the viewpoints the chosen views use, screenshots each view in the
local site and writes a sheet of each view beside its reference photo.
Views come from blender/rooms/<room>.views.json.

  [viewpoint,...]   only views on these viewpoints (a viewpoint with no views
                    gets one shot at its opening yaw)
  --views a,b       only these views (by name)
  --list            list the room's views and exit
  --no-render       screenshot what content/ holds now (e.g. a "before" sheet)
  --full            render at full quality instead of a draft (slow)
  --restore         afterwards, discard the renders (git checkout content/spaces/<space>)
  --base <url>      use this dev server instead of finding or starting one
  --no-open         don't open the sheet (macOS)
  -h, --help        this help

e.g. scripts/preview.sh jobs_room office,desk
     scripts/preview.sh jobs_room --views bookshelf-east --restore`;

const t0 = Date.now();
const secs = (since) => `${((Date.now() - since) / 1000).toFixed(0)} s`;
const step = (s) => console.log(`\n==> ${s}`);
class Fail extends Error {
	constructor(msg, code = 1) {
		super(msg);
		this.code = code;
	}
}

// ---- options and the views file ---------------------------------------------------

function parse() {
	const { values: o, positionals } = parseArgs({
		allowPositionals: true,
		options: {
			views: { type: 'string' },
			list: { type: 'boolean' },
			'no-render': { type: 'boolean' },
			full: { type: 'boolean' },
			restore: { type: 'boolean' },
			base: { type: 'string' },
			'no-open': { type: 'boolean' },
			help: { type: 'boolean', short: 'h' }
		}
	});
	if (o.help) return console.log(USAGE), process.exit(0);
	const [room, vps, ...extra] = positionals;
	if (!room || extra.length) throw new Fail(USAGE, 2);
	if (o['no-render'] && o.full) throw new Fail('--no-render and --full contradict each other', 2);
	return { o, room, vps: vps ? vps.split(',').filter(Boolean) : [] };
}

function loadViews(room) {
	const file = path.join(ROOT, 'blender/rooms', `${room}.views.json`);
	if (!fs.existsSync(path.join(ROOT, 'blender/rooms', `${room}.py`))) {
		const rooms = fs.readdirSync(path.join(ROOT, 'blender/rooms')).filter((f) => f.endsWith('.py')).map((f) => f.slice(0, -3));
		throw new Fail(`no room "${room}" (blender/rooms has: ${rooms.join(', ')})`, 2);
	}
	if (!fs.existsSync(file)) return { space: room.replace(/_/g, '-'), views: [] };
	const spec = JSON.parse(fs.readFileSync(file, 'utf8'));
	for (const v of spec.views) {
		if (!v.name || !v.viewpoint) throw new Fail(`${path.relative(ROOT, file)}: every view needs a name and a viewpoint`);
		if (v.yaw != null && v.hotspot) throw new Fail(`${path.relative(ROOT, file)}: view "${v.name}" has both yaw and hotspot`);
	}
	return { space: spec.space ?? room.replace(/_/g, '-'), views: spec.views };
}

/** The main checkout's starter/ folder (worktrees share it through the common .git). */
function starterDir() {
	const r = spawnSync('git', ['-C', ROOT, 'rev-parse', '--path-format=absolute', '--git-common-dir'], { encoding: 'utf8' });
	return path.join(r.status === 0 ? path.dirname(r.stdout.trim()) : ROOT, 'starter');
}

function refPath(ref) {
	if (!ref) return null;
	if (ref.startsWith('~/')) return path.join(os.homedir(), ref.slice(2));
	return path.isAbsolute(ref) ? ref : path.join(starterDir(), ref);
}

// ---- rendering ------------------------------------------------------------------------

/** Run blender/pipeline.sh with the Mac kept awake; full log to a file, progress lines to the terminal. */
async function render(room, space, vps, full) {
	const panos = vps.map((vp) => path.join(ROOT, 'content/spaces', space, 'panos', `${vp}.webp`));
	const before = panos.map((f) => (fs.existsSync(f) ? fs.statSync(f).mtimeMs : 0));
	const log = path.join(OUT, `render-${room}.log`);
	const args = [room, ...(full ? [] : ['--draft']), '--only', vps.join(',')];
	step(`Rendering ${full ? 'full-quality' : 'draft'} ${vps.join(', ')} (blender/pipeline.sh ${args.join(' ')}; log ${path.relative(ROOT, log)})`);
	const start = Date.now();
	const out = fs.createWriteStream(log);
	const child = spawn(path.join(ROOT, 'blender/pipeline.sh'), args, { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
	// keep the Mac awake (idle, display and system sleep) until the render exits
	if (process.platform === 'darwin') spawn('caffeinate', ['-ims', '-w', String(child.pid)], { stdio: 'ignore' }).on('error', () => {});
	const tail = [];
	let buf = '';
	const onData = (d) => {
		out.write(d);
		buf += d;
		const lines = buf.split('\n');
		buf = lines.pop();
		for (const line of lines) {
			tail.push(line);
			if (tail.length > 40) tail.shift();
			if (/Rendering panorama|rendered in|waiting for the GPU|Traceback|Error|error:|failed|pipeline\.sh:/.test(line)) console.log(`  ${line.trim()}`);
		}
	};
	child.stdout.on('data', onData);
	child.stderr.on('data', onData);
	const ticker = setInterval(() => console.log(`  ... ${secs(start)}`), 60000);
	const code = await new Promise((resolve) => child.on('close', resolve).on('error', () => resolve(127)));
	clearInterval(ticker);
	out.end();
	const stale = vps.filter((vp, i) => !fs.existsSync(panos[i]) || fs.statSync(panos[i]).mtimeMs <= before[i]);
	if (code !== 0 || stale.length) {
		const last = [...tail, buf].filter((l) => l.trim()).slice(-25);
		console.error(last.length ? `\n  last lines of the log:\n    ${last.join('\n    ')}` : '\n  (pipeline.sh printed nothing)');
		throw new Fail(`render failed after ${secs(start)}: ${code !== 0 ? `pipeline.sh exited ${code}` : `no new panorama for ${stale.join(', ')}`} (full log: ${log})`);
	}
	console.log(`  rendered in ${secs(start)}`);
}

// ---- the dev server -------------------------------------------------------------------

/** A vite already serving this checkout's web/ (found by its working directory), or null. */
function runningServer() {
	const r = spawnSync('lsof', ['-nP', '-a', '-iTCP', '-sTCP:LISTEN', '-c', 'node', '-F', 'pn'], { encoding: 'utf8' });
	if (r.status !== 0) return null;
	let pid = null;
	for (const line of r.stdout.split('\n')) {
		if (line.startsWith('p')) pid = line.slice(1);
		else if (line.startsWith('n') && pid) {
			const port = line.match(/:(\d+)$/)?.[1];
			const cwd = spawnSync('lsof', ['-a', '-p', pid, '-d', 'cwd', '-F', 'n'], { encoding: 'utf8' }).stdout.split('\n').find((l) => l.startsWith('n'))?.slice(1);
			if (port && cwd === path.join(ROOT, 'web')) return `http://localhost:${port}`;
		}
	}
	return null;
}

const freePort = () =>
	new Promise((resolve, reject) => {
		const s = net.createServer().listen(0, '127.0.0.1', () => {
			const { port } = s.address();
			s.close(() => resolve(port));
		});
		s.on('error', reject);
	});

async function responds(url) {
	try {
		return (await fetch(url, { signal: AbortSignal.timeout(3000) })).ok;
	} catch {
		return false;
	}
}

/** Returns { base, stop }: an existing server for this checkout, or one we start (and stop). */
async function devServer(space, base) {
	if (base) return { base: base.replace(/\/$/, ''), stop: () => {} };
	const found = runningServer();
	if (found && (await responds(`${found}/spaces/${space}/space.json`))) {
		console.log(`  using the dev server already running for this checkout at ${found}`);
		return { base: found, stop: () => {} };
	}
	const web = path.join(ROOT, 'web');
	if (!fs.existsSync(path.join(web, 'node_modules/vite'))) throw new Fail('web/node_modules is missing: run `npm ci` in web/ first');
	const port = await freePort();
	const url = `http://localhost:${port}`;
	const log = path.join(OUT, 'vite.log');
	const fd = fs.openSync(log, 'w');
	const child = spawn('npx', ['vite', 'dev', '--port', String(port), '--strictPort'], { cwd: web, stdio: ['ignore', fd, fd], detached: true });
	const stop = () => {
		try {
			process.kill(-child.pid, 'SIGTERM'); // the whole group: npx and vite
		} catch {}
	};
	process.on('exit', stop);
	for (const end = Date.now() + 60000; Date.now() < end; await new Promise((r) => setTimeout(r, 500))) {
		if (child.exitCode != null) throw new Fail(`the dev server exited (${child.exitCode}); see ${log}`);
		if (await responds(`${url}/spaces/${space}/space.json`)) {
			console.log(`  started a dev server for this checkout at ${url}`);
			return { base: url, stop };
		}
	}
	stop();
	throw new Fail(`the dev server didn't respond within 60 s; see ${log}`);
}

// ---- screenshots and the sheet --------------------------------------------------------

/** Run tools/check; returns its final JSON line (or throws with its output). */
function check(args, what) {
	const r = spawnSync('node', [CHECK, ...args], { cwd: ROOT, encoding: 'utf8' });
	const last = r.stdout.trim().split('\n').at(-1);
	let json = null;
	try {
		json = JSON.parse(last);
	} catch {}
	if (!json) throw new Fail(`tools/check ${what} failed:\n${r.stdout}${r.stderr}`);
	return { ...json, output: r.stdout };
}

/** Reference photos are large (up to 17 MB PNGs): a smaller JPEG copy keeps the sheet quick. */
function smallRef(file) {
	const out = path.join(OUT, 'refs', `${path.basename(file).replace(/[^\w.-]+/g, '_')}.jpg`);
	if (fs.existsSync(out) && fs.statSync(out).mtimeMs >= fs.statSync(file).mtimeMs) return out;
	fs.mkdirSync(path.dirname(out), { recursive: true });
	const r = spawnSync('sips', ['-Z', '1600', '-s', 'format', 'jpeg', file, '--out', out], { encoding: 'utf8' });
	return r.status === 0 ? out : file;
}

const clean = (s) => String(s).replace(/,/g, ';'); // tools/check splits --labels on commas

async function main() {
	const { o, room, vps: askedVps } = parse();
	const { space, views: all } = loadViews(room);
	if (o.list) {
		for (const v of all) console.log(`${v.name.padEnd(20)} ${v.viewpoint.padEnd(10)} ${v.hotspot ? `hotspot ${v.hotspot}` : `yaw ${v.yaw ?? '-'} pitch ${v.pitch ?? 0}`}${v.fov ? ` fov ${v.fov}` : ''}  ${v.ref ?? '(no photo)'}`);
		return 0;
	}
	const spaceJson = path.join(ROOT, 'content/spaces', space, 'space.json');
	const known = fs.existsSync(spaceJson) ? JSON.parse(fs.readFileSync(spaceJson, 'utf8')).viewpoints.map((v) => v.slug) : null;

	// Which views, and so which viewpoints to render
	let views = all;
	if (o.views) {
		const names = o.views.split(',').filter(Boolean);
		const unknown = names.filter((n) => !all.some((v) => v.name === n));
		if (unknown.length) throw new Fail(`no view called ${unknown.join(', ')} in blender/rooms/${room}.views.json (have: ${all.map((v) => v.name).join(', ') || 'none'})`, 2);
		views = all.filter((v) => names.includes(v.name));
	}
	if (askedVps.length) {
		views = views.filter((v) => askedVps.includes(v.viewpoint));
		// a viewpoint with no listed view still gets a shot, at its opening yaw
		for (const vp of askedVps) if (!views.some((v) => v.viewpoint === vp)) views.push({ name: vp, viewpoint: vp });
	}
	if (!views.length) throw new Fail(`nothing to preview: blender/rooms/${room}.views.json lists no views (name some viewpoints instead)`, 2);
	const vps = [...new Set(views.map((v) => v.viewpoint))];
	const bad = known ? vps.filter((vp) => !known.includes(vp)) : [];
	if (bad.length) throw new Fail(`no viewpoint ${bad.join(', ')} in ${space} (have: ${known.join(', ')})`, 2);
	for (const v of views) {
		const ref = refPath(v.ref);
		if (ref && !fs.existsSync(ref)) console.log(`  note: reference photo for ${v.name} not found: ${ref}`);
	}

	fs.mkdirSync(OUT, { recursive: true });
	console.log(`Previewing ${room} (${space}): ${views.map((v) => v.name).join(', ')}`);
	if (!o['no-render']) await render(room, space, vps, o.full);

	step('Screenshotting');
	const server = await devServer(space, o.base);
	const shots = [];
	try {
		for (const v of views) {
			const args = ['view', v.viewpoint, '--base', server.base, '--space', space, '--out', OUT, '--name', v.name];
			if (v.yaw != null) args.push('--yaw', String(v.yaw));
			if (v.pitch != null) args.push('--pitch', String(v.pitch));
			if (v.hotspot) args.push('--hotspot', v.hotspot);
			if (v.turn) args.push('--turn', String(v.turn));
			if (v.fov) args.push('--fov', String(v.fov));
			const r = check(args, `view ${v.name}`);
			const file = r.files.find((f) => f.endsWith('.png'));
			const pano = [...r.output.matchAll(/panorama loaded[^(]*\(([^;)]*)/g)].at(-1)?.[1]; // e.g. 3:12/12
			console.log(`  ${r.ok ? 'ok  ' : 'FAIL'} ${v.name}${pano ? ` (${pano})` : ''}${r.ok ? '' : `: ${[...r.checks.failed, ...r.failedRequests, ...r.pageErrors].join('; ')}`}`);
			shots.push({ v, file, ok: r.ok });
		}
	} finally {
		server.stop();
	}

	step('Making the sheet');
	const withRefs = views.some((v) => v.ref);
	const cells = [];
	const labels = [];
	for (const { v, file, ok } of shots) {
		const aim = v.hotspot ? `at ${v.hotspot}` : v.yaw != null ? `yaw ${v.yaw}` : 'opening view';
		cells.push(file ?? '-');
		labels.push(clean(`${v.name}: ${v.viewpoint} ${aim}${v.note ? ` (${v.note})` : ''}${ok ? '' : ' [CHECK FAILED]'}`));
		if (!withRefs) continue;
		const ref = refPath(v.ref);
		const have = ref && fs.existsSync(ref);
		cells.push(have ? smallRef(ref) : '-');
		labels.push(clean(ref ? `${have ? 'photo' : 'MISSING photo'}: ${path.basename(ref)}` : 'no reference photo'));
	}
	const stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');
	const sheet = path.join(OUT, `${space}-${stamp}.png`);
	const quality = o['no-render'] ? 'current content' : o.full ? 'full render' : 'draft render';
	const r = check(['sheet', ...cells, '--out', sheet, '--cols', withRefs ? '2' : '3', '--labels', labels.join(','), '--title', `${space}: ${quality}, ${new Date().toLocaleString()}`], 'sheet');
	if (!r.ok) throw new Fail(`making the sheet failed:\n${r.output}`);
	console.log(`\nSheet: ${sheet}`);
	if (process.platform === 'darwin' && !o['no-open']) spawn('open', [sheet], { stdio: 'ignore', detached: true }).unref();

	// content/ now holds whatever we rendered: say so, or put it back
	const rel = path.join('content/spaces', space);
	if (o.restore) {
		spawnSync('git', ['-C', ROOT, 'checkout', '--', rel, 'content/spaces/index.json'], { stdio: 'inherit' });
		console.log(`\nRestored ${rel} to the committed renders (--restore).`);
	}
	const dirty = spawnSync('git', ['-C', ROOT, 'status', '--porcelain', '--', 'content/'], { encoding: 'utf8' }).stdout.trim();
	if (dirty) {
		console.log(`\n!! content/ differs from the last commit${o['no-render'] ? '' : ` (${quality} of ${vps.join(', ')})`}.`);
		console.log(`!! Before deploying, run the full render (blender/pipeline.sh ${room}), or discard these with`);
		console.log(`!!   git checkout -- ${rel} content/spaces/index.json`);
		console.log('!! scripts/deploy.sh refuses to deploy until then.');
	}
	const failed = shots.filter((s) => !s.ok).map((s) => s.v.name);
	console.log(`\nDone in ${secs(t0)}${failed.length ? `; FAILED views: ${failed.join(', ')}` : ''}.`);
	return failed.length ? 1 : 0;
}

main().then(
	(code) => process.exit(code),
	(e) => {
		console.error(e instanceof Fail ? `\npreview: ${e.message}` : e);
		process.exit(e instanceof Fail ? e.code : 1);
	}
);
