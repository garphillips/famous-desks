<script lang="ts" module>
	/** The parts of Spotify's iFrame API used here (https://developer.spotify.com/documentation/embeds). */
	interface EmbedController {
		addListener(event: 'playback_update', cb: (e: { data: { isPaused: boolean } }) => void): void;
		destroy(): void;
	}
	interface IFrameAPI {
		createController(
			element: HTMLElement,
			options: { uri: string; width: string; height: number },
			ready: (controller: EmbedController) => void
		): void;
	}

	// Spotify's script loads once per page.
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
		spaceTitle,
		onplaying
	}: {
		hotspot: Hotspot;
		spaceTitle: string;
		/** Whether music is playing (the speaker glows while it is). */
		onplaying: (playing: boolean) => void;
	} = $props();

	let host: HTMLDivElement;
	let controller: EmbedController | null = null;
	let failed = $state(false);
	// The story behind the songs shows on hover; this pins it open (touch screens, keyboard).
	let about = $state(false);
	let destroyed = false;

	const link = $derived(`https://open.spotify.com/playlist/${hotspot.playlist}`);

	onMount(() => {
		loadApi()
			.then((IFrameAPI) => {
				if (destroyed) return;
				IFrameAPI.createController(host, { uri: `spotify:playlist:${hotspot.playlist}`, width: '100%', height: 80 }, (c) => {
					if (destroyed) return c.destroy();
					controller = c;
					c.addListener('playback_update', (e) => onplaying(!e.data.isPaused));
				});
			})
			.catch(() => (failed = true));
	});

	onDestroy(() => {
		destroyed = true;
		controller?.destroy();
		onplaying(false);
	});
</script>

<div class="music" class:about role="region" aria-labelledby="music-title">
	{#if hotspot.summary}
		<div class="context" id="music-about">
			<div>
				<span class="eyebrow">{spaceTitle}</span>
				<p>{hotspot.summary}</p>
			</div>
		</div>
	{/if}
	<div class="dock-bar">
		<Icon name="music" size={14} />
		<span id="music-title">{hotspot.title}</span>
		{#if hotspot.summary}
			<button
				onclick={() => (about = !about)}
				aria-label="Why these songs"
				aria-expanded={about}
				aria-controls="music-about"
			>
				<Icon name="info" size={14} />
			</button>
		{/if}
	</div>
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
	.music {
		width: 340px;
		max-width: 100%;
		display: flex;
		flex-direction: column;
		border-radius: 16px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
		overflow: hidden;
	}
	/* Opens upwards from the bar, so the player itself never moves. */
	.context {
		display: grid;
		grid-template-rows: 0fr;
		opacity: 0;
		transition:
			grid-template-rows 280ms cubic-bezier(0.2, 0.8, 0.2, 1),
			opacity 200ms ease;
	}
	.context > div {
		min-height: 0;
		overflow: hidden;
	}
	.music:hover .context,
	.music.about .context {
		grid-template-rows: 1fr;
		opacity: 1;
	}
	.eyebrow {
		display: block;
		padding: 18px 18px 0;
		font-size: 10.5px;
		letter-spacing: 0.22em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	.context p {
		margin: 8px 18px 4px;
		font-size: 13.5px;
		line-height: 1.55;
		color: var(--ink-soft);
	}
	.player {
		padding: 0 8px 8px;
	}
	.player :global(iframe) {
		display: block;
		width: 100%;
		height: 80px;
		border: 0;
		border-radius: 12px;
		color-scheme: normal;
	}
	.fallback {
		margin: 0;
		padding: 4px 6px;
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
	.dock-bar button:hover,
	.dock-bar button[aria-expanded='true'] {
		background: var(--accent-wash);
		color: var(--ink);
	}
</style>
