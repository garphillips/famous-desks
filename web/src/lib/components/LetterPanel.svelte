<script lang="ts">
	import '@fontsource/special-elite/400.css';
	import { onMount, tick } from 'svelte';
	import Icon from './Icon.svelte';
	import { prefersReducedMotion } from '$lib/viewer/PanoViewer';

	let {
		title,
		text,
		from,
		onclose
	}: {
		title: string;
		/** Plain text, blank lines between paragraphs. */
		text: string;
		/** Where the envelope lies on screen (the hotspot's pin). */
		from: { x: number; y: number };
		onclose: () => void;
	} = $props();

	const paragraphs = $derived(text.split(/\n\s*\n/).map((p) => p.trim()));

	let scrim: HTMLDivElement;
	let page: HTMLDivElement;
	let group: HTMLDivElement;
	let envelope: HTMLDivElement | undefined = $state();
	let flap: HTMLDivElement | undefined = $state();
	let top: HTMLDivElement | undefined = $state();
	let bottom: HTMLDivElement | undefined = $state();
	let closeButton: HTMLButtonElement;
	let height = $state(0);
	/** The letter has landed: the plain page (selectable, crisp) replaces the folding strips. */
	let flat = $state(false);
	let shown = $state(false);
	let closing = false;
	let animations: Animation[] = [];

	// One continuous move, phases overlapping: the envelope rises off the desk, its flap opens,
	// it drops away from the folded letter, and the letter unfolds, top third then bottom.
	const EASE = 'cubic-bezier(0.3, 0, 0.15, 1)';

	function play(el: Element, keyframes: Keyframe[], delay: number, duration: number) {
		const a = el.animate(keyframes, { delay, duration, easing: EASE, fill: 'both' });
		animations.push(a);
		return a;
	}

	onMount(() => {
		let cancelled = false;
		(async () => {
			// lay the page out in its own font before measuring it
			await document.fonts.load('16px "Special Elite"').catch(() => {});
			await tick();
			if (cancelled) return;
			height = page.offsetHeight;
			await tick();
			shown = true;

			// the folded letter (the middle third) starts on the pin, small and lying flat like on the desk
			const r = page.getBoundingClientRect();
			const cx = r.left + r.width / 2;
			const cy = r.top + r.height / 2;
			const scale = Math.min(0.16, 90 / r.width);
			const third = r.height / 3;
			play(scrim, [{ opacity: 0 }, { opacity: 1 }], 0, 600);
			play(group, [
				{ transform: `translate(${from.x - cx}px, ${from.y - cy}px) scale(${scale}) rotateX(58deg) rotateZ(-14deg)`, opacity: 0 },
				{ opacity: 1, offset: 0.12 },
				{ transform: 'none', opacity: 1 }
			], 0, 950);
			play(flap!, [
				{ transform: 'translateZ(4px) rotateX(0deg)' },
				{ transform: 'translateZ(-4px) rotateX(180deg)' }
			], 700, 480);
			play(envelope!, [
				{ transform: 'translateY(0)', opacity: 1 },
				{ opacity: 1, offset: 0.55 },
				{ transform: `translateY(${third * 2.2}px)`, opacity: 0 }
			], 1100, 650);
			play(top!, [
				{ transform: 'translateZ(1.6px) rotateX(-180deg)' },
				{ transform: 'translateZ(0) rotateX(0deg)' }
			], 1500, 600);
			play(bottom!, [
				{ transform: 'translateZ(0.8px) rotateX(180deg)' },
				{ transform: 'translateZ(0) rotateX(0deg)' }
			], 1750, 600);

			if (prefersReducedMotion()) animations.forEach((a) => a.finish());
			await Promise.all(animations.map((a) => a.finished)).catch(() => {});
			if (cancelled || closing) return;
			flat = true;
			closeButton.focus({ preventScroll: true });
		})();
		return () => {
			cancelled = true;
			animations.forEach((a) => a.cancel());
		};
	});

	/** Folds the letter back into its envelope and sends it back to the desk: the opening, in reverse. */
	async function close() {
		if (closing) return;
		closing = true;
		flat = false;
		if (!prefersReducedMotion() && animations.length) {
			animations.forEach((a) => a.updatePlaybackRate(-1.8));
			animations.forEach((a) => a.play());
			await Promise.all(animations.map((a) => a.finished)).catch(() => {});
		}
		onclose();
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') close();
	}
