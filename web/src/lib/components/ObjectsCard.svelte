<script lang="ts">
	import Icon from './Icon.svelte';
	import type { Hotspot } from '$lib/types';

	let {
		hotspot,
		href,
		spaceTitle,
		viewpointTitle,
		image = ''
	}: { hotspot: Hotspot; href: string; spaceTitle: string; viewpointTitle: string; image?: string } =
		$props();

	const icon = $derived(hotspot.icon === 'info' ? 'info' : 'eye');
</script>

<a class="card" {href}>
	<div class="media">
		{#if image}
			<img src={image} alt="" loading="lazy" />
		{:else}
			<div class="placeholder" aria-hidden="true">
				<span class="badge"><Icon name={icon} size={20} /></span>
			</div>
		{/if}
	</div>
	<div class="body">
		<span class="eyebrow">{spaceTitle} <span class="sep">·</span> {viewpointTitle}</span>
		<h3>{hotspot.title}</h3>
		{#if hotspot.summary}<p>{hotspot.summary}</p>{/if}
		<span class="go">View in tour <Icon name="arrow-right" size={14} /></span>
	</div>
</a>

<style>
	.card {
		display: flex;
		flex-direction: column;
		min-width: 0;
		border-radius: var(--radius);
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		overflow: hidden;
		text-decoration: none;
		transition:
			border-color 180ms ease,
			transform 180ms ease;
	}
	.card:hover {
		border-color: var(--line);
		transform: translateY(-2px);
	}
	.media {
		aspect-ratio: 4 / 3;
		background: var(--panel-solid);
	}
	.media img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.placeholder {
		width: 100%;
		height: 100%;
		display: grid;
		place-items: center;
		background:
			radial-gradient(120% 90% at 30% 20%, var(--accent-wash), transparent 70%),
			linear-gradient(160deg, rgba(244, 241, 234, 0.05), rgba(244, 241, 234, 0.01));
	}
	.badge {
		width: 48px;
		height: 48px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		border: 1px solid var(--line);
		color: var(--ink-soft);
		background: rgba(14, 14, 13, 0.4);
		transition:
			color 180ms ease,
			border-color 180ms ease;
	}
	.card:hover .badge {
		color: var(--accent);
		border-color: var(--accent);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 16px 18px 18px;
		flex: 1;
	}
	.eyebrow {
		font-size: 10.5px;
		font-weight: 500;
		letter-spacing: 0.2em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	.sep {
		margin: 0 2px;
	}
	h3 {
		margin: 2px 0 0;
		font-family: var(--serif);
		font-weight: 500;
		font-size: 24px;
		line-height: 1.15;
	}
	p {
		margin: 0;
		font-size: 14px;
		line-height: 1.55;
		color: var(--ink-soft);
	}
	.go {
		margin-top: auto;
		padding-top: 10px;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 13px;
		color: var(--ink-soft);
		transition: color 150ms ease;
	}
	.card:hover .go {
		color: var(--accent);
	}
</style>
