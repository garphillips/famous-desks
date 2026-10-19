<script lang="ts">
	import Icon from './Icon.svelte';
	import type { Hotspot } from '$lib/types';

	let {
		hotspot,
		x,
		y,
		open,
		thumbnail,
		onpeek,
		onunpeek,
		ontoggle,
		onopen,
		ongrab
	}: {
		hotspot: Hotspot;
		x: number;
		y: number;
		/** Card showing (hovered or pinned). */
		open: boolean;
		thumbnail: string;
		onpeek: () => void;
		onunpeek: () => void;
		ontoggle: () => void;
		onopen: () => void;
		/** Pointer down on the pin: lets the viewer turn it into a drag. */
		ongrab: (e: PointerEvent) => void;
	} = $props();

	const GUTTER = 16;
	const TAP_SLOP = 8;

	let vw = $state(window.innerWidth);
	let vh = $state(window.innerHeight);
	let cardW = $state(0);
	let cardH = $state(0);
	let down: { x: number; y: number } | null = null;

	const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

	// Beside the pin on whichever side has more room, kept inside the viewport.
	// If clamping would slide it over the pin (narrow screens), stack it above or below.
	const card = $derived.by(() => {
		const want = x > vw / 2 ? x - 32 - cardW : x + 32;
		const left = clamp(want, GUTTER, vw - GUTTER - cardW);
		let top = y - 78;
		if (left !== want && left < x + 24 && left + cardW > x - 24) {
			top = y - 66 - cardH;
			if (top < GUTTER) top = y + 16;
		}
		return { left: left - x, top: clamp(top, GUTTER, vh - GUTTER - cardH) - y };
	});

	function onpointerdown(e: PointerEvent) {
		down = { x: e.clientX, y: e.clientY };
		ongrab(e);
	}

	// A drag that started on the pin shouldn't toggle it. Keyboard clicks (detail 0) always count.
	function onclick(e: MouseEvent) {
		const moved = down && e.detail > 0 && Math.hypot(e.clientX - down.x, e.clientY - down.y) > TAP_SLOP;
		down = null;
		if (!moved) ontoggle();
	}

	const hover = (fn: () => void) => (e: PointerEvent) => {
		if (e.pointerType === 'mouse') fn();
	};
	const comingSoon = $derived(hotspot.kind === 'door' && !hotspot.target);
	const leadsTo = $derived(hotspot.kind === 'door' && hotspot.target ? hotspot.targetTitle || hotspot.target : '');
	const cardId = $derived(`card-${hotspot.slug}`);
</script>

<svelte:window bind:innerWidth={vw} bind:innerHeight={vh} />

<div
	class="hotspot"
	class:open
	style:left="{x}px"
	style:top="{y}px"
	onpointerenter={hover(onpeek)}
	onpointerleave={hover(onunpeek)}
	role="presentation"
>
	<button
		class="badge"
		class:open
		{onpointerdown}
		{onclick}
		aria-label={hotspot.title}
		aria-expanded={open}
		aria-controls={cardId}
	>
		<Icon name={hotspot.icon} />
	</button>
	<span class="dot" aria-hidden="true"></span>

	{#if open}
		<div
			class="card"
			id={cardId}
			style:left="{card.left}px"
			style:top="{card.top}px"
			bind:offsetWidth={cardW}
			bind:offsetHeight={cardH}
		>
			{#if thumbnail}
				<img src={thumbnail} alt="" />
			{/if}
			<div class="text">
				<strong>{hotspot.title}</strong>
				{#if comingSoon}
					<span>Leads to another space, coming soon.</span>
				{:else if leadsTo}
					<span>Go to {leadsTo}</span>
				{:else if hotspot.summary}
					<span>{hotspot.summary}</span>
				{/if}
			</div>
			{#if !comingSoon}
				<button class="go" onclick={onopen} aria-label={leadsTo ? `Go to ${leadsTo}` : `Look closer at ${hotspot.title}`}>
					<Icon name="arrow-right" size={18} />
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	/* The anchor point (x, y) is the dot; the badge floats above it like a pin. */
	.hotspot {
		position: absolute;
		width: 0;
		height: 0;
		pointer-events: auto;
		touch-action: none;
	}
	.hotspot.open {
		z-index: 2;
	}
	.badge {
		position: absolute;
		left: -19px;
		top: -58px;
		width: 38px;
		height: 38px;
		border-radius: 50%;
		border: 1.5px solid rgba(244, 241, 234, 0.9);
		background: rgba(14, 14, 13, 0.78);
		backdrop-filter: var(--blur);
		display: grid;
		place-items: center;
		cursor: pointer;
		box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
		transition:
			transform 160ms ease,
			background 160ms ease,
			border-color 160ms ease;
	}
	.badge:hover,
	.badge.open {
		transform: scale(1.08);
		border-color: var(--accent);
		background: rgba(14, 14, 13, 0.9);
	}
	.dot {
		position: absolute;
		left: -5px;
		top: -5px;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--ink);
		box-shadow:
			0 0 0 4px rgba(244, 241, 234, 0.22),
			0 1px 6px rgba(0, 0, 0, 0.5);
		pointer-events: none;
	}
	.card {
		position: absolute;
		width: min(290px, calc(100vw - 32px));
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 12px 10px 10px;
		border-radius: var(--radius);
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
		animation: rise 180ms ease both;
	}
	@keyframes rise {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
	}
	img {
		width: 56px;
		height: 56px;
		border-radius: 8px;
		object-fit: cover;
		flex: none;
	}
	.text {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
		flex: 1;
	}
	strong {
		font-size: 14px;
		font-weight: 600;
	}
	.text span {
		font-size: 12.5px;
		line-height: 1.4;
		color: var(--ink-soft);
	}
	.go {
		flex: none;
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 0;
		background: transparent;
		display: grid;
		place-items: center;
		cursor: pointer;
		transition: background 150ms ease;
	}
	.go:hover {
		background: rgba(244, 241, 234, 0.12);
	}
</style>
