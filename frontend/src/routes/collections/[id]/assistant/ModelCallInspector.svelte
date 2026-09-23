<script lang="ts">
	import { X, RefreshCw } from '@lucide/svelte';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { t } from '../../../_shared/i18n';
	import type { ChatModelCall } from '../../../_shared/chatSessions';

	export let call: ChatModelCall | null = null;
	export let loading = false;
	export let error = '';
	export let onRetry: () => void = () => {};
	export let onClose: () => void = () => {};

	$: requestText = call ? JSON.stringify(call.request, null, 2) : '';
	$: statusLabel = call
		? call.status === 'provider_succeeded'
			? $t('researchAgent.modelCall.providerSucceeded')
			: call.status === 'provider_failed'
				? $t('researchAgent.modelCall.providerFailed')
				: call.status === 'response_invalid'
					? $t('researchAgent.modelCall.responseInvalid')
					: call.status === 'cancelled'
						? $t('researchAgent.modelCall.cancelled')
						: $t('researchAgent.modelCall.recorded')
		: '';
</script>

{#if call || loading || error}
	<section class="model-call-inspector" aria-label={$t('researchAgent.modelCall.title')}>
		<header>
			<div>
				<p class="eyebrow">{$t('researchAgent.modelCall.eyebrow')}</p>
				<h3>{$t('researchAgent.modelCall.title')}</h3>
			</div>
			<IconButton label={$t('researchAgent.modelCall.close')} onClick={onClose}>
				<X size={16} />
			</IconButton>
		</header>
		{#if loading}
			<p class="state" role="status">{$t('researchAgent.modelCall.loading')}</p>
		{:else if error}
			<div class="state error" role="alert">
				<span>{error}</span>
				<IconButton label={$t('researchAgent.modelCall.retry')} onClick={onRetry}>
					<RefreshCw size={15} />
				</IconButton>
			</div>
		{:else if call}
			<div class="meta">
				<span>{statusLabel}</span>
				<span>{call.purpose}</span>
				<span>{call.model}</span>
			</div>
			<p class="digest">{call.request_digest}</p>
			<pre>{requestText}</pre>
		{/if}
	</section>
{/if}

<style>
	.model-call-inspector {
		position: fixed;
		inset: auto 20px 20px auto;
		z-index: 20;
		width: min(720px, calc(100vw - 40px));
		max-height: min(76vh, 760px);
		overflow: auto;
		padding: 16px;
		background: var(--surface-card);
		border: 1px solid var(--brand-border);
		box-shadow: 0 12px 36px rgb(15 23 42 / 18%);
	}
	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}
	.eyebrow {
		margin: 0 0 3px;
		color: var(--text-tertiary);
		font-size: 11px;
		text-transform: uppercase;
	}
	h3 {
		margin: 0;
		font-size: 16px;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 14px;
		color: var(--text-secondary);
		font-size: 12px;
	}
	.meta span {
		padding: 3px 7px;
		border: 1px solid var(--brand-border);
		border-radius: 4px;
	}
	.digest {
		margin: 10px 0;
		color: var(--text-tertiary);
		font:
			11px ui-monospace,
			SFMono-Regular,
			Menlo,
			monospace;
		word-break: break-all;
	}
	pre {
		margin: 0;
		padding: 12px;
		overflow: auto;
		background: var(--surface-muted, #f8fafc);
		font:
			11px/1.5 ui-monospace,
			SFMono-Regular,
			Menlo,
			monospace;
		white-space: pre-wrap;
		word-break: break-word;
	}
	.state {
		margin: 18px 0 0;
		color: var(--text-secondary);
	}
	.state.error {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		color: var(--status-danger, #b42318);
	}
	@media (max-width: 640px) {
		.model-call-inspector {
			inset: auto 10px 10px;
			width: auto;
		}
	}
</style>
