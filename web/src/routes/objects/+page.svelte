<script lang="ts">
	import TopBar from '$lib/components/TopBar.svelte';
	import ObjectsCard from '$lib/components/ObjectsCard.svelte';
	import { bestViewpoint, hotspotHref } from '$lib/content';
	import { site } from '$lib/site';

	let { data } = $props();

	const first = $derived(data.spaces[0]);
	const groups = $derived(
		data.spaces
			.map((space) => ({
				space,
				objects: space.hotspots.flatMap((hotspot) => {
					if (hotspot.kind !== 'hotspot' || hotspot.playlist || site.hiddenHotspots.includes(hotspot.slug)) return [];
					const viewpoint = bestViewpoint(space, hotspot);
					return viewpoint ? [{ hotspot, viewpoint }] : [];
				})
			}))
			.filter((g) => g.objects.length)
	);
</script>

<svelte:head>
	<title>Objects · Famous Desks</title>
</svelte:head>

<div class="page">
	<TopBar title={first?.title ?? ''} active="objects" exploreHref={first ? `/${first.slug}` : '/'} />

	<main>
		<header class="intro">
			<span class="eyebrow">Objects</span>
			<h1>Things to look at</h1>
			<p>Every object you can open in the tour. Pick one to jump straight to it.</p>
		</header>

		{#each groups as { space, objects } (space.slug)}
			<section aria-labelledby="space-{space.slug}">
				<div class="space-head">
					<h2 id="space-{space.slug}">{space.title}</h2>
					<span class="count">{objects.length} {objects.length === 1 ? 'object' : 'objects'}</span>
				</div>
				<ul class="grid">
					{#each objects as { hotspot, viewpoint } (hotspot.slug)}
						<li>
							<ObjectsCard
								{hotspot}
								href={hotspotHref(space.slug, viewpoint.slug, hotspot.slug)}
								spaceTitle={space.title}
								viewpointTitle={viewpoint.title}
							/>
						</li>
					{/each}
				</ul>
			</section>
		{:else}
			<p class="empty">No objects yet.</p>
		{/each}
	</main>
</div>

<style>
	.page {
		min-height: 100%;
		background: var(--bg);
	}
	main {
		max-width: var(--page-width);
		margin: 0 auto;
		padding: 40px 28px 96px;
	}
	.intro {
		max-width: 620px;
		margin-bottom: 56px;
	}
	.eyebrow {
		font-size: 13px;
		font-weight: 300;
		color: var(--accent);
	}
	h1 {
		margin: 12px 0 14px;
		font-family: var(--heading);
		font-weight: 600;
		font-size: clamp(34px, 5vw, 50px);
		letter-spacing: -0.01em;
		line-height: 1.02;
	}
	.intro p {
		margin: 0;
		font-size: 16px;
		line-height: 1.6;
		color: var(--ink-soft);
	}
	section + section {
		margin-top: 64px;
	}
	.space-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 16px;
		padding-bottom: 14px;
		margin-bottom: 24px;
		border-bottom: 1px solid var(--line);
	}
	h2 {
		margin: 0;
		font-family: var(--heading);
		font-weight: 600;
		font-size: 26px;
		letter-spacing: -0.01em;
		line-height: 1.1;
	}
	.count {
		font-size: 13px;
		color: var(--ink-faint);
		white-space: nowrap;
	}
	.grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr));
		gap: 20px;
	}
	.grid li {
		display: flex;
		min-width: 0;
	}
	.grid li > :global(*) {
		flex: 1;
	}
	.empty {
		color: var(--ink-soft);
	}

	@media (max-width: 600px) {
		main {
			padding: 24px 16px 64px;
		}
		.intro {
			margin-bottom: 40px;
		}
		h2 {
			font-size: 28px;
		}
		.grid {
			gap: 16px;
		}
	}
</style>
