<script lang="ts">
	import Tour from '$lib/components/Tour.svelte';

	let { data } = $props();
</script>

<svelte:head>
	<title>{data.space.title} · Famous Desks</title>
</svelte:head>

<Tour space={data.space} viewpointSlug={data.viewpoint} />
