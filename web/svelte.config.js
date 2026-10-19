import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
export default {
	preprocess: vitePreprocess(),
	kit: {
		// Single-page app: every tour URL falls back to the same shell.
		adapter: adapter({ fallback: '200.html' }),
		// Exported Blender content (content/spaces/...) is served as static files at /spaces/...
		files: { assets: '../content' }
	}
};
