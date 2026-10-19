<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from './Icon.svelte';
	import { site } from '$lib/site';

	let {
		title,
		active,
		exploreHref
	}: { title: string; active: 'explore' | 'objects' | 'about'; exploreHref: string } = $props();

	let fullscreen = $state(false);

	onMount(() => {
		const sync = () => (fullscreen = !!document.fullscreenElement);
		document.addEventListener('fullscreenchange', sync);
		return () => document.removeEventListener('fullscreenchange', sync);
	});

	function toggleFullscreen() {
		if (document.fullscreenElement) document.exitFullscreen();
		else document.documentElement.requestFullscreen?.();
	}

	const links = $derived([
		{ id: 'explore', label: 'Explore', href: exploreHref },
		{ id: 'objects', label: 'Objects', href: '/objects' },
		{ id: 'about', label: 'About', href: '/about' }
	] as const);
</script>

<header class="topbar">
	<a class="wordmark" href={exploreHref}>
		<span class="name">{(site.name || title).toLowerCase()} <span class="dash">—</span></span>
		<span class="tagline">{site.tagline}</span>
	</a>

	<div class="right">
		<nav aria-label="Main">
			{#each links as link (link.id)}
				<a href={link.href} class:active={link.id === active} aria-current={link.id === active ? 'page' : undefined}
					>{link.label}</a
				>
			{/each}
		</nav>
		<button class="fullscreen" onclick={toggleFullscreen} aria-label={fullscreen ? 'Exit full screen' : 'Full screen'}>
			<Icon name={fullscreen ? 'collapse' : 'expand'} size={17} />
		</button>
	</div>
</header>

<style>
	.topbar {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
		padding: 22px 28px;
		pointer-events: none;
	}
	.topbar > * {
		pointer-events: auto;
	}
	.wordmark {
		display: flex;
		flex-direction: column;
		gap: 4px;
		text-decoration: none;
		text-shadow: 0 1px 12px rgba(0, 0, 0, 0.45);
	}
	.name {
		font-family: var(--serif);
		font-weight: 500;
		font-size: 30px;
		line-height: 1;
		letter-spacing: 0.01em;
	}
	.dash {
		font-weight: 400;
	}
	.tagline {
		font-size: 10.5px;
		font-weight: 500;
		letter-spacing: 0.24em;
		text-transform: uppercase;
		color: var(--ink-soft);
	}
	.right {
		display: flex;
		align-items: center;
		gap: 22px;
	}
	nav {
		display: flex;
		gap: 26px;
	}
	nav a {
		position: relative;
		font-size: 14px;
		text-decoration: none;
		color: var(--ink-soft);
		padding: 6px 0;
		text-shadow: 0 1px 10px rgba(0, 0, 0, 0.5);
		transition: color 150ms ease;
	}
	nav a:hover,
	nav a.active {
		color: var(--ink);
	}
	nav a.active::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: -2px;
		height: 1.5px;
		background: var(--accent);
	}
	.fullscreen {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		border: 1px solid var(--line);
		background: var(--panel);
		backdrop-filter: var(--blur);
		display: grid;
		place-items: center;
		cursor: pointer;
		transition: border-color 150ms ease;
	}
	.fullscreen:hover {
		border-color: var(--ink-soft);
	}

	@media (max-width: 600px) {
		.topbar {
			padding: 16px;
		}
		.name {
			font-size: 24px;
		}
		.tagline {
			display: none;
		}
		.right {
			gap: 12px;
		}
		nav {
			gap: 14px;
		}
		nav a {
			font-size: 13px;
		}
		.fullscreen {
			display: none;
		}
	}
</style>
