<script lang="ts">
	import { t } from '../../../../../_shared/i18n';
	import type { WorkbenchQaSuggestion } from '../../../../../_shared/documents';

	export let suggestions: WorkbenchQaSuggestion[] = [];
	let question = '';
</script>

<section class="qa-panel" aria-labelledby="qa-panel-title">
	<div class="qa-card">
		<h3 id="qa-panel-title">{$t('workbench.quickQa')}</h3>
		<p>{$t('workbench.qaPlaceholderBody')}</p>
		<div class="suggestion-chips">
			{#each suggestions as suggestion}
				<button type="button" on:click={() => (question = suggestion.text)}>
					{suggestion.text}
				</button>
			{/each}
		</div>
		<div class="qa-input">
			<input bind:value={question} placeholder={$t('workbench.qaInputPlaceholder')} />
			<button type="button">{$t('workbench.send')}</button>
		</div>
	</div>
</section>

<style>
	.qa-panel {
		margin-top: 12px;
		padding-top: 12px;
		border-top: 1px solid #e2e8f0;
	}

	.qa-card {
		padding: 16px;
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		background: #ffffff;
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
	}

	h3 {
		margin: 0 0 8px;
		color: #0f172a;
		font-size: 15px;
		font-weight: 700;
		line-height: 22px;
	}

	p {
		margin: 0 0 12px;
		color: #334155;
		font-size: 14px;
		line-height: 22px;
	}

	.suggestion-chips {
		display: flex;
		margin-bottom: 12px;
		flex-wrap: wrap;
		gap: 8px;
	}

	.suggestion-chips button {
		height: 26px;
		padding: 0 10px;
		border: 0;
		border-radius: 999px;
		background: #eff6ff;
		color: #334155;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
	}

	.qa-input {
		display: flex;
		height: 44px;
		align-items: center;
		gap: 8px;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
		padding: 0 8px 0 12px;
	}

	input {
		min-width: 0;
		flex: 1;
		border: 0;
		outline: 0;
		background: transparent;
		color: #0f172a;
		font-size: 14px;
	}

	.qa-input button {
		height: 32px;
		padding: 0 12px;
		border: 0;
		border-radius: 10px;
		background: #2563eb;
		color: #ffffff;
		font-size: 14px;
		font-weight: 700;
		cursor: pointer;
	}
</style>
