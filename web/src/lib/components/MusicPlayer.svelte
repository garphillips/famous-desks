<script lang="ts" module>
	/** The parts of Spotify's iFrame API used here (https://developer.spotify.com/documentation/embeds). */
	interface EmbedController {
		addListener(event: 'playback_update', cb: (e: { data: { isPaused: boolean } }) => void): void;
		pause(): void;
		destroy(): void;
	}
	interface IFrameAPI {
		createController(
			element: HTMLElement,
			options: { uri: string; width: string; height: number },
			ready: (controller: EmbedController) => void
		): void;
	}

	// Spotify's script loads once per page, and only when a player first opens.
	let api: Promise<IFrameAPI> | null = null;
	function loadApi() {
		api ??= new Promise<IFrameAPI>((resolve, reject) => {
			(window as unknown as { onSpotifyIframeApiReady: (a: IFrameAPI) => void }).onSpotifyIframeApiReady = resolve;
			const script = document.createElement('script');
			script.src = 'https://open.spotify.com/embed/iframe-api/v1';
			script.async = true;
			script.onerror = () => {
				api = null;
				script.remove();
				reject(new Error("Spotify's player didn't load"));
			};
			document.head.append(script);
		});
		return api;
	}
</script>

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import Icon from './Icon.svelte';
	import type { Hotspot } from '$lib/types';

	let {
		hotspot,
		open,
		spaceTitle,
		onclose,
		onopen
	}: {
		hotspot: Hotspot;
		/** The full panel; otherwise a small player in the corner, so music plays on while you look around. */
		open: boolean;
		spaceTitle: string;
		/** `playing`: whether music is playing, so the player stays in the corner. */
		onclose: (playing: boolean) => void;
		onopen: () => void;
	} = $props();

	let host: HTMLDivElement;
	let closeButton: HTMLButtonElement | undefined = $state();
	let controller: EmbedController | null = null;
	let playing = $state(false);
	let failed = $state(false);
	let destroyed = false;

	const link = $derived(`https://open.spotify.com/playlist/${hotspot.playlist}`);

	onMount(() => {
		loadApi()
			.then((IFrameAPI) => {
				if (destroyed) return;
				IFrameAPI.createController(host, { uri: `spotify:playlist:${hotspot.playlist}`, width: '100%', height: 352 }, (c) => {
					if (destroyed) return c.destroy();
					controller = c;
					c.addListener('playback_update', (e) => (playing = !e.data.isPaused));
				});
			})
			.catch(() => (failed = true));
	});

	onDestroy(() => {
		destroyed = true;
		controller?.destroy();
	});

	$effect(() => {
		if (open) closeButton?.focus();
	});

	function stop() {
		controller?.pause();
		playing = false;
		onclose(false);
	}

	function onkeydown(e: KeyboardEvent) {
		if (open && e.key === 'Escape') onclose(playing);
	}
</script>

<svelte:window {onkeydown} />

{#if open}
	<div class="scrim" onclick={() => onclose(playing)} role="presentation"></div>
{/if}
<div
	class="music"
	class:open
	role={open ? 'dialog' : 'region'}
	aria-modal={open ? 'true' : undefined}
	aria-labelledby="music-title"
>
	{#if open}
		<button class="close" bind:this={closeButton} onclick={() => onclose(playing)} aria-label="Close">
			<Icon name="close" size={18} />
		</button>
		<div class="body">
			<span class="eyebrow">{spaceTitle}</span>
			<h2 id="music-title">{hotspot.title}</h2>
			{#if hotspot.summary}<p>{hotspot.summary}</p>{/if}
		</div>
	{:else}
		<div class="dock-bar">
			<Icon name="music" size={14} />
			<span id="music-title">{hotspot.title}</span>
			<button onclick={onopen} aria-label="Show the playlist"><Icon name="expand" size={14} /></button>
			<button onclick={stop} aria-label="Stop the music"><Icon name="close" size={14} /></button>
		</div>
	{/if}
	<!-- Stays mounted while open or docked, so the music never restarts. -->
	<div class="player">
		<div bind:this={host}></div>
		{#if failed}
			<p class="fallback">
				The player couldn't load here. <a href={link} target="_blank" rel="noopener">Open the playlist in Spotify</a>
			</p>
		{/if}
	</div>
</div>

<style>
	.scrim {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.25);
		animation: fade 200ms ease both;
	}
	.music {
		position: absolute;
		right: 16px;
		bottom: 16px;
		width: 320px;
		display: flex;
		flex-direction: column;
		border-radius: 16px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
		overflow: hidden;
		animation: dock 300ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
	}
	.music.open {
		top: 50%;
		right: 24px;
		bottom: auto;
		width: min(420px, calc(100vw - 32px));
		max-height: calc(100% - 48px);
		transform: translateY(-50%);
		border-radius: 20px;
		overflow: auto;
		animation-name: slide;
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
	@keyframes dock {
		from {
			opacity: 0;
			transform: translateY(12px);
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
		padding: 28px 28px 16px;
	}
	.eyebrow {
		font-size: 10.5px;
		letter-spacing: 0.22em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	h2 {
		margin: 10px 0 12px;
		font-family: var(--serif);
		font-weight: 500;
		font-size: 34px;
		line-height: 1.05;
	}
	p {
		margin: 0 0 8px;
		font-size: 14.5px;
		line-height: 1.6;
		color: var(--ink-soft);
	}
	.player {
		padding: 0 16px 16px;
	}
	.music:not(.open) .player {
		padding: 0 8px 8px;
	}
	.player :global(iframe) {
		display: block;
		width: 100%;
		height: 352px;
		border: 0;
		border-radius: 12px;
		color-scheme: normal;
	}
	/* Spotify's compact layout, same player */
	.music:not(.open) .player :global(iframe) {
		height: 80px;
	}
	.fallback {
		margin: 0;
		font-size: 13px;
	}
	.fallback a {
		color: var(--accent);
	}
	.dock-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 6px 6px 14px;
		font-size: 11px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	.dock-bar span {
		flex: 1;
	}
	.dock-bar button {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		border: 0;
		background: transparent;
		color: var(--ink-soft);
		display: grid;
		place-items: center;
		cursor: pointer;
	}
	.dock-bar button:hover {
		background: var(--accent-wash);
		color: var(--ink);
	}

	/* Phone: the panel is a sheet along the bottom; the small player sits above the scene bar. */
	@media (max-width: 760px) {
		.music {
			left: 12px;
			right: 12px;
			width: auto;
			bottom: calc(76px + env(safe-area-inset-bottom));
		}
		.music.open {
			top: auto;
			bottom: max(12px, env(safe-area-inset-bottom));
			right: 12px;
			width: auto;
			max-height: calc(100% - 24px);
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
			padding: 22px 22px 12px;
		}
		h2 {
			font-size: 28px;
		}
	}
</style>
