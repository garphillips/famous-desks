<script lang="ts">
	import Icon from './Icon.svelte';
	import type { FloorPlan, Viewpoint } from '$lib/types';

	let {
		plan,
		viewpoints,
		current,
		yaw,
		hfov,
		onselect,
		onzoom
	}: {
		plan: FloorPlan;
		viewpoints: Viewpoint[];
		current: string;
		yaw: number;
		hfov: number;
		onselect: (slug: string) => void;
		onzoom: (direction: 1 | -1) => void;
	} = $props();

	const CONE_RADIUS = 1.8;

	// Room metres -> SVG units: same scale, y flipped so north is up.
	const sx = (x: number) => x;
	const sy = (y: number) => -y;

	const t = $derived(plan.wallThickness);
	const W = $derived(plan.width);
	const D = $derived(plan.depth);
	// Fit the whole room (corners included) inside the circle.
	const view = $derived(Math.hypot(W + 2 * t, D + 2 * t) + 0.1);

	function openingRect(o: FloorPlan['openings'][number]) {
		const a0 = o.center - o.width / 2;
		switch (o.wall) {
			case 'N':
				return { x: a0, y: -(D / 2 + t), w: o.width, h: t };
			case 'S':
				return { x: a0, y: D / 2, w: o.width, h: t };
			case 'E':
				return { x: W / 2, y: -(o.center + o.width / 2), w: t, h: o.width };
			case 'W':
				return { x: -W / 2 - t, y: -(o.center + o.width / 2), w: t, h: o.width };
		}
	}

	const here = $derived(viewpoints.find((v) => v.slug === current));

	function cone(px: number, py: number, yawDeg: number, fovDeg: number) {
		const span = Math.min(fovDeg, 179);
		const a0 = ((yawDeg - span / 2) * Math.PI) / 180;
		const a1 = ((yawDeg + span / 2) * Math.PI) / 180;
		const p = (a: number) => `${sx(px) + CONE_RADIUS * Math.sin(a)} ${sy(py) - CONE_RADIUS * Math.cos(a)}`;
		return `M ${sx(px)} ${sy(py)} L ${p(a0)} A ${CONE_RADIUS} ${CONE_RADIUS} 0 0 1 ${p(a1)} Z`;
	}

	function onKey(e: KeyboardEvent, slug: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			onselect(slug);
		}
	}
</script>

<div class="minimap">
	<div class="disc">
		<svg viewBox="{-view / 2} {-view / 2} {view} {view}" role="group" aria-label="Floor plan">
			<defs>
				<radialGradient id="cone-fill" cx="0" cy="0" r={CONE_RADIUS} gradientUnits="userSpaceOnUse"
					gradientTransform={here ? `translate(${sx(here.position[0])} ${sy(here.position[1])})` : ''}>
					<stop offset="0" style="stop-color: var(--accent); stop-opacity: 0.75" />
					<stop offset="1" style="stop-color: var(--accent); stop-opacity: 0" />
				</radialGradient>
			</defs>

			<!-- walls: outer and inner outline, openings cut through -->
			<rect class="wall" x={-W / 2 - t} y={-D / 2 - t} width={W + 2 * t} height={D + 2 * t} />
			<rect class="wall" x={-W / 2} y={-D / 2} width={W} height={D} />
			{#each plan.openings as o, i (i)}
				{@const r = openingRect(o)}
				<rect class="cut" x={r.x} y={r.y} width={r.w} height={r.h} />
				{#if o.kind === 'window'}
					{#if r.w > r.h}
						<line class="glass" x1={r.x} x2={r.x + r.w} y1={r.y + r.h / 2} y2={r.y + r.h / 2} />
					{:else}
						<line class="glass" y1={r.y} y2={r.y + r.h} x1={r.x + r.w / 2} x2={r.x + r.w / 2} />
					{/if}
				{/if}
			{/each}

			{#each plan.items as item (item.name)}
				<polygon class="item" points={item.points.map(([x, y]) => `${sx(x)},${sy(y)}`).join(' ')} />
			{/each}

			{#if here}
				<path class="cone" d={cone(here.position[0], here.position[1], yaw, hfov)} />
			{/if}

			{#each viewpoints as v (v.slug)}
				<g
					class="vp"
					class:current={v.slug === current}
					role="button"
					tabindex="0"
					aria-label="Go to {v.title}"
					aria-current={v.slug === current ? 'location' : undefined}
					onclick={() => onselect(v.slug)}
					onkeydown={(e) => onKey(e, v.slug)}
				>
					<circle class="hit" cx={sx(v.position[0])} cy={sy(v.position[1])} r="0.35" />
					<circle class="mark" cx={sx(v.position[0])} cy={sy(v.position[1])} r={v.slug === current ? 0.16 : 0.11} />
				</g>
			{/each}
		</svg>
	</div>
	<div class="zoom">
		<button onclick={() => onzoom(1)} aria-label="Zoom in"><Icon name="plus" size={16} /></button>
		<button onclick={() => onzoom(-1)} aria-label="Zoom out"><Icon name="minus" size={16} /></button>
	</div>
</div>

<style>
	.minimap {
		display: flex;
		align-items: flex-end;
		gap: 10px;
	}
	.disc {
		width: 156px;
		height: 156px;
		border-radius: 50%;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid var(--line);
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
		overflow: hidden;
		padding: 4px;
	}
	svg {
		width: 100%;
		height: 100%;
		display: block;
		overflow: visible;
	}
	.wall,
	.item,
	.glass {
		fill: none;
		vector-effect: non-scaling-stroke;
	}
	.wall {
		stroke: var(--ink);
		stroke-width: 1.2;
		opacity: 0.9;
	}
	.cut {
		fill: var(--panel-solid);
	}
	.glass {
		stroke: var(--ink-soft);
		stroke-width: 1;
	}
	.item {
		stroke: var(--ink-faint);
		stroke-width: 0.9;
	}
	.cone {
		fill: url(#cone-fill);
	}
	.vp {
		cursor: pointer;
		outline: none;
	}
	.vp .hit {
		fill: transparent;
	}
	.vp .mark {
		fill: var(--ink-soft);
		transition: fill 150ms ease;
	}
	.vp:hover .mark,
	.vp:focus-visible .mark {
		fill: var(--ink);
	}
	.vp.current .mark {
		fill: var(--accent);
		stroke: var(--panel-solid);
		stroke-width: 0.05;
	}
	.vp:focus-visible .hit {
		stroke: var(--accent);
		stroke-width: 0.04;
	}
	.zoom {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-bottom: 14px;
	}
	.zoom button {
		width: 34px;
		height: 34px;
		border-radius: 50%;
		border: 1px solid var(--line);
		background: var(--panel);
		backdrop-filter: var(--blur);
		display: grid;
		place-items: center;
		cursor: pointer;
		transition: border-color 150ms ease;
	}
	.zoom button:hover {
		border-color: var(--ink-soft);
	}

	@media (max-width: 600px) {
		.disc {
			width: 112px;
			height: 112px;
			padding: 6px;
		}
		.zoom {
			display: none;
		}
	}
</style>
