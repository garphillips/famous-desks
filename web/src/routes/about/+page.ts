import { loadIndex } from '$lib/content';

export async function load({ fetch }) {
	const index = await loadIndex(fetch).catch(() => ({ spaces: [] }));
	return { first: index.spaces[0] };
}