</script>

<svelte:window {onkeydown} />

{#snippet letter()}
	{#each paragraphs as p, i (i)}
		<p class:sign={i === paragraphs.length - 1 && paragraphs.length > 1}>{p}</p>
	{/each}
{/snippet}

<div class="letter-view" class:shown role="dialog" aria-modal="true" aria-label={title}>
	<div class="scrim" bind:this={scrim} onclick={close} role="presentation"></div>
	<div class="scroller" onclick={(e) => e.target === e.currentTarget && close()} role="presentation">
		<div class="stage">
			<div class="group" bind:this={group}>
				<!-- Sizes the page and, once it has landed, is the letter you read and select. -->
				<div class="page" class:flat bind:this={page}>
					<div class="type">{@render letter()}</div>
				</div>
				{#if height}
					<div class="strips" class:hidden={flat} style:--h="{height}px" aria-hidden="true">
						<div class="strip" bind:this={top} style:--k="0" style:transform-origin="50% 100%">
							<div class="face"><div class="type">{@render letter()}</div></div>
							<div class="back"></div>
						</div>
						<div class="strip middle" style:--k="1">
							<div class="face"><div class="type">{@render letter()}</div></div>
						</div>
						<div class="strip" bind:this={bottom} style:--k="2" style:transform-origin="50% 0">
							<div class="face"><div class="type">{@render letter()}</div></div>
							<div class="back"></div>
						</div>
					</div>
					<!-- A plain kraft envelope, flap side up, cut to fit the letter folded in three. -->
					<div class="envelope" class:hidden={flat} bind:this={envelope} style:--h="{height}px" aria-hidden="true">
						<div class="env-back"></div>
						<div class="pocket"></div>
						<div class="flap" bind:this={flap}></div>
					</div>
				{/if}
			</div>
		</div>
	</div>
	<button class="close" class:flat bind:this={closeButton} onclick={close} aria-label="Put the letter back">
		<Icon name="close" size={18} />
	</button>
</div>

<style>
	.letter-view {
		position: absolute;
		inset: 0;
		z-index: 5;
		--paper: #f2ead8;
		--kraft: #c4a47a;
		--kraft-dark: #a9895f;
		--type-ink: #2a2520;
		--w: min(560px, calc(100vw - 32px));
	}
	.letter-view:not(.shown) .stage {
		visibility: hidden;
	}
	.scrim {
		position: absolute;
		inset: 0;
		background: rgba(8, 8, 7, 0.62);
		backdrop-filter: blur(3px);
		opacity: 0;
	}
	.scroller {
		position: absolute;
		inset: 0;
		overflow-y: auto;
		display: flex;
		padding: 72px 16px 96px;
	}
	.stage {
		margin: auto;
		perspective: 1600px;
	}
	.group {
		position: relative;
		transform-style: preserve-3d;
	}
	.page,
	.face {
		width: var(--w);
		background:
			radial-gradient(circle at 20% 15%, rgba(255, 255, 255, 0.35), transparent 60%),
			radial-gradient(circle at 85% 90%, rgba(120, 95, 60, 0.08), transparent 55%),
			var(--paper);
	}
	.page {
		position: relative;
		min-height: calc(var(--w) * 1.294);
		opacity: 0;
		box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
	}
	.page.flat {
		opacity: 1;
	}
	/* where it was folded in three: a faint crease at each third */
	.page::after {
		content: '';
		position: absolute;
		inset: 0;
		pointer-events: none;
		background:
			linear-gradient(transparent calc(33.33% - 1px), rgba(110, 90, 60, 0.12) 33.33%, rgba(255, 255, 255, 0.5) calc(33.33% + 1px), transparent calc(33.33% + 3px)),
			linear-gradient(transparent calc(66.67% - 1px), rgba(110, 90, 60, 0.12) 66.67%, rgba(255, 255, 255, 0.5) calc(66.67% + 1px), transparent calc(66.67% + 3px));
	}
	.type {
		padding: calc(var(--w) * 0.11) calc(var(--w) * 0.1);
		font-family: 'Special Elite', 'Courier New', monospace;
		font-size: clamp(12.5px, 2.9vw, 16px);
		line-height: 1.65;
		color: var(--type-ink);
		text-align: left;
	}
	.type p {
		margin: 0 0 1.1em;
	}
	.type p.sign {
		margin-top: 1.8em;
	}

	/* The page in three strips, each showing its third of the same text, hinged on the middle one. */
	.strips {
		position: absolute;
		inset: 0;
		transform-style: preserve-3d;
	}
	.strip {
		position: absolute;
		left: 0;
		top: calc(var(--h) * var(--k) / 3);
		width: var(--w);
		height: calc(var(--h) / 3);
		transform-style: preserve-3d;
	}
	.face,
	.back {
		position: absolute;
		inset: 0;
		overflow: hidden;
		backface-visibility: hidden;
	}
	.face .type {
		position: absolute;
		left: 0;
		right: 0;
		top: calc(var(--h) * var(--k) / -3);
		min-height: var(--h);
	}
	.middle .face {
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.45);
	}
	/* the outside of the folded letter: blank paper, a shade darker */
	.back {
		transform: rotateX(180deg);
		background: linear-gradient(#e9dfca, #e3d8c1);
	}
	.hidden {
		visibility: hidden;
	}

	.envelope {
		position: absolute;
		left: calc(var(--w) * -0.035);
		width: calc(var(--w) * 1.07);
		top: calc(var(--h) / 3 - var(--h) * 0.03);
		height: calc(var(--h) * 0.4);
		transform-style: preserve-3d;
		pointer-events: none;
	}
	.env-back,
	.pocket,
	.flap {
		position: absolute;
		left: 0;
		width: 100%;
	}
	.env-back {
		inset: 0;
		background: var(--kraft-dark);
		transform: translateZ(-3px);
		box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
	}
	/* the back of the envelope, its side and bottom folds meeting under the flap */
	.pocket {
		inset: 0;
		background:
			linear-gradient(to top right, transparent 49.6%, rgba(90, 65, 35, 0.22) 50%, transparent 50.6%) left / 50% 100% no-repeat,
			linear-gradient(to top left, transparent 49.6%, rgba(90, 65, 35, 0.22) 50%, transparent 50.6%) right / 50% 100% no-repeat,
			radial-gradient(circle at 30% 30%, rgba(255, 240, 210, 0.18), transparent 60%),
			var(--kraft);
		clip-path: polygon(0 0, 50% 52%, 100% 0, 100% 100%, 0 100%);
		transform: translateZ(3px);
	}
	.flap {
		top: 0;
		height: 56%;
		background: linear-gradient(rgba(255, 240, 210, 0.12), rgba(70, 50, 25, 0.12)), var(--kraft);
		clip-path: polygon(0 0, 100% 0, 50% 100%);
		transform-origin: 50% 0;
		transform: translateZ(4px);
		filter: drop-shadow(0 2px 2px rgba(60, 40, 20, 0.3));
	}

	.close {
		position: absolute;
		top: 20px;
		right: 20px;
		width: 40px;
		height: 40px;
		border-radius: 50%;
		border: 0;
		background: var(--panel);
		backdrop-filter: var(--blur);
		color: var(--ink);
		display: grid;
		place-items: center;
		cursor: pointer;
		opacity: 0;
		transition: opacity 300ms ease;
	}
	.close.flat {
		opacity: 1;
	}
	.close:focus-visible {
		opacity: 1;
	}
</style>
