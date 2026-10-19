<script lang="ts">
	import Icon from './Icon.svelte';
	import type { HotspotItem } from '$lib/types';

	let {
		item,
		index,
		count,
		shelfTitle,
		onclose,
		onstep
	}: {
		item: HotspotItem;
		index: number;
		count: number;
		shelfTitle: string;
		onclose: () => void;
		onstep: (delta: number) => void;
	} = $props();

	let closeButton: HTMLButtonElement;

	$effect(() => {
		closeButton.focus();
	});

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
		else if (e.key === 'ArrowLeft') onstep(-1);
		else if (e.key === 'ArrowRight') onstep(1);
	}
</script>

<svelte:window {onkeydown} />

<!-- The book itself is drawn in the panorama, beside this panel (which also dims the room);
     the scrim only keeps the view still and closes on a click. -->
<div class="scrim" onclick={onclose} role="presentation"></div>
<div class="panel" role="dialog" aria-modal="true" aria-labelledby="book-title">
	<button class="close" bind:this={closeButton} onclick={onclose} aria-label="Put the book back">
		<Icon name="close" size={18} />
	</button>
	{#key item.slug}
		<div class="body">
			<span class="eyebrow">{shelfTitle} · {index + 1} of {count}</span>
			<h2 id="book-title">{item.title}</h2>
			<p class="author">{item.author}</p>
			<p>{item.summary}</p>
		</div>
	{/key}
	{#if count > 1}
		<nav class="steps" aria-label="Other books">
			<button onclick={() => onstep(-1)} aria-label="Previous book"><Icon name="chevron-left" size={18} /></button>
			<button onclick={() => onstep(1)} aria-label="Next book"><Icon name="chevron-right" size={18} /></button>
		</nav>
	{/if}
</div>

<style>
	.scrim {
		position: absolute;
		inset: 0;
	}
	.panel {
		position: absolute;
		top: 50%;
		right: 24px;
		width: min(400px, calc(100vw - 32px));
		max-height: calc(100% - 48px);
		transform: translateY(-50%);
		display: flex;
		flex-direction: column;
		border-radius: 20px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
		overflow: auto;
		animation: slide 420ms 280ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
	}
	@keyframes fade {
		from {
			opacity: 0;
		}
	}
	@keyframes slide {
		from {
			opacity: 0;
			transform: translate(24px, -50%);
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
	.body {
		padding: 28px 28px 8px;
		animation: fade 320ms ease both;
	}
	.eyebrow {
		font-size: 10.5px;
		letter-spacing: 0.22em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	h2 {
		margin: 10px 0 4px;
		font-family: var(--serif);
		font-weight: 500;
		font-size: 36px;
		line-height: 1.05;
	}
	.author {
		margin: 0 0 16px;
		font-size: 14px;
		color: var(--accent);
	}
	p {
		margin: 0 0 12px;
		font-size: 14.5px;
		line-height: 1.6;
		color: var(--ink-soft);
	}
	.steps {
		display: flex;
		gap: 8px;
		padding: 8px 28px 24px;
	}
	.steps button {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		border: 1px solid var(--line);
		background: transparent;
		display: grid;
		place-items: center;
		cursor: pointer;
	}
	.steps button:hover {
		background: var(--accent-wash);
	}

	/* Phone: a sheet along the bottom; the book rests above it. */
	@media (max-width: 760px) {
		.panel {
			top: auto;
			right: 12px;
			left: 12px;
			bottom: max(12px, env(safe-area-inset-bottom));
			width: auto;
			max-height: 46%;
			transform: none;
			animation-name: rise;
		}
		@keyframes rise {
			from {
				opacity: 0;
				transform: translateY(24px);
			}
		}
		.body {
			padding: 22px 22px 4px;
		}
		h2 {
			font-size: 28px;
		}
		.steps {
			padding: 4px 22px 18px;
		}
	}
</style>
