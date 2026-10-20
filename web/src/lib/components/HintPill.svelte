<script lang="ts">
	import Icon from './Icon.svelte';

	const touch = matchMedia('(pointer: coarse)').matches;
</script>

<div class="hint" role="note">
	{#if touch}
		<Icon name="hand" size={22} />
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
