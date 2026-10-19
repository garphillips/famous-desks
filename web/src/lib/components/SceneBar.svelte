<script lang="ts">
	import Icon from './Icon.svelte';
	import type { Viewpoint } from '$lib/types';

	let {
		viewpoints,
		current,
		onselect
	}: { viewpoints: Viewpoint[]; current: string; onselect: (slug: string) => void } = $props();

	const index = $derived(Math.max(0, viewpoints.findIndex((v) => v.slug === current)));
	const step = (d: number) => onselect(viewpoints[(index + d + viewpoints.length) % viewpoints.length].slug);
</script>

<nav class="scenes" aria-label="Viewpoints">
	<button class="arrow" onclick={() => step(-1)} aria-label="Previous viewpoint">
		<Icon name="chevron-left" size={16} />
	</button>
	<ul>
		{#each viewpoints as v (v.slug)}
			<li>
				<button
					class:current={v.slug === current}
					aria-current={v.slug === current ? 'location' : undefined}
					onclick={() => onselect(v.slug)}>{v.title}</button
				>
			</li>
		{/each}
	</ul>
	<button class="arrow" onclick={() => step(1)} aria-label="Next viewpoint">
		<Icon name="chevron-right" size={16} />
	</button>
</nav>

<style>
	.scenes {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 6px;
		border-radius: 999px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
		max-width: calc(100vw - 32px);
	}
	ul {
		display: flex;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
		overflow-x: auto;
		scrollbar-width: none;
	}
	ul button {
		position: relative;
		border: 0;
		background: transparent;
		padding: 9px 14px 11px;
		font-size: 13.5px;
		color: var(--ink-soft);
		cursor: pointer;
		white-space: nowrap;
		transition: color 150ms ease;
	}
	ul button:hover {
		color: var(--ink);
	}
	ul button.current {
		color: var(--ink);
	}
	ul button.current::after {
		content: '';
		position: absolute;
		left: 14px;
		right: 14px;
		bottom: 5px;
		height: 1.5px;
		border-radius: 1px;
		background: var(--accent);
	}
	.arrow {
		flex: none;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		border: 0;
		background: transparent;
		display: grid;
		place-items: center;
		cursor: pointer;
		transition: background 150ms ease;
	}
	.arrow:hover {
		background: rgba(244, 241, 234, 0.12);
	}
</style>
