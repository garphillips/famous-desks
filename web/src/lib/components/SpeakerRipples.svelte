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

	// Like rings on water: one leaves the speaker every EVERY seconds and spreads to REACH metres over LIFE seconds.
	const EVERY = 1.1;
	const LIFE = 4.2;
	const REACH = 1.8;
	const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

	let canvas: HTMLCanvasElement;
	let rings: number[] = [];
	let lastEmit = -Infinity;
	let frame = 0;

	// eases out like a ripple: quick off the speaker, slowing as it spreads
	const spread = (u: number) => 1 - Math.pow(1 - u, 2.2);

	function draw(now: number) {
		frame = 0;
		const t = now / 1000;
		if (playing && source && t - lastEmit > EVERY) {
			lastEmit = t;
			rings.push(t);
		}
		rings = rings.filter((born) => t - born < LIFE);

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
			for (const born of rings) {
				const u = (t - born) / LIFE;
				const r = (0.04 + REACH * spread(u)) * scale;
				// in quickly, then thinning and fading as it widens
				const alpha = Math.min(u / 0.08, 1) * Math.pow(1 - u, 1.6);
				ctx.beginPath();
				ctx.arc(at.x, at.y, r, 0, Math.PI * 2);
				ctx.lineWidth = Math.max(2, r * 0.18);
				ctx.strokeStyle = `rgba(232, 182, 96, ${0.16 * alpha})`;
				ctx.stroke();
				ctx.lineWidth = Math.max(1, 2.4 * (1 - u));
				ctx.strokeStyle = `rgba(255, 226, 160, ${0.75 * alpha})`;
				ctx.stroke();
			}
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
