import { site } from '$lib/site';
import { spaceUrl, type Hotspot, type Space, type SpaceIndex, type Viewpoint } from '$lib/types';

type Fetch = typeof fetch;

export async function loadIndex(fetch: Fetch): Promise<SpaceIndex> {
	const res = await fetch('/spaces/index.json');
	if (!res.ok) throw new Error(`Couldn't load the space index (${res.status})`);
	return res.json();
}

export async function loadSpace(fetch: Fetch, slug: string): Promise<Space> {
	const res = await fetch(spaceUrl(slug, 'space.json'));
	if (!res.ok) throw new Error(`Couldn't load space "${slug}" (${res.status})`);
	return res.json();
}

/** Every space shown on the site (site.hiddenSpaces aren't loaded: they may not be deployed). */
export async function loadSpaces(fetch: Fetch): Promise<Space[]> {
	const index = await loadIndex(fetch);
	const shown = index.spaces.filter((s) => !site.hiddenSpaces.includes(s.slug));
	return Promise.all(shown.map((s) => loadSpace(fetch, s.slug)));
}

/** The viewpoint the hotspot is seen closest from, or undefined if it isn't visible anywhere. */
export function bestViewpoint(space: Space, hotspot: Hotspot): Viewpoint | undefined {
	let best: Viewpoint | undefined;
	let bestDistance = Infinity;
	for (const v of space.viewpoints) {
		const view = hotspot.views[v.slug];
		if (view && view.distance < bestDistance) {
			best = v;
			bestDistance = view.distance;
		}
	}
	return best;
}

/** Tour link that opens at a viewpoint, facing the hotspot with its card open. */
export const hotspotHref = (space: string, viewpoint: string, hotspot: string) =>
	`/${space}/${viewpoint}?h=${encodeURIComponent(hotspot)}`;
