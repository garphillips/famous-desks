<script lang="ts">
	import Icon from './Icon.svelte';
	import type { Hotspot } from '$lib/types';

	let {
		hotspot,
		image,
		spaceTitle,
		onclose
	}: { hotspot: Hotspot; image: string; spaceTitle: string; onclose: () => void } = $props();

	let closeButton: HTMLButtonElement;

	$effect(() => {
		closeButton.focus();
	});
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<div class="scrim" onclick={onclose} role="presentation"></div>
<aside class="panel" aria-labelledby="detail-title">
	<button class="close" bind:this={closeButton} onclick={onclose} aria-label="Close">
		<Icon name="close" size={18} />
	</button>
	{#if image}
		<img src={image} alt="{hotspot.title} in {spaceTitle}" />
	{/if}
	<div class="body">
		<span class="eyebrow">{spaceTitle}</span>
		<h2 id="detail-title">{hotspot.title}</h2>
		{#if hotspot.summary}<p>{hotspot.summary}</p>{/if}
		<p class="soon">Close-up renders, a 3D view and the story behind this object are on the way.</p>
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
		z-index: 1;
	}
	img {
		width: 100%;
		aspect-ratio: 4 / 3;
		object-fit: cover;
		display: block;
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
