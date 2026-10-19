import { error } from '@sveltejs/kit';
import { spaceUrl, type Space } from '$lib/types';

export async function load({ params, fetch }) {
	const res = await fetch(spaceUrl(params.space, 'space.json'));
	if (!res.ok) error(404, `No space called "${params.space}"`);
	const space: Space = await res.json();
	return { space, viewpoint: params.viewpoint ?? space.viewpoints[0].slug };
}
