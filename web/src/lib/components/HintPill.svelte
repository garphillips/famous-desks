<script lang="ts">
	import Icon from './Icon.svelte';

	const touch = matchMedia('(pointer: coarse)').matches;
</script>

<div class="hint" role="note">
	{#if touch}
		<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6"
			stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V10m0-1.5a1.5 1.5 0 0 1 3 0V11m0-1a1.5 1.5 0 0 1 3 0v4.5a6 6 0 0 1-6 6h-.6a5 5 0 0 1-3.9-1.9L4.6 15a1.5 1.5 0 0 1 2.3-1.9L9 15" />
		</svg>
	{:else}
		<Icon name="mouse" size={22} />
	{/if}
	<div class="text">
		<strong>Drag to look around</strong>
		<span>{touch ? 'Pinch to zoom' : 'Scroll to zoom'}</span>
	</div>
</div>

<style>
	.hint {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 18px 10px 14px;
		border-radius: 999px;
		background: var(--panel);
		backdrop-filter: var(--blur);
		border: 1px solid rgba(244, 241, 234, 0.08);
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
	}
	.text {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	strong {
		font-size: 12.5px;
		font-weight: 500;
	}
	span {
		font-size: 12px;
		color: var(--ink-soft);
	}
</style>
