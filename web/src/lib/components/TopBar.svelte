<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from './Icon.svelte';
	import { site } from '$lib/site';
	import { loadSpaces, type SpaceSummary } from '$lib/spaces';

	let {
		title,
		active,
		exploreHref
	}: { title: string; active: 'explore' | 'objects' | 'about'; exploreHref: string } = $props();

	let fullscreen = $state(false);

	// --- Spaces menu ---------------------------------------------------------
	let spaces: SpaceSummary[] = $state([]);
	let spacesError = $state(false);
	let menuOpen = $state(false);
	let spacesRoot: HTMLDivElement;
	let spacesButton: HTMLButtonElement;
	let list: HTMLUListElement | undefined = $state();
	const currentSpace = $derived(page.params.space ?? '');
	const menuId = 'spaces-menu';

	onMount(() => {
		const sync = () => (fullscreen = !!document.fullscreenElement);
		document.addEventListener('fullscreenchange', sync);
		loadSpaces()
			.then((s) => (spaces = s.filter((x) => !site.hiddenSpaces.includes(x.slug))))
			.catch(() => (spacesError = true));
		return () => document.removeEventListener('fullscreenchange', sync);
	});

	afterNavigate(() => (menuOpen = false));

	function toggleFullscreen() {
		if (document.fullscreenElement) document.exitFullscreen();
		else document.documentElement.requestFullscreen?.();
	}

	const items = () => Array.from(list?.querySelectorAll<HTMLAnchorElement>('a') ?? []);

	async function openMenu() {
		menuOpen = true;
		await tick();
		const all = items();
		(all.find((a) => a.getAttribute('aria-current') === 'page') ?? all[0])?.focus();
	}

	function closeMenu(returnFocus = true) {
		if (!menuOpen) return;
		menuOpen = false;
		if (returnFocus) spacesButton?.focus();
	}

	function onMenuKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			closeMenu();
			return;
		}
		const all = items();
		if (!all.length || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
		e.preventDefault();
		const i = all.indexOf(document.activeElement as HTMLAnchorElement);
		const next =
			e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (i + (e.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length;
		all[next].focus();
	}

	function onButtonKeydown(e: KeyboardEvent) {
		if (e.key === 'ArrowDown' && !menuOpen) {
			e.preventDefault();
			openMenu();
		}
	}

	// Close when focus or a click leaves the control.
	function onFocusOut(e: FocusEvent) {
		if (menuOpen && !spacesRoot.contains(e.relatedTarget as Node | null)) closeMenu(false);
	}
	function onWindowPointerDown(e: PointerEvent) {
		if (menuOpen && !spacesRoot.contains(e.target as Node)) closeMenu(false);
	}

	const pad = (n: number) => String(n).padStart(2, '0');

	const links = $derived([
		{ id: 'explore', label: 'Explore', href: exploreHref },
		{ id: 'objects', label: 'Objects', href: '/objects' },
		{ id: 'about', label: 'About', href: '/about' }
	] as const);
</script>

<svelte:window onpointerdown={onWindowPointerDown} />

<header class="topbar">
	<a class="wordmark" href={exploreHref}>
		<span class="name">{(site.name || title).toLowerCase()} <span class="dash">—</span></span>
		<span class="tagline">{site.tagline}</span>
	</a>

	<div class="right">
		<div class="spaces" bind:this={spacesRoot} onfocusout={onFocusOut} onkeydown={onMenuKeydown} role="presentation">
			<button
				bind:this={spacesButton}
				class="spaces-button"
				class:open={menuOpen}
				aria-expanded={menuOpen}
				aria-controls={menuId}
				aria-haspopup="true"
				onclick={() => (menuOpen ? closeMenu() : openMenu())}
				onkeydown={onButtonKeydown}
			>
				<svg class="stack" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
					stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M12 3.5l8.5 4.5L12 12.5 3.5 8z" />
					<path d="M3.5 12.2L12 16.7l8.5-4.5M3.5 16.2L12 20.7l8.5-4.5" />
				</svg>
				<span class="label">Spaces</span>
				<svg class="chevron" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"
					stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M6 9.5l6 6 6-6" />
				</svg>
			</button>

			{#if menuOpen}
				<div class="popover" id={menuId}>
					<p class="heading">
						<span>Spaces</span>
						{#if spaces.length}<span class="count">{spaces.length}</span>{/if}
					</p>
					{#if spaces.length}
						<ul bind:this={list} aria-label="Spaces">
							{#each spaces as s, i (s.slug)}
								{@const here = s.slug === currentSpace}
								<li>
									<a
										href="/{s.slug}"
										class:here
										aria-current={here ? 'page' : undefined}
										onclick={() => closeMenu(false)}
									>
										<span class="num">{pad(i + 1)}</span>
										<span class="title">{s.title}</span>
										{#if here}<span class="badge">You're here</span>{/if}
									</a>
								</li>
							{/each}
						</ul>
						<p class="soon">More coming soon</p>
					{:else}
						<p class="empty">{spacesError ? "Couldn't load the list of spaces." : 'Loading…'}</p>
					{/if}
				</div>
			{/if}
		</div>

		{#if site.showPages}
			<nav aria-label="Main">
				{#each links as link (link.id)}
					<a href={link.href} class:active={link.id === active} aria-current={link.id === active ? 'page' : undefined}
						>{link.label}</a
					>
				{/each}
			</nav>
		{/if}
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
		min-width: 0;
		text-decoration: none;
		text-shadow: 0 1px 12px rgba(0, 0, 0, 0.45);
	}
	.name {
		font-family: var(--serif);
		font-weight: 500;
		font-size: 30px;
		line-height: 1;
		letter-spacing: 0.01em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
		flex-shrink: 0;
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

	/* --- Spaces menu --- */
	.spaces {
		position: relative;
	}
	.spaces-button {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 40px;
		padding: 0 14px 0 13px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--panel);
		backdrop-filter: var(--blur);
		font-size: 14px;
		cursor: pointer;
		transition: border-color 150ms ease;
	}
	.spaces-button:hover,
	.spaces-button.open {
		border-color: var(--ink-soft);
	}
	.stack {
		color: var(--accent);
	}
	.chevron {
		color: var(--ink-soft);
		transition: transform 180ms ease;
	}
	.spaces-button.open .chevron {
		transform: rotate(180deg);
	}
	.popover {
		position: absolute;
		top: calc(100% + 10px);
		right: 0;
		z-index: 20;
		width: 300px;
		max-height: min(70vh, 520px);
		overflow-y: auto;
		padding: 14px 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius);
		background: var(--panel);
		backdrop-filter: var(--blur);
		box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
		animation: pop 160ms ease-out;
	}
	@keyframes pop {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
	}
	.heading {
		display: flex;
		justify-content: space-between;
		margin: 0 12px 8px;
		font-size: 10.5px;
		font-weight: 500;
		letter-spacing: 0.24em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	.count {
		letter-spacing: 0.08em;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li a {
		display: flex;
		align-items: baseline;
		gap: 12px;
		padding: 10px 12px;
		border-radius: 10px;
		text-decoration: none;
		color: var(--ink-soft);
		transition:
			background 150ms ease,
			color 150ms ease;
	}
	li a:hover,
	li a:focus-visible {
		background: rgba(244, 241, 234, 0.08);
		color: var(--ink);
	}
	li a:focus-visible {
		outline-offset: -2px;
	}
	.num {
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		color: var(--ink-faint);
	}
	.title {
		position: relative;
		flex: 1;
		min-width: 0;
		font-family: var(--serif);
		font-size: 21px;
		line-height: 1.15;
	}
	li a.here {
		color: var(--ink);
	}
	li a.here .title {
		flex: 0 1 auto;
	}
	li a.here .title::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: -2px;
		height: 1.5px;
		background: var(--accent);
	}
	.badge {
		margin-left: auto;
		font-size: 10px;
		font-weight: 500;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		white-space: nowrap;
		color: var(--accent);
	}
	.soon {
		margin: 6px 12px 6px 42px;
		font-size: 10.5px;
		font-weight: 500;
		letter-spacing: 0.24em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
	.empty {
		margin: 4px 12px 8px;
		font-size: 13px;
		color: var(--ink-soft);
	}

	@media (max-width: 400px) {
		.topbar .dash {
			display: none;
		}
		.topbar .name {
			font-size: 21px;
		}
		.topbar .right {
			gap: 10px;
		}
		.topbar nav {
			gap: 11px;
		}
		.topbar nav a {
			font-size: 12.5px;
		}
		.topbar .spaces-button {
			width: 34px;
			height: 34px;
		}
	}

	@media (max-width: 600px) {
		.topbar {
			padding: 16px;
			gap: 12px;
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
		.spaces {
			position: static;
		}
		.spaces-button {
			width: 36px;
			height: 36px;
			padding: 0;
			justify-content: center;
		}
		.spaces-button .label {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip-path: inset(50%);
			white-space: nowrap;
		}
		.spaces-button .chevron {
			display: none;
		}
		.popover {
			position: fixed;
			top: 64px;
			left: 16px;
			right: 16px;
			width: auto;
		}
	}
</style>
