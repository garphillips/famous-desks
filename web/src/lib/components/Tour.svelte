<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { PanoViewer } from '$lib/viewer/PanoViewer';
	import { spaceUrl, type Hotspot, type Space } from '$lib/types';
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
		if (!slug || loading || !viewer) return;
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

	// Load the panorama whenever the viewpoint changes.
	$effect(() => {
		const v = viewpoint;
		if (!viewer) return;
		untrack(() => {
			loading = true;
			pinned = peek = null;
			detail = null;
		});
		viewer
			.setPanorama(spaceUrl(space.slug, v.pano))
			.then(() => {
				const focus = page.url.searchParams.get('h');
				const target = focus ? space.hotspots.find((h) => h.slug === focus && h.views[v.slug]) : null;
				if (target) {
					viewer!.lookAt(target.views[v.slug].yaw, Math.max(-20, Math.min(20, target.views[v.slug].pitch)));
					pinned = target.slug;
				} else {
					viewer!.lookAt(v.initialYaw);
				}
			})
			.catch((err) => console.error(`Couldn't load panorama for ${v.slug}`, err))
			.finally(() => (loading = false));
	});

	function goToViewpoint(slug: string) {
		if (slug === viewpoint.slug) return;
		goto(`/${space.slug}/${slug}`, { replaceState: true, noScroll: true, keepFocus: true });
	}

	function openDetail(h: Hotspot) {
		if (h.kind === 'door') {
			if (h.target) goto(`/${h.target}`);
			return;
		}
		const { yaw, pitch } = h.views[viewpoint.slug];
		detailImage = viewer?.snapshot(yaw, pitch, 40, 840, 630) ?? '';
		detail = h;
		pinned = null;
	}
</script>

<div class="tour">
	<canvas
		bind:this={canvas}
		class:loading
		tabindex="0"
		aria-label="Panorama of {space.title}, {viewpoint.title}. Drag or use arrow keys to look around; plus and minus to zoom."
	></canvas>

	<div class="markers">
		{#each markers as m (m.hotspot.slug)}
			{#if m.visible && !loading}
				<HotspotMarker
					hotspot={m.hotspot}
					x={m.x}
					y={m.y}
					open={openSlug === m.hotspot.slug}
					thumbnail={thumbnails[thumbKey(m.hotspot)] ?? ''}
					onpeek={() => (peek = m.hotspot.slug)}
					onunpeek={() => (peek = null)}
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

	@media (max-width: 760px) {
		.bottom {
			grid-template-columns: 1fr;
			justify-items: center;
			padding: 16px;
			gap: 12px;
		}
		.left {
			justify-self: start;
		}
		.right {
			display: none;
		}
	}
</style>
