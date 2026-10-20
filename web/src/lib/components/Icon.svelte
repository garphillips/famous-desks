<script lang="ts" module>
	export type IconName =
		| 'eye'
		| 'info'
		| 'door'
		| 'arrow-right'
		| 'chevron-left'
		| 'chevron-right'
		| 'plus'
		| 'minus'
		| 'expand'
		| 'collapse'
		| 'close'
		| 'mouse'
		| 'music'
		| 'books';
</script>

<script lang="ts">
	let { name, size = 18 }: { name: IconName; size?: number } = $props();
</script>

<svg
	viewBox="0 0 24 24"
	width={size}
	height={size}
	fill="none"
	stroke="currentColor"
	stroke-width="1.6"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	{#if name === 'eye'}
		<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z" />
		<circle cx="12" cy="12" r="2.6" />
	{:else if name === 'info'}
		<circle cx="12" cy="7.2" r="0.6" fill="currentColor" />
		<path d="M10.5 10.5H12v7M10.5 17.5h3" />
	{:else if name === 'door'}
		<path d="M6 20.5V4.5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v16M3.5 20.5h17M14.5 12.5h.01" />
	{:else if name === 'arrow-right'}
		<path d="M5 12h14M13 6l6 6-6 6" />
	{:else if name === 'chevron-left'}
		<path d="M15 5l-7 7 7 7" />
	{:else if name === 'chevron-right'}
		<path d="M9 5l7 7-7 7" />
	{:else if name === 'plus'}
		<path d="M12 5v14M5 12h14" />
	{:else if name === 'minus'}
		<path d="M5 12h14" />
	{:else if name === 'expand'}
		<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
	{:else if name === 'collapse'}
		<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
	{:else if name === 'close'}
		<path d="M6 6l12 12M18 6L6 18" />
	{:else if name === 'mouse'}
		<rect x="7" y="3" width="10" height="18" rx="5" />
		<path d="M12 7v3" />
	{:else if name === 'music'}
		<path d="M9 17.5V5.5l10-2v12" />
		<circle cx="6.5" cy="17.5" r="2.5" />
		<circle cx="16.5" cy="15.5" r="2.5" />
	{:else if name === 'books'}
		<rect x="3.5" y="15.5" width="17" height="4.5" rx="1" />
		<rect x="5.5" y="10.5" width="14" height="4.5" rx="1" />
		<rect x="4.5" y="5.5" width="12" height="4.5" rx="1" transform="rotate(-6 10.5 7.75)" />
		<path d="M7.5 15.5v4.5M16 10.5v4.5" />
	{/if}
</svg>
