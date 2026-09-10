<script lang="ts">
	export let label: string;
	export let type: 'button' | 'submit' = 'button';
	export let variant: 'quiet' | 'primary' = 'quiet';
	export let disabled = false;
	export let pressed: boolean | undefined = undefined;
	export let className = '';
	export let tooltipAlign: 'start' | 'center' | 'end' = 'center';
	export let onClick: () => void = () => {};
</script>

<span
	class="icon-control"
	class:tooltip-start={tooltipAlign === 'start'}
	class:tooltip-end={tooltipAlign === 'end'}
>
	<button
		{type}
		{disabled}
		class="icon-button {className}"
		class:primary={variant === 'primary'}
		aria-label={label}
		aria-pressed={pressed}
		on:click={onClick}
	>
		<span aria-hidden="true"><slot /></span>
	</button>
	<span class="icon-tooltip" aria-hidden="true">{label}</span>
</span>

<style>
	.icon-control {
		position: relative;
		display: inline-flex;
		width: 36px;
		height: 36px;
		flex: 0 0 36px;
	}
	.icon-button {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border: 1px solid transparent;
		border-radius: 50%;
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
		line-height: 1;
		font-size: 22px;
		transition:
			background-color 140ms ease,
			color 140ms ease,
			border-color 140ms ease;
	}
	.icon-button:hover:not(:disabled) {
		background: var(--bg-subtle);
		color: var(--text-primary);
	}
	.icon-button.primary {
		border-color: var(--brand-primary);
		background: var(--brand-primary);
		color: #fff;
	}
	.icon-button[aria-pressed='true'] {
		background: var(--bg-subtle);
		color: var(--text-primary);
	}
	.icon-button.primary:hover:not(:disabled) {
		border-color: var(--brand-primary-hover);
		background: var(--brand-primary-hover);
		color: #fff;
	}
	.icon-button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
	.icon-button.primary:disabled {
		border-color: var(--border-default);
		background: var(--bg-subtle);
		color: var(--text-tertiary);
	}
	.icon-button:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 3px;
	}
	.icon-tooltip {
		position: absolute;
		bottom: calc(100% + 8px);
		left: 50%;
		z-index: 10;
		transform: translateX(-50%);
		width: max-content;
		max-width: 160px;
		padding: 6px 8px;
		border: 1px solid var(--border-default);
		border-radius: 4px;
		background: var(--surface-card);
		color: var(--text-primary);
		box-shadow: var(--shadow-xs);
		font-size: 12px;
		line-height: 18px;
		text-align: center;
		pointer-events: none;
		visibility: hidden;
		opacity: 0;
		transition: opacity 140ms ease;
	}
	.icon-control:focus-within .icon-tooltip {
		visibility: visible;
		opacity: 1;
	}
	.tooltip-start .icon-tooltip {
		left: 0;
		transform: none;
	}
	.tooltip-end .icon-tooltip {
		left: auto;
		right: 0;
		transform: none;
	}
	@media (hover: hover) {
		.icon-control:hover .icon-tooltip {
			visibility: visible;
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.icon-button,
		.icon-tooltip {
			transition: none;
		}
	}
</style>
