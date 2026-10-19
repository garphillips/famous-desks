<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { PanoViewer, prefersReducedMotion } from '$lib/viewer/PanoViewer';
	import { spaceUrl, type Hotspot, type Space, type Viewpoint } from '$lib/types';
	import TopBar from './TopBar.svelte';
	import HotspotMarker from './HotspotMarker.svelte';
	import Minimap from './Minimap.svelte';
	import SceneBar from './SceneBar.svelte';
	import HintPill from './HintPill.svelte';
	import DetailPanel from './DetailPanel.svelte';

	let { space, viewpointSlug }: { space: Space; viewpointSlug: string } = $props();

	const THUMB_FOV = 24;

	let canvas: HTMLCanvasElement;
	let viewer: PanoViewer | undefined = $state();
	let loading = $state(true);
	let moving = $state(false);
	let showToken = 0;
	let yaw = $state(0);
	let hfov = $state(90);
	let markers: { hotspot: Hotspot; x: number; y: number; visible: boolean }[] = $state([]);
	let peek: string | null = $state(null);
	let pinned: string | null = $state(null);
	let detail: Hotspot | null = $state(null);
	let detailImage = $state('');
	let showHint = $state(true);
	const thumbnails: Record<string, string> = $state({});

	const viewpoint = $derived(
		space.viewpoints.find((v) => v.slug === viewpointSlug) ?? space.viewpoints[0]
	);
	const here = $derived(space.hotspots.filter((h) => h.views[viewpoint.slug]));
	const openSlug = $derived(pinned ?? peek);

	function updateView() {
		if (!viewer) return;
		yaw = viewer.yaw;
		hfov = viewer.hfov;
		markers = here.map((hotspot) => {
			const { yaw, pitch } = hotspot.views[viewpoint.slug];
			return { hotspot, ...viewer!.project(yaw, pitch) };
		});
	}

	const thumbKey = (h: Hotspot) => `${viewpoint.slug}:${h.slug}`;

	// Card thumbnails are cut from the live panorama the first time a card opens.
	$effect(() => {
		const slug = openSlug;
		if (!slug || loading || moving || !viewer) return;
		const h = here.find((x) => x.slug === slug);
		if (!h) return;
		const key = thumbKey(h);
		if (untrack(() => thumbnails[key])) return;
		const { yaw, pitch } = h.views[viewpoint.slug];
		thumbnails[key] = viewer.snapshot(yaw, pitch, THUMB_FOV, 112, 112);
	});

	onMount(() => {
		viewer = new PanoViewer(canvas, {
			onChange: updateView,
			onInteract: () => {
				showHint = false;
				pinned = null;
			}
		});
		return () => viewer?.dispose();
	});

	// Show the panorama whenever the viewpoint changes: step across from the one on
	// screen, or load it plainly on first visit, a new space or a ?h= deep link.
	$effect(() => {
		const v = viewpoint;
		if (!viewer) return;
		untrack(() => show(viewer!, v));
	});

	const panoUrl = (v: Viewpoint) => spaceUrl(space.slug, v.pano);

	function show(viewer: PanoViewer, v: Viewpoint) {
		pinned = peek = null;
		detail = null;
		const token = ++showToken;
		const focus = page.url.searchParams.get('h');
		const target = focus ? space.hotspots.find((h) => h.slug === focus && h.views[v.slug]) : null;
		viewer.settle();
		const from = space.viewpoints.find((x) => panoUrl(x) === viewer.url);
		if (from === v && !target) {
			loading = moving = false;
			return;
		}

		let shown: Promise<unknown>;
		if (from && !target) {
			moving = true;
			// Compass bearing from here to there: x east, y north, clockwise from north.
			const yaw = (Math.atan2(v.position[0] - from.position[0], v.position[1] - from.position[1]) * 180) / Math.PI;
			shown = viewer.transitionTo(panoUrl(v), { yaw, reduced: prefersReducedMotion() });
		} else {
			loading = true;
			shown = viewer.setPanorama(panoUrl(v)).then(() => {
				if (token !== showToken) return;
				if (target) {
					viewer.lookAt(target.views[v.slug].yaw, Math.max(-20, Math.min(20, target.views[v.slug].pitch)));
					pinned = target.slug;
				} else {
					viewer.lookAt(v.initialYaw);
				}
			});
		}
		shown
			.catch((err) => console.error(`Couldn't load panorama for ${v.slug}`, err))
			.finally(() => {
				if (token !== showToken) return;
				loading = moving = false;
				viewer.prefetch(neighbours(v).map(panoUrl));
			});
	}

	/** The nearest viewpoints and the scene bar's previous/next: the likely next moves. */
	function neighbours(v: Viewpoint) {
		const all = space.viewpoints;
		const i = all.indexOf(v);
		const dist = (w: Viewpoint) => Math.hypot(w.position[0] - v.position[0], w.position[1] - v.position[1]);
		const nearest = all.filter((w) => w !== v).sort((a, b) => dist(a) - dist(b));
		const list = [...nearest.slice(0, 2), all[(i + 1) % all.length], all[(i - 1 + all.length) % all.length]];
		return [...new Set(list)].filter((w) => w !== v);
	}

	function goToViewpoint(slug: string) {
		if (slug === viewpoint.slug) return;
		goto(`/${space.slug}/${slug}`, { replaceState: true, noScroll: true, keepFocus: true });
	}

	function openDetail(h: Hotspot) {
		if (h.kind === 'door') {
			if (h.target) goto(h.arrive ? `/${h.target}/${h.arrive}` : `/${h.target}`);
			return;
		}
		const { yaw, pitch } = h.views[viewpoint.slug];
		detailImage = viewer?.snapshot(yaw, pitch, 40, 840, 630) ?? '';
		detail = h;
		pinned = peek = null;
	}
