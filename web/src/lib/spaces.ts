import type { SpaceIndex } from './types';

export type SpaceSummary = SpaceIndex['spaces'][number];

let cached: Promise<SpaceSummary[]> | undefined;

/** All spaces from content/spaces/index.json (already sorted by export.py), fetched once per session. */
export function loadSpaces(fetcher: typeof fetch = fetch): Promise<SpaceSummary[]> {
	cached ??= fetcher('/spaces/index.json')
		.then((res) => {
			if (!res.ok) throw new Error(`index.json: ${res.status}`);
			return res.json() as Promise<SpaceIndex>;
		})
		.then((index) => index.spaces)
		.catch((err) => {
			cached = undefined; // let a later call retry
			throw err;
		});
	return cached;
}
