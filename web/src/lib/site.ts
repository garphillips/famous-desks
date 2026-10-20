/** Site-wide settings. The wordmark shows the site name (the current space's name
 *  when it is empty). */
export const site = {
	name: 'Famous Desks',
	tagline: 'The Jobs room',
	/** Always-visible credit under the wordmark. */
	credit: { label: 'Created by Gareth', href: 'https://garphillips.com' },
	/** The Explore / Objects / About links in the top bar (the pages still work by URL). */
	showPages: false,
	/** Spaces left out of the Spaces menu for now. */
	hiddenSpaces: ['hallway'],
	/** Hotspots (by slug) left out of the tour and the Objects page for now. */
	hiddenHotspots: ['tripod', 'east_window']
};
