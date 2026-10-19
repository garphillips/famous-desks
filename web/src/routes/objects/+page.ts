import { error } from '@sveltejs/kit';
import { loadSpaces } from '$lib/content';

export async function load({ fetch }) {
	try {
		return { spaces: await loadSpaces(fetch) };
	} catch (err) {
		error(500, err instanceof Error ? err.message : 'Couldn’t load the spaces');
	}
}
