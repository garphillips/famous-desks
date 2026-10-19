<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { PanoViewer, prefersReducedMotion, type PanoSource } from '$lib/viewer/PanoViewer';
	import { ShelfItems, type Panel } from '$lib/viewer/shelfItems';
	import { spaceUrl, type Hotspot, type HotspotItem, type Space, type Viewpoint } from '$lib/types';
	import TopBar from './TopBar.svelte';
	import HotspotMarker from './HotspotMarker.svelte';
	import Minimap from './Minimap.svelte';
	import SceneBar from './SceneBar.svelte';
	import HintPill from './HintPill.svelte';
	import Icon from './Icon.svelte';
	import DetailPanel from './DetailPanel.svelte';
	import BookPanel from './BookPanel.svelte';

	let { space, viewpointSlug }: { space: Space; viewpointSlug: string } = $props();

	const THUMB_FOV = 24;
	const DEFAULT_FOV = 75;
	/** Zooming out this far past a focus view leaves it. */
	const FOCUS_EXIT = 22;

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

	// Focus: zoomed in on a hotspot whose items (books) can be picked.
	let focus: Hotspot | null = $state(null);
	/** True once the zoom-in has landed (so zooming out can leave). */
	let focusReady = false;
	/** The field of view the focus zoomed to (wider than focus.fov on portrait screens). */
	let focusFov = 0;
	let pendingFocus: Hotspot | null = null;
	let shelf: ShelfItems | null = null;
	let hoverItem: HotspotItem | null = $state(null);
	let hoverAt = $state({ x: 0, y: 0 });
	let openItem: HotspotItem | null = $state(null);
	let outlines: { item: HotspotItem; points: string }[] = $state([]);

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
		if (focus && shelf) {
			outlines = (focus.items ?? []).flatMap((item) => {
				const pts = shelf!.outline(item.slug);
				return pts ? [{ item, points: pts.map((p) => `${p.x},${p.y}`).join(' ') }] : [];
			});
			if (focusReady && !openItem && viewer.fov > focusFov + FOCUS_EXIT) leaveFocus(false);
		}
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
			},
			onTap: (e) => {
				if (!focus || !shelf || openItem) return;
				const item = shelf.pick(viewer!.pointerDirection(e.clientX, e.clientY));
				if (item) openBook(item);
			}
		});
		const onResize = () => shelf?.relayout(panelLayout());
		window.addEventListener('resize', onResize);
		return () => {
			window.removeEventListener('resize', onResize);
			shelf?.dispose();
			viewer?.dispose();
		};
	});

	// Show the panorama whenever the viewpoint changes: step across from the one on
	// screen, or load it plainly on first visit, a new space or a ?h= deep link.
	$effect(() => {
		const v = viewpoint;
		if (!viewer) return;
		untrack(() => show(viewer!, v));
	});

	const panoUrl = (v: Viewpoint) => spaceUrl(space.slug, v.pano);

	// The cube-face tiles when the viewpoint has them (?tiles=0 forces the equirect, for comparison).
	function panoSource(v: Viewpoint): PanoSource {
		const t = page.url.searchParams.get('tiles') === '0' ? undefined : v.tiles;
		const tiles = t && { ...t, path: spaceUrl(space.slug, t.path), preview: spaceUrl(space.slug, t.preview) };
		return { url: panoUrl(v), tiles };
	}

	function show(viewer: PanoViewer, v: Viewpoint) {
		pinned = peek = null;
		detail = null;
		if (focus) leaveFocus(false, false);
		const token = ++showToken;
		const linked = page.url.searchParams.get('h');
		const target = linked ? space.hotspots.find((h) => h.slug === linked && h.views[v.slug]) : null;
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
			shown = viewer.transitionTo(panoSource(v), { yaw, reduced: prefersReducedMotion() });
		} else {
			loading = true;
			shown = viewer.setPanorama(panoSource(v)).then(() => {
				if (token !== showToken) return;
				if (target) {
					viewer.lookAt(target.views[v.slug].yaw, Math.max(-20, Math.min(20, target.views[v.slug].pitch)));
					pinned = target.slug;
				} else {
					viewer.lookAt(v.initialYaw);
				}
				// ?fov=<degrees> opens zoomed in (e.g. with ?h= to look closely at a hotspot)
				const fov = Number(page.url.searchParams.get('fov'));
				if (fov) viewer.setFov(fov);
			});
		}
		shown
			.catch((err) => console.error(`Couldn't load panorama for ${v.slug}`, err))
			.finally(() => {
				if (token !== showToken) return;
				loading = moving = false;
				viewer.prefetch(neighbours(v).map(panoSource));
				const next = pendingFocus;
				pendingFocus = null;
				if (next?.focus?.viewpoint === v.slug) startFocus(next);
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
		if (h.focus && h.items?.length) {
			pinned = peek = null;
			if (h.focus.viewpoint === viewpoint.slug) startFocus(h);
			else {
				pendingFocus = h;
				goToViewpoint(h.focus.viewpoint);
			}
			return;
		}
		const { yaw, pitch } = h.views[viewpoint.slug];
		detailImage = viewer?.snapshot(yaw, pitch, 40, 840, 630) ?? '';
		detail = h;
		pinned = peek = null;
	}

	/** Zooms in on a focus hotspot and lets its items be picked. */
	async function startFocus(h: Hotspot) {
		if (!viewer || !h.focus) return;
		focus = h;
		focusReady = false;
		showHint = false;
		shelf = new ShelfItems(viewer, h.items ?? [], viewpoint, (path) => spaceUrl(space.slug, path));
		viewer.addOverlay(shelf);
		// on a narrow (portrait) screen, zoom less so the shelf's width still fits
		const aspect = canvas.clientWidth / canvas.clientHeight;
		const t = Math.tan(((h.focus.fov * 0.8) / 2) * (Math.PI / 180)) / aspect;
		const fov = Math.max(h.focus.fov, Math.min(90, (2 * Math.atan(t) * 180) / Math.PI));
		focusFov = fov;
		await viewer.zoomTo(h.focus.yaw, h.focus.pitch, fov, 900);
		if (focus === h) focusReady = true;
	}

	/** Back to looking around: the book goes back, the overlay goes, the view zooms out. */
	async function leaveFocus(zoomOut = true, animate = true) {
		const s = shelf;
		focus = null;
		focusReady = false;
		hoverItem = null;
		outlines = [];
		openItem = null;
		shelf = null;
		if (s && viewer) {
			if (animate) await s.putBack();
			viewer.removeOverlay(s);
			s.dispose();
		}
		if (zoomOut && viewer) viewer.zoomTo(viewer.yaw, Math.max(-10, Math.min(10, viewer.pitch)), DEFAULT_FOV, 600);
	}

	function panelLayout(): Panel {
		const w = window.innerWidth;
		if (w <= 760) return { side: 'bottom', fraction: 0.5 };
		return { side: 'right', fraction: (Math.min(400, w - 32) + 48) / w };
	}

	async function openBook(item: HotspotItem) {
		if (!shelf) return;
		hoverItem = null;
		openItem = item;
		await shelf.fly(item.slug, panelLayout());
	}

	async function closeBook() {
		if (!shelf || !openItem) return;
		openItem = null;
		await shelf.putBack();
		canvas.focus();
	}

	async function stepBook(delta: number) {
		const items = focus?.items ?? [];
		if (!shelf || !openItem || items.length < 2) return;
		const i = items.findIndex((x) => x.slug === openItem!.slug);
		const next = items[(i + delta + items.length) % items.length];
		openItem = next;
		await shelf.putBack();
		if (openItem === next) await shelf.fly(next.slug, panelLayout());
	}

	function onCanvasHover(e: PointerEvent) {
		if (!focus || !shelf || openItem || e.pointerType !== 'mouse' || e.buttons) {
			if (hoverItem && e.buttons) hoverItem = null;
			return;
		}
		hoverItem = shelf.pick(viewer!.pointerDirection(e.clientX, e.clientY));
		hoverAt = { x: e.clientX, y: e.clientY };
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && focus && !openItem) leaveFocus();
	}}
