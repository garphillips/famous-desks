/** Mirrors content/spaces/<slug>/space.json, written by blender/export.py. */

export interface SpaceIndex {
	/** Sorted by the optional SPEC "order", then slug. */
	spaces: { slug: string; title: string; order?: number }[];
}

export interface Viewpoint {
	slug: string;
	title: string;
	/** Room metres: x east, y north, z up. */
	position: [number, number, number];
	/** Equirectangular panorama path relative to the space folder (fallback when there are no tiles). */
	pano: string;
	/** Degrees, 0 = north, clockwise. */
	initialYaw: number;
	/** Cube-face tile pyramid of the same panorama, when it was rendered as cube faces. */
	tiles?: PanoTiles;
}

/**
 * A panorama as six 90° cube faces, each a multi-resolution tile pyramid
 * (written by blender/export.py through web/scripts/tile-pano.mjs).
 *
 * Faces, in this order: n, e, s, w (looking north, east, south, west, image up = up),
 * u (looking up; image top = south, right = east) and d (looking down; image top = north,
 * right = east). Tile files: `<path>/<level>/<face>-<row>-<col>.webp`, where `level` is the
 * face size in pixels at that level. Each tile holds up to tileSize x tileSize pixels of the
 * face plus a `bleed`-pixel border copied from its neighbours (clamped at the face edges),
 * so filtering is seamless across tile boundaries.
 */
export interface PanoTiles {
	/** Folder relative to the space folder, e.g. panos/office. */
	path: string;
	/** Face size in pixels at the finest level. */
	faceSize: number;
	tileSize: number;
	/** Face sizes in pixels, coarsest first; the last one is faceSize. */
	levels: number[];
	/** Border pixels around every tile (and preview face). */
	bleed: number;
	/** Image format of the tiles (file extension). */
	format: 'webp';
	/** Low-res preview for first paint: the six faces side by side (n e s w u d), relative to the space folder. */
	preview: string;
	/** Face size of the preview, without the bleed. */
	previewSize: number;
}

export interface HotspotView {
	yaw: number;
	pitch: number;
	distance: number;
}

/** Extra media for a hotspot's detail panel. Paths are relative to the space folder. */
export interface HotspotDetail {
	/** Close-up renders (details/<hotspot>/closeup-<n>.webp), in display order. */
	images: string[];
	/** glTF binary of the object (details/<hotspot>/model.glb): metres, Y-up, centred, resting on y=0. */
	model?: string;
}

/** Clicking a hotspot with a focus moves to `viewpoint` and zooms in, where its items can be picked. */
export interface HotspotFocus {
	viewpoint: string;
	yaw: number;
	pitch: number;
	/** Vertical field of view to zoom to, degrees. */
	fov: number;
}

/** The focus viewpoint's panorama with an item taken out, for where it leaves its slot. */
export interface ItemPatch {
	viewpoint: string;
	face: 'n' | 'e' | 's' | 'w' | 'u' | 'd';
	/** Face size in px the rect is measured at. */
	faceSize: number;
	/** x, y, width, height in face px (top-left origin); padded by a few px for feathering. */
	rect: [number, number, number, number];
	image: string;
}

/**
 * A featured book on a shelf (blender/lib/featured.py). Its own axes, as in Blender: x across
 * the thickness (front cover at +x), y the depth (spine at -y), z up, origin at the middle of
 * the bottom. Paths are relative to the space folder.
 */
export interface HotspotItem {
	slug: string;
	title: string;
	author: string;
	summary: string;
	kind: 'paperback' | 'hardback';
	cover: string;
	spine: string;
	coverAspect: number;
	coverColour: string;
	spineColour: string;
	/** Thickness, height, width (m). */
	size: [number, number, number];
	/** Room metres (x east, y north, z up). */
	position: [number, number, number];
	/** Quaternion w, x, y, z in room axes. */
	rotation: [number, number, number, number];
	patches: ItemPatch[];
}

export interface Hotspot {
	slug: string;
	title: string;
	kind: 'hotspot' | 'door';
	icon: 'eye' | 'info' | 'door' | 'music';
	summary: string;
	position: [number, number, number];
	/** Only viewpoints the hotspot is visible from. */
	views: Record<string, HotspotView>;
	/** For doors: the space slug they lead to ('' = not connected yet). */
	target?: string;
	/** For doors: viewpoint slug to land at in the target space (the one nearest this door). */
	arrive?: string;
	/** For doors: the target space's title, for "Go to <title>". */
	targetTitle?: string;
	/** Close-ups and 3D model, when the space has them. */
	detail?: HotspotDetail;
	/** Zoom-in target, for hotspots whose items can be picked (e.g. books on a shelf). */
	focus?: HotspotFocus;
	items?: HotspotItem[];
	/** Spotify playlist id: the hotspot opens a player for it. */
	playlist?: string;
}

export interface FloorPlan {
	width: number;
	depth: number;
	wallThickness: number;
	/** center/width along the wall: west->east on N/S walls, south->north on E/W walls. */
	openings: { wall: 'N' | 'E' | 'S' | 'W'; kind: 'window' | 'door'; center: number; width: number }[];
	/** Footprints of floor-standing furniture, room metres. */
	items: { name: string; points: [number, number][] }[];
}

export interface Space {
	slug: string;
	title: string;
	plan: { image: string; center: [number, number]; size: number };
	floorPlan: FloorPlan;
	viewpoints: Viewpoint[];
	hotspots: Hotspot[];
}

export const spaceUrl = (space: string, path = '') => `/spaces/${space}/${path}`;