</script>

<div class="tour">
	<canvas
		bind:this={canvas}
		class:loading
		tabindex="0"
		aria-label="Panorama of {space.title}, {viewpoint.title}. Drag or use arrow keys to look around; plus and minus to zoom."
	></canvas>

	<div class="markers" class:hidden={loading || moving}>
		{#each markers as m (m.hotspot.slug)}
			{#if m.visible}
				<HotspotMarker
					hotspot={m.hotspot}
					x={m.x}
					y={m.y}
					open={openSlug === m.hotspot.slug}
					thumbnail={thumbnails[thumbKey(m.hotspot)] ?? ''}
					onpeek={() => (peek = m.hotspot.slug)}
					onunpeek={() => (peek = null)}
					ongrab={(e) => viewer?.grab(e)}
					ontoggle={() => {
						if (pinned === m.hotspot.slug) openDetail(m.hotspot);
						else pinned = m.hotspot.slug;
					}}
					onopen={() => openDetail(m.hotspot)}
				/>
			{/if}
		{/each}
	</div>

	<div class="top">
		<TopBar title={space.title} active="explore" exploreHref="/{space.slug}" />
	</div>

	<div class="bottom">
		<div class="left">
			<Minimap
				plan={space.floorPlan}
				viewpoints={space.viewpoints}
				current={viewpoint.slug}
				{yaw}
				{hfov}
				onselect={goToViewpoint}
				onzoom={(d) => viewer?.zoomBy(d * -8)}
			/>
		</div>
		<div class="center">
			<SceneBar viewpoints={space.viewpoints} current={viewpoint.slug} onselect={goToViewpoint} />
		</div>
		<div class="right">
			{#if showHint}<HintPill />{/if}
		</div>
	</div>

	{#if detail}
		<DetailPanel
			hotspot={detail}
			image={detailImage}
			spaceTitle={space.title}
			onclose={() => {
				detail = null;
				canvas.focus();
			}}
		/>
	{/if}
</div>

<style>
	.tour {
		position: fixed;
		inset: 0;
		overflow: hidden;
		background: var(--bg);
	}
	canvas {
		width: 100%;
		height: 100%;
		display: block;
		cursor: grab;
		touch-action: none;
		outline: none;
		transition:
			opacity 300ms ease,
			filter 300ms ease;
	}
	canvas:active {
		cursor: grabbing;
	}
	canvas.loading {
		opacity: 0.3;
		filter: blur(6px);
	}
	.markers {
		position: absolute;
		inset: 0;
		pointer-events: none;
		transition: opacity 240ms ease;
	}
	.markers.hidden {
		opacity: 0;
		visibility: hidden;
		transition: none;
	}
	.top {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		pointer-events: none;
		background: linear-gradient(rgba(0, 0, 0, 0.35), transparent);
	}
	.top :global(.topbar) {
		pointer-events: none;
	}
	.bottom {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		display: grid;
		grid-template-columns: 1fr auto 1fr;
		align-items: end;
		gap: 16px;
		padding: 24px 28px;
		pointer-events: none;
	}
	.bottom > * {
		pointer-events: auto;
	}
	.right {
		justify-self: end;
	}

	/* Stacked: minimap and hint on one row, scene bar full width below. */
	@media (max-width: 1040px) {
		.bottom {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-areas:
				'left right'
				'center center';
			padding: 16px;
			padding-bottom: max(16px, env(safe-area-inset-bottom));
			gap: 12px;
		}
		.left {
			grid-area: left;
		}
		.right {
			grid-area: right;
			min-width: 0;
		}
		.center {
			grid-area: center;
			justify-self: center;
			min-width: 0;
			max-width: 100%;
		}
	}
</style>
