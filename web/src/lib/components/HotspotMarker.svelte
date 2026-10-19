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
		onopen
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
	} = $props();

	// Show the card on whichever side has more room.
	const side = $derived(x > window.innerWidth / 2 ? 'left' : 'right');
	const comingSoon = $derived(hotspot.kind === 'door' && !hotspot.target);
	const cardId = $derived(`card-${hotspot.slug}`);
</script>

<div
	class="hotspot"
	style:left="{x}px"
	style:top="{y}px"
	onmouseenter={onpeek}
	onmouseleave={onunpeek}
	role="presentation"
>
	<button
		class="badge"
		class:open
		onclick={ontoggle}
		aria-label={hotspot.title}
		aria-expanded={open}
		aria-controls={cardId}
	>
		<Icon name={hotspot.icon} />
	</button>
	<span class="dot" aria-hidden="true"></span>

	{#if open}
		<div class="card {side}" id={cardId}>
			{#if thumbnail}
				<img src={thumbnail} alt="" />
			{/if}
			<div class="text">
				<strong>{hotspot.title}</strong>
				{#if comingSoon}
					<span>Leads to another space, coming soon.</span>
				{:else if hotspot.summary}
					<span>{hotspot.summary}</span>
				{/if}
			</div>
			{#if !comingSoon}
				<button class="go" onclick={onopen} aria-label="Look closer at {hotspot.title}">
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
		top: -78px;
		width: 290px;
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
	.card.left {
		right: 32px;
	}
	.card.right {
		left: 32px;
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

	@media (max-width: 600px) {
		.card {
			width: min(260px, calc(100vw - 80px));
		}
	}
</style>
