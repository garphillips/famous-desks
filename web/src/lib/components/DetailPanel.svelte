<script lang="ts">
	import { page } from '$app/state';
	import Icon from './Icon.svelte';
	import ModelViewer from './ModelViewer.svelte';
	import { spaceUrl, type Hotspot } from '$lib/types';

	let {
		hotspot,
		image,
		spaceTitle,
		onclose
	}: { hotspot: Hotspot; image: string; spaceTitle: string; onclose: () => void } = $props();

	let closeButton: HTMLButtonElement;

	const space = $derived(page.params.space ?? '');
	/** Close-up renders, or the panorama crop when the hotspot has none yet. */
	const images = $derived(
		hotspot.detail?.images.length
			? hotspot.detail.images.map((path) => spaceUrl(space, path))
			: image
				? [image]
				: []
	);
	const model = $derived(hotspot.detail?.model ? spaceUrl(space, hotspot.detail.model) : '');

	let index = $state(0);
	let view: 'images' | '3d' = $state('images');

	// Start each hotspot on its first image.
	$effect(() => {
		void hotspot.slug;
		index = 0;
		view = 'images';
	});

	$effect(() => {
		closeButton.focus();
	});

	function step(delta: number) {
		if (images.length < 2) return;
		index = (index + delta + images.length) % images.length;
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
		else if (view === 'images' && e.key === 'ArrowLeft') step(-1);
		else if (view === 'images' && e.key === 'ArrowRight') step(1);
	}
</script>

<svelte:window {onkeydown} />

<div class="scrim" onclick={onclose} role="presentation"></div>
<aside class="panel" aria-labelledby="detail-title">
	<button class="close" bind:this={closeButton} onclick={onclose} aria-label="Close">
		<Icon name="close" size={18} />
	</button>

	{#if images.length || model}
		<div class="media">
			{#if view === '3d' && model}
				<ModelViewer src={model} label={hotspot.title} />
			{:else}
				<div class="gallery" aria-roledescription="carousel" aria-label="Close-ups of {hotspot.title}">
					{#each images as src, i (src)}
						<img
							{src}
							alt="{hotspot.title} in {spaceTitle}{images.length > 1 ? `, view ${i + 1} of ${images.length}` : ''}"
							class:active={i === index}
							aria-hidden={i !== index}
							loading={i === 0 ? 'eager' : 'lazy'}
							draggable="false"
						/>
					{/each}
					{#if images.length > 1}
						<button class="arrow prev" onclick={() => step(-1)} aria-label="Previous image">
							<Icon name="chevron-left" size={18} />
						</button>
						<button class="arrow next" onclick={() => step(1)} aria-label="Next image">
							<Icon name="chevron-right" size={18} />
						</button>
					{/if}
				</div>
			{/if}
		</div>

		{#if model || images.length > 1}
			<div class="controls">
				{#if model}
					<div class="toggle" role="group" aria-label="View">
						<button aria-pressed={view === 'images'} onclick={() => (view = 'images')}>Close-ups</button>
						<button aria-pressed={view === '3d'} onclick={() => (view = '3d')}>3D</button>
					</div>
				{/if}
				{#if view === 'images' && images.length > 1}
					<div class="dots" role="group" aria-label="Choose image">
						{#each images as _, i (i)}
							<button
								class:active={i === index}
								aria-label="Image {i + 1} of {images.length}"
								aria-current={i === index}
								onclick={() => (index = i)}
							></button>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	{/if}

	<div class="body">
		<span class="eyebrow">{spaceTitle}</span>
		<h2 id="detail-title">{hotspot.title}</h2>
		{#if hotspot.summary}<p>{hotspot.summary}</p>{/if}
		<p class="soon">The story behind this object is on the way.</p>
	</div>
</aside>

<style>
	.scrim {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.25);
		animation: fade 200ms ease both;
	}
	.panel {
		position: absolute;
		top: 16px;
		right: 16px;
		bottom: 16px;
		width: min(420px, calc(100vw - 32px));
		display: flex;
		flex-direction: column;
		border-radius: 20px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
		overflow: auto;
		animation: slide 260ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
	}
	@keyframes fade {
		from {
			opacity: 0;
		}
	}
	@keyframes slide {
		from {
			opacity: 0;
			transform: translateX(24px);
		}
	}
	.close {
		position: absolute;
		top: 12px;
		right: 12px;
		width: 36px;
		height: 36px;
		border-radius: 50%;
		border: 0;
		background: rgba(14, 14, 13, 0.7);
		display: grid;
		place-items: center;
		cursor: pointer;
		z-index: 2;
	}

	.media {
		position: relative;
		flex: none;
		width: 100%;
		aspect-ratio: 4 / 3;
		background: var(--panel-solid);
		overflow: hidden;
	}
	.gallery {
		position: absolute;
		inset: 0;
	}
	.gallery img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
		opacity: 0;
		transition: opacity 380ms ease;
		user-select: none;
	}
	.gallery img.active {
		opacity: 1;
	}
	.arrow {
		position: absolute;
		top: 50%;
		width: 36px;
		height: 36px;
		margin-top: -18px;
		border-radius: 50%;
		border: 1px solid rgba(244, 241, 234, 0.14);
		background: rgba(14, 14, 13, 0.55);
		backdrop-filter: var(--blur);
		display: grid;
		place-items: center;
		cursor: pointer;
		opacity: 0;
		transition:
			opacity 200ms ease,
			background 200ms ease;
	}
	.arrow:hover {
		background: rgba(14, 14, 13, 0.8);
	}
	.prev {
		left: 12px;
	}
	.next {
		right: 12px;
	}
	.gallery:hover .arrow,
	.arrow:focus-visible {
		opacity: 1;
	}
	@media (hover: none) {
		.arrow {
			opacity: 1;
		}
	}

	.controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 14px 24px 0;
	}
	.toggle {
		display: inline-flex;
		padding: 3px;
		border-radius: 999px;
		background: rgba(244, 241, 234, 0.06);
		border: 1px solid rgba(244, 241, 234, 0.1);
	}
	.toggle button {
		border: 0;
		background: none;
		padding: 6px 14px;
		border-radius: 999px;
		font-size: 12px;
		letter-spacing: 0.06em;
		color: var(--ink-soft);
		cursor: pointer;
		transition:
			background 200ms ease,
			color 200ms ease;
	}
	.toggle button:hover {
		color: var(--ink);
	}
	.toggle button[aria-pressed='true'] {
		background: var(--accent);
		color: #1a1712;
		font-weight: 500;
	}
	.dots {
		display: flex;
		gap: 4px;
		margin-left: auto;
	}
	.dots button {
		width: 20px;
		height: 20px;
		padding: 0;
		border: 0;
		background: none;
		cursor: pointer;
		display: grid;
		place-items: center;
	}
	.dots button::after {
		content: '';
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--ink-faint);
		transition:
			background 200ms ease,
			transform 200ms ease;
	}
	.dots button.active::after {
		background: var(--accent);
		transform: scale(1.25);
	}

	.body {
		padding: 22px 24px 28px;
	}
	.eyebrow {
		font-size: 10.5px;
		letter-spacing: 0.22em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	h2 {
		margin: 8px 0 12px;
		font-family: var(--serif);
		font-weight: 500;
		font-size: 34px;
		line-height: 1.05;
	}
	p {
		margin: 0 0 12px;
		font-size: 14.5px;
		line-height: 1.55;
		color: var(--ink-soft);
	}
	.soon {
		margin-top: 20px;
		padding-top: 16px;
		border-top: 1px solid var(--line);
		font-size: 13px;
		color: var(--ink-faint);
	}
</style>
