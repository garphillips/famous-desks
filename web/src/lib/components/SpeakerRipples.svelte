<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { ScreenPoint } from '$lib/viewer/PanoViewer';

	let {
		source,
		playing,
		hidden,
		project,
		focal
	}: {
		/** Where the speaker is from this viewpoint; the ripples spread out from it. */
		source: { yaw: number; pitch: number; distance: number } | null;
		playing: boolean;
		/** Out of the way while the view moves or loads. */
		hidden: boolean;
		project: (yaw: number, pitch: number) => ScreenPoint | undefined;
		/** Screen pixels per radian at the current zoom. */
		focal: () => number;
	} = $props();

	// Soft rings like smoke rings: one leaves the speaker every EVERY seconds and spreads to REACH metres
	// over LIFE seconds, drifting up a little.
	const EVERY = 1.3;
	const LIFE = 5;
	const REACH = 1.7;
	const RISE = 0.25;
	const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

	let canvas: HTMLCanvasElement;
	let rings: { born: number; seed: number }[] = [];

	// One soft puff; each ring is many of them, overlapping into a smoky band.
	const puff = document.createElement('canvas');
	puff.width = puff.height = 64;
	{
		const g = puff.getContext('2d')!;
		const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
		grad.addColorStop(0, 'rgba(250, 222, 168, 1)');
		grad.addColorStop(0.45, 'rgba(232, 190, 120, 0.45)');
		grad.addColorStop(1, 'rgba(216, 170, 100, 0)');
		g.fillStyle = grad;
		g.fillRect(0, 0, 64, 64);
	}
	let lastEmit = -Infinity;
	let frame = 0;

	// eases out like a ripple: quick off the speaker, slowing as it spreads
	const spread = (u: number) => 1 - Math.pow(1 - u, 2.2);

	function draw(now: number) {
		frame = 0;
		const t = now / 1000;
		if (playing && source && t - lastEmit > EVERY) {
			lastEmit = t;
			rings.push({ born: t, seed: Math.random() * Math.PI * 2 });
		}
		rings = rings.filter((r) => t - r.born < LIFE);

		const dpr = Math.min(devicePixelRatio, 2);
		const { clientWidth: cw, clientHeight: ch } = canvas;
		if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
			canvas.width = Math.round(cw * dpr);
			canvas.height = Math.round(ch * dpr);
		}
		const ctx = canvas.getContext('2d')!;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, cw, ch);

		const at = source && project(source.yaw, source.pitch);
		if (source && at?.visible) {
			const scale = focal() / source.distance;
			for (const { born, seed } of rings) {
				const u = (t - born) / LIFE;
				const r = (0.05 + REACH * spread(u)) * scale;
				const cy = at.y - RISE * spread(u) * scale;
				// in gently, then thinning as it widens
				const alpha = Math.min(u / 0.12, 1) * Math.pow(1 - u, 1.5);
				// the band thickens and softens as it spreads
				const band = 5 + r * 0.16;
				const count = Math.min(140, Math.max(18, Math.round((2 * Math.PI * r) / (band * 0.45))));
				for (let k = 0; k < count; k++) {
					const a = (k / count) * Math.PI * 2;
					// a slow, slight wobble, so it stays round but isn't a drawn circle
					const wobble = 1 + 0.035 * Math.sin(3 * a + seed + t * 0.5) + 0.02 * Math.sin(5 * a - seed * 1.7 - t * 0.35);
					// thicker and thinner patches around the ring, like smoke
					const density = 0.65 + 0.35 * Math.sin(2 * a + seed * 2.3 + t * 0.3);
					const size = band * (0.8 + 0.25 * Math.sin(4 * a + seed));
					// about four puffs overlap at any point of the band
					ctx.globalAlpha = 0.34 * alpha * density;
					ctx.drawImage(puff, at.x + Math.cos(a) * r * wobble - size, cy + Math.sin(a) * r * wobble * 0.97 - size, size * 2, size * 2);
				}
			}
			ctx.globalAlpha = 1;
		}

		if (playing || rings.length) frame = requestAnimationFrame(draw);
		else lastEmit = -Infinity;
	}

	$effect(() => {
		if (playing && !reduced && !frame) frame = requestAnimationFrame(draw);
	});

	onDestroy(() => cancelAnimationFrame(frame));
</script>

<canvas bind:this={canvas} class:hidden aria-hidden="true"></canvas>

<style>
	canvas {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		transition: opacity 400ms ease;
	}
	canvas.hidden {
		opacity: 0;
		transition: none;
	}
</style>
