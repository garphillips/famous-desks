/** Mirrors content/spaces/<slug>/space.json, written by blender/export.py. */

export interface SpaceIndex {
	spaces: { slug: string; title: string }[];
}

export interface Viewpoint {
	slug: string;
	title: string;
	/** Room metres: x east, y north, z up. */
	position: [number, number, number];
	/** Panorama path relative to the space folder. */
	pano: string;
	/** Degrees, 0 = north, clockwise. */
	initialYaw: number;
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

export interface Hotspot {
	slug: string;
	title: string;
	kind: 'hotspot' | 'door';
	icon: 'eye' | 'info' | 'door';
	summary: string;
	position: [number, number, number];
	/** Only viewpoints the hotspot is visible from. */
	views: Record<string, HotspotView>;
	/** For doors: the space slug they lead to ('' = not connected yet). */
	target?: string;
	/** Close-ups and 3D model, when the space has them. */
	detail?: HotspotDetail;
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