/>

<div class="tour">
	<canvas
		bind:this={canvas}
		class:loading
		class:picking={!!hoverItem}
		onpointermove={onCanvasHover}
		onpointerleave={() => (hoverItem = null)}
		tabindex="0"
		aria-label="Panorama of {space.title}, {viewpoint.title}. Drag or use arrow keys to look around; plus and minus to zoom."
	></canvas>

	{#if focus}
		<!-- A soft light breathing on each spine (screen-blended, so it brightens like light). -->
		<svg class="outlines" class:dim={!!openItem} aria-hidden="true">
			<defs>
				<filter id="spine-glow" x="-100%" y="-50%" width="300%" height="200%">
					<feGaussianBlur stdDeviation="9" />
				</filter>
				<filter id="spine-soft" x="-50%" y="-20%" width="200%" height="140%">
					<feGaussianBlur stdDeviation="2" />
				</filter>
			</defs>
			{#each outlines as o, i (o.item.slug)}
				<g class:hover={hoverItem?.slug === o.item.slug} style="animation-delay: {i * -0.45}s">
					<polygon class="bloom" points={o.points} filter="url(#spine-glow)" />
					<polygon class="core" points={o.points} filter="url(#spine-soft)" />
				</g>
			{/each}
		</svg>
		{#if hoverItem}
			<div class="book-label" style="left: {hoverAt.x}px; top: {hoverAt.y}px">
				<strong>{hoverItem.title}</strong>
				<span>{hoverItem.author}</span>
			</div>
		{/if}
		{#if !openItem}
			<div class="focus-bar">
				<button class="back" onclick={() => leaveFocus()} aria-label="Back to the room">
					<Icon name="chevron-left" size={16} />
				</button>
				<span class="wide">{focus.title}: pick one of the {focus.items?.length ?? 0} highlighted books</span>
				<span class="narrow">Tap a highlighted book</span>
			</div>
			<div class="sr-only" role="group" aria-label="Books on the {focus.title.toLowerCase()}">
				{#each focus.items ?? [] as item (item.slug)}
					<button onclick={() => openBook(item)}>{item.title} by {item.author}</button>
				{/each}
			</div>
		{/if}
	{/if}

	<div class="markers" class:hidden={loading || moving || !!focus}>
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

	{#if openItem && focus}
		<BookPanel
			item={openItem}
			index={(focus.items ?? []).findIndex((x) => x.slug === openItem!.slug)}
			count={focus.items?.length ?? 0}
			shelfTitle={focus.title}
			onclose={closeBook}
			onstep={stepBook}
		/>
	{/if}

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
	canvas.picking {
		cursor: pointer;
	}
	.outlines {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		transition: opacity 300ms ease;
	}
	.outlines.dim {
		opacity: 0;
	}
	.outlines {
		mix-blend-mode: screen;
	}
	.outlines g {
		animation: breathe 2.2s ease-in-out infinite;
		transition: opacity 160ms ease;
	}
	.outlines .bloom {
		fill: #ffd28a;
		stroke: #ffd28a;
		stroke-width: 14;
		stroke-linejoin: round;
	}
	.outlines .core {
		fill: rgba(255, 236, 200, 0.55);
	}
	.outlines g.hover {
		animation: none;
		opacity: 1;
	}
	.outlines g.hover .core {
		fill: rgba(255, 240, 214, 0.75);
	}
	@keyframes breathe {
		0%,
		100% {
			opacity: 0.35;
		}
		50% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.outlines g {
			animation: none;
			opacity: 0.6;
		}
	}
	.book-label {
		position: absolute;
		transform: translate(16px, 16px);
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 8px 12px;
		border-radius: 10px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		pointer-events: none;
		font-size: 13px;
		white-space: nowrap;
	}
	.book-label span {
		font-size: 12px;
		color: var(--ink-soft);
	}
	.focus-bar {
		position: absolute;
		top: 88px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 6px 16px 6px 6px;
		border-radius: 999px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		font-size: 13px;
		color: var(--ink-soft);
		white-space: nowrap;
		animation: drop 300ms ease both;
	}
	@keyframes drop {
		from {
			opacity: 0;
			transform: translate(-50%, -8px);
		}
	}
	.back {
		width: 30px;
		height: 30px;
		border-radius: 50%;
		border: 1px solid var(--line);
		background: transparent;
		display: grid;
		place-items: center;
		cursor: pointer;
	}
	.focus-bar .narrow {
		display: none;
	}
	@media (max-width: 760px) {
		.focus-bar .wide {
			display: none;
		}
		.focus-bar .narrow {
			display: inline;
		}
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}
	.sr-only button:focus-visible {
		position: fixed;
		top: 140px;
		left: 50%;
		transform: translateX(-50%);
		width: auto;
		height: auto;
		padding: 8px 14px;
		border-radius: 999px;
		background: var(--panel-solid);
		border: 0;
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
