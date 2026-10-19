import { redirect } from '@sveltejs/kit';
import type { SpaceIndex } from '$lib/types';

// Until there's a landing page, open the first space.
export async function load({ fetch }) {
	const index: SpaceIndex = await (await fetch('/spaces/index.json')).json();
	redirect(307, `/${index.spaces[0].slug}`);
}
