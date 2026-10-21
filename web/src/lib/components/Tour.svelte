<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { MIN_FOV, PanoViewer, prefersReducedMotion, type PanoSource } from '$lib/viewer/PanoViewer';
	import { ShelfItems, type Panel } from '$lib/viewer/shelfItems';
	import { spaceUrl, type Hotspot, type HotspotItem, type Space, type Viewpoint } from '$lib/types';
	import TopBar from './TopBar.svelte';
	import HotspotMarker from './HotspotMarker.svelte';
	import Minimap from './Minimap.svelte';
	import HintPill from './HintPill.svelte';
	import Icon from './Icon.svelte';
	import DetailPanel from './DetailPanel.svelte';
	import BookPanel from './BookPanel.svelte';
	import LetterPanel from './LetterPanel.svelte';
	import MusicPlayer from './MusicPlayer.svelte';
	import { site } from '$lib/site';
	import SpeakerRipples from './SpeakerRipples.svelte';

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
	/** An open letter, and where its envelope lies on screen. */
	let letter: { hotspot: Hotspot; from: { x: number; y: number } } | null = $state(null);
	// The room's playlist: its player sits in the corner, and ripples spread from the speaker while it plays.
	const music = $derived(space.hotspots.find((h) => h.playlist));
	let playing = $state(false);
	let showHint = $state(true);
	const thumbnails: Record<string, string> = $state({});

	// Focus: zoomed in on a hotspot (the print), or on one whose items (books) can be picked.
	let focus: Hotspot | null = $state.raw(null);
	/** True once the zoom-in has landed (so zooming out can leave). */
	let focusReady = false;
	/** The field of view the focus zoomed to (wider than focus.fov on portrait screens). */
	let focusFov = 0;
	let pendingFocus: Hotspot | null = null;
	/** The next move came from the minimap: land facing the space's landmark (viewpoint.arrive). */
	let fromMinimap = false;
	let shelf: ShelfItems | null = null;
	let hoverItem: HotspotItem | null = $state(null);
	let hoverAt = $state({ x: 0, y: 0 });
	let openItem: HotspotItem | null = $state(null);
	let outlines: { item: HotspotItem; points: string }[] = $state([]);

	const viewpoint = $derived(
		space.viewpoints.find((v) => v.slug === viewpointSlug) ?? space.viewpoints[0]
	);
	const here = $derived(
		space.hotspots.filter((h) => h.views[viewpoint.slug] && !h.playlist && !site.hiddenHotspots.includes(h.slug))
	);
	const openSlug = $derived(pinned ?? peek);

	function updateView() {
		if (!viewer) return;
		yaw = viewer.yaw;
		hfov = viewer.hfov;
		// while a book is out the page above the canvas stays still, so frames stay cheap
		if (openItem) return;
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
		// a letter's typewriter face, fetched now so its envelope opens without a pause
		if (space.hotspots.some((h) => h.letter)) document.fonts.load('16px "Special Elite"').catch(() => {});
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
		viewer.yawRange = v.yawRange ?? null;
		const minimap = fromMinimap;
		fromMinimap = false;
		const from = space.viewpoints.find((x) => panoUrl(x) === viewer.url);
		if (from === v && !target) {
			loading = moving = false;
			return;
		}

		let shown: Promise<unknown>;
		let landing: Hotspot | null = null;
		if (from && !target) {
			moving = true;
			// Compass bearing from here to there: x east, y north, clockwise from north.
			const yaw = (Math.atan2(v.position[0] - from.position[0], v.position[1] - from.position[1]) * 180) / Math.PI;
			// heading for a close-up (the bookshelf): the move itself ends on it
			landing = pendingFocus?.focus?.viewpoint === v.slug ? pendingFocus : null;
			const view = landing
				? focusView(landing)
				: minimap && v.arrive
					? { ...v.arrive, fov: DEFAULT_FOV }
					: { yaw };
			// a close-up may zoom in further than usual (the display): let the move land on it
			if (landing && 'fov' in view) viewer.minFov = Math.min(MIN_FOV, view.fov);
			shown = viewer.transitionTo(panoSource(v), { ...view, reduced: prefersReducedMotion() });
		} else {
			loading = true;
			shown = viewer.setPanorama(panoSource(v)).then(() => {
				if (token !== showToken) return;
				if (target) {
					viewer.lookAt(target.views[v.slug].yaw, Math.max(-20, Math.min(20, target.views[v.slug].pitch)));
					pinned = target.slug;
				} else {
					// ?yaw=<deg>&pitch=<deg> opens facing a compass bearing (clockwise from north),
					// e.g. for screenshots to compare with photos (tools/check view --yaw)
					const q = page.url.searchParams;
					const yaw = q.get('yaw') ? Number(q.get('yaw')) : NaN;
					if (Number.isFinite(yaw)) viewer.lookAt(yaw, Number(q.get('pitch')) || 0);
					else viewer.lookAt(v.initialYaw);
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
				const landed = next === landing;
				pendingFocus = landing = null;
				if (next?.focus?.viewpoint === v.slug) startFocus(next, !landed || prefersReducedMotion());
			});
	}

	/** The nearest viewpoints and the previous/next in tour order: the likely next moves. */
	function neighbours(v: Viewpoint) {
		const all = space.viewpoints;
		const i = all.indexOf(v);
		const dist = (w: Viewpoint) => Math.hypot(w.position[0] - v.position[0], w.position[1] - v.position[1]);
		const nearest = all.filter((w) => w !== v).sort((a, b) => dist(a) - dist(b));
		const list = [...nearest.slice(0, 2), all[(i + 1) % all.length], all[(i - 1 + all.length) % all.length]];
		return [...new Set(list)].filter((w) => w !== v);
	}

	/** The hotspot (e.g. the bookshelf) whose picking view lives at viewpoint `slug`, if any. */
	const focusAt = (slug: string) => space.hotspots.find((h) => h.focus?.viewpoint === slug && h.items?.length);

	/** Minimap: a viewpoint with a picking view (the bookshelf) opens straight into it. */
	function goToViewpoint(slug: string, target = focusAt(slug)) {
		if (slug === viewpoint.slug) {
			if (target && !focus && !moving && !loading) startFocus(target);
			return;
		}
		pendingFocus = target ?? null;
		goto(`/${space.slug}/${slug}`, { replaceState: true, noScroll: true, keepFocus: true });
	}

	/** The detail panel: close-ups and 3D model, over a snapshot of the hotspot. */
	function showPanel(h: Hotspot) {
		const { yaw, pitch } = h.views[viewpoint.slug] ?? { yaw: viewer?.yaw ?? 0, pitch: viewer?.pitch ?? 0 };
		detailImage = viewer?.snapshot(yaw, pitch, 40, 840, 630) ?? '';
		detail = h;
		pinned = peek = null;
	}

	function openDetail(h: Hotspot) {
		if (h.kind === 'door') {
			if (h.target) goto(h.arrive ? `/${h.target}/${h.arrive}` : `/${h.target}`);
			return;
		}
		if (h.letter) {
			const m = markers.find((x) => x.hotspot.slug === h.slug);
			pinned = peek = null;
			letter = { hotspot: h, from: m ? { x: m.x, y: m.y } : { x: innerWidth / 2, y: innerHeight / 2 } };
			return;
		}
		if (h.focus) {
			pinned = peek = null;
			if (h.focus.viewpoint === viewpoint.slug) startFocus(h);
			else goToViewpoint(h.focus.viewpoint, h);
			return;
		}
		showPanel(h);
	}

	/** Where a focus hotspot is looked at from; on a narrow (portrait) screen, zoomed out so the shelf's width still fits. */
	function focusView(h: Hotspot) {
		const f = h.focus!;
		const aspect = canvas.clientWidth / canvas.clientHeight;
		const t = Math.tan(((f.width ?? f.fov * 0.8) / 2) * (Math.PI / 180)) / aspect;
		const fov = Math.max(f.fov, Math.min(90, (2 * Math.atan(t) * 180) / Math.PI));
		return { yaw: f.yaw, pitch: f.pitch, fov };
	}

	/**
	 * Zooms in on a focus hotspot (unless a move already landed there) and lets its items
	 * be picked. The items are set up once the view is still, so nothing competes with the zoom.
	 */
	async function startFocus(h: Hotspot, zoom = true) {
		if (!viewer || !h.focus) return;
		focus = h;
		focusReady = false;
		showHint = false;
		const view = focusView(h);
		focusFov = view.fov;
		viewer.minFov = Math.min(MIN_FOV, view.fov);
		if (zoom && !(await viewer.zoomTo(view.yaw, view.pitch, view.fov))) {
			if (focus === h) leaveFocus(false, false);
			return;
		}
		if (focus !== h) return;
		if (h.items?.length) {
			shelf = new ShelfItems(viewer, h.items, viewpoint, (path) => spaceUrl(space.slug, path));
			viewer.addOverlay(shelf);
		}
		focusReady = true;
		updateView();
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
		if (viewer) viewer.minFov = MIN_FOV;
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
		if (e.key === 'Escape' && focus && !openItem && !letter) leaveFocus();
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
		<svg class="outlines" class:hidden={!!openItem} aria-hidden="true">
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
				{#if focus.items?.length}
					<span class="wide">{focus.title}: pick one of the {focus.items.length} highlighted books</span>
					<span class="narrow">Tap a highlighted book</span>
				{:else}
					<span>{focus.title}</span>
					{#if focus.detail}
						<button class="more" onclick={() => showPanel(focus!)}>Close-ups and 3D</button>
					{/if}
				{/if}
			</div>
			{#if focus.items?.length}
				<div class="sr-only" role="group" aria-label="Books on the {focus.title.toLowerCase()}">
					{#each focus.items as item (item.slug)}
						<button onclick={() => openBook(item)}>{item.title} by {item.author}</button>
					{/each}
				</div>
			{/if}
		{/if}
	{/if}

	<SpeakerRipples
		source={music?.views[viewpoint.slug] ?? null}
		{playing}
		hidden={loading || moving || !!focus}
		project={(y, p) => viewer?.project(y, p)}
		focal={() => canvas.clientWidth / 2 / Math.tan((hfov * Math.PI) / 360)}
	/>

	<div class="markers" class:hidden={loading || moving || !!focus || !!letter}>
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
						if (pinned === m.hotspot.slug || m.hotspot.focus || m.hotspot.letter) openDetail(m.hotspot);
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
				onselect={(slug) => {
					const here = slug === viewpoint.slug;
					const v = space.viewpoints.find((x) => x.slug === slug);
					// already here: turn back to the landmark (the bookshelf opens its close-up instead)
					if (here && !focusAt(slug) && v?.arrive && !moving && !loading) {
						viewer?.zoomTo(v.arrive.yaw, v.arrive.pitch, DEFAULT_FOV);
						return;
					}
					fromMinimap = !here;
					goToViewpoint(slug);
				}}
				onzoom={(d) => viewer?.zoomBy(d * -8)}
			/>
			<a class="credit" href={site.credit.href} target="_blank" rel="noopener">{site.credit.label}</a>
		</div>
		<div class="right">
			{#if showHint}<HintPill />{/if}
			{#if music}
				<div class="music-slot">
					<MusicPlayer hotspot={music} spaceTitle={space.title} onplaying={(p) => (playing = p)} />
				</div>
			{/if}
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

	{#if letter}
		<LetterPanel
			title={letter.hotspot.title}
			text={letter.hotspot.letter ?? ''}
			from={letter.from}
			onclose={() => {
				letter = null;
				canvas.focus();
			}}
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
	.outlines.hidden {
		display: none;
	}
	.outlines {
		mix-blend-mode: screen;
	}
	.outlines g {
		animation: breathe 2.2s ease-in-out infinite;
		transition: opacity 160ms ease;
	}
	/* the glow arrives once the zoom has landed */
	.outlines polygon {
		animation: glow-in 600ms ease-out both;
	}
	@keyframes glow-in {
		from {
			opacity: 0;
		}
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
	.focus-bar .more {
		margin-left: 6px;
		padding: 6px 12px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: transparent;
		font: inherit;
		font-weight: 500;
		color: var(--ink);
		cursor: pointer;
		transition: border-color 150ms ease;
	}
	.focus-bar .more:hover {
		border-color: var(--ink-soft);
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
		grid-template-columns: auto minmax(0, 1fr);
		align-items: end;
		gap: 16px;
		padding: 24px 28px;
		pointer-events: none;
		/* the minimap's raised disc (it grows over the room) stays below the book and detail panels */
		isolation: isolate;
	}
	.bottom > * {
		pointer-events: auto;
	}
	.left {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 10px;
	}
	.credit {
		font-family: var(--mono);
		font-size: 10.5px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--ink-soft);
		text-decoration: none;
		text-shadow: 0 1px 8px rgba(0, 0, 0, 0.6);
		transition: color 150ms ease;
	}
	.credit:hover,
	.credit:focus-visible {
		color: var(--accent);
	}
	.right {
		justify-self: end;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 12px;
	}

	@media (max-width: 1040px) {
		.bottom {
			padding: 16px;
			padding-bottom: max(16px, env(safe-area-inset-bottom));
			gap: 12px;
		}
	}
	/* Phone: minimap and hint on one row, the music full width below. */
	@media (max-width: 760px) {
		.bottom {
			grid-template-areas:
				'left right'
				'music music';
		}
		.left {
			grid-area: left;
		}
		.right {
			display: contents;
		}
		.right > :global(.hint) {
			grid-area: right;
			justify-self: end;
		}
		.music-slot {
			grid-area: music;
		}
		.music-slot :global(.music) {
			width: 100%;
		}
	}
</style>
