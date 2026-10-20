<script lang="ts">
	import TopBar from '$lib/components/TopBar.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import { site } from '$lib/site';

	let { data } = $props();

	const exploreHref = $derived(data.first ? `/${data.first.slug}` : '/');
	const name = $derived(site.name || 'This site');
</script>

<svelte:head>
	<title>About{site.name ? ` · ${site.name}` : ''}</title>
</svelte:head>

<div class="page">
	<TopBar title={data.first?.title ?? ''} active="about" {exploreHref} />

	<main>
		<p class="draft" role="note">Draft copy, to be rewritten</p>

		<header>
			<span class="eyebrow">About</span>
			<h1>A room you can walk around</h1>
			<p class="lede">
				{name} is an explorable office, modelled and rendered in Blender, that you can look around from a few
				spots in the room.
			</p>
		</header>

		<section>
			<h2>How to use it</h2>
			<ul class="steps">
				<li><strong>Drag</strong> to look around, or use the arrow keys.</li>
				<li><strong>Scroll</strong> or pinch to zoom in and out.</li>
				<li><strong>Click a pin</strong> to see what an object is, and again (or use its arrow) to look closer.</li>
				<li><strong>Change spot</strong> with the floor plan.</li>
			</ul>
		</section>

		<section>
			<h2>How it’s made</h2>
			<p>
				The room was modelled in Blender from reference photos and a floor-plan sketch, then rendered as 360°
				panoramas from each viewpoint. The site stitches those panoramas together with clickable hotspots.
			</p>
		</section>

		<a class="cta" href={exploreHref}>Start exploring <Icon name="arrow-right" size={16} /></a>
	</main>
</div>

<style>
	.page {
		min-height: 100%;
		background: var(--bg);
	}
	main {
		max-width: 680px;
		margin: 0 auto;
		padding: 48px 28px 96px;
	}
	.draft {
		display: inline-block;
		margin: 0 0 32px;
		padding: 5px 12px;
		border: 1px dashed var(--accent);
		border-radius: 999px;
		font-size: 13px;
		font-weight: 300;
		color: var(--accent);
	}
	.eyebrow {
		font-size: 13px;
		font-weight: 300;
		color: var(--accent);
	}
	h1 {
		margin: 12px 0 18px;
		font-family: var(--heading);
		font-weight: 600;
		font-size: clamp(34px, 6vw, 50px);
		letter-spacing: -0.01em;
		line-height: 1.02;
	}
	.lede {
		margin: 0;
		font-family: var(--heading);
		font-weight: 600;
		font-size: 20px;
		letter-spacing: -0.01em;
		line-height: 1.4;
		color: var(--ink-soft);
	}
	section {
		margin-top: 48px;
		padding-top: 28px;
		border-top: 1px solid var(--line);
	}
	h2 {
		margin: 0 0 14px;
		font-family: var(--heading);
		font-weight: 600;
		font-size: 23px;
		letter-spacing: -0.01em;
		line-height: 1.15;
	}
	p,
	.steps {
		font-size: 16px;
		line-height: 1.7;
		color: var(--ink-soft);
	}
	section p {
		margin: 0;
	}
	.steps {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 8px;
	}
	.steps li {
		position: relative;
		padding-left: 20px;
	}
	.steps li::before {
		content: '';
		position: absolute;
		left: 2px;
		top: 0.75em;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--accent);
	}
	strong {
		font-weight: 500;
		color: var(--ink);
	}
	.cta {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		margin-top: 48px;
		padding: 12px 20px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--panel);
		backdrop-filter: var(--blur);
		font-size: 14px;
		text-decoration: none;
		transition: border-color 150ms ease;
	}
	.cta:hover {
		border-color: var(--accent);
	}

	@media (max-width: 600px) {
		main {
			padding: 24px 16px 64px;
		}
		.lede {
			font-size: 21px;
		}
	}
</style>
