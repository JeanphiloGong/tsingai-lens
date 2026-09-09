<script lang="ts">
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import { Sparkles, RotateCcw } from '@lucide/svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { getApiErrorCode } from '../../../_shared/api';
	import { language, t } from '../../../_shared/i18n';
	import {
		generateFindingSummary,
		type FindingEvidenceSummary
	} from '../../../_shared/researchView';

	export let collectionId: string;
	export let objectiveId: string;
	export let findingId: string;
	export let analysisVersion: number;
	export let returnTo = '';
	let summary: FindingEvidenceSummary | null = null;
	let loading = false;
	let open = false;
	let errorCode = '';
	let loadedKey = '';
	let controller: AbortController | null = null;
	let sequence = 0;
	$: key = `${collectionId}:${objectiveId}:${analysisVersion}:${findingId}:${$language}`;
	$: if (key !== loadedKey) {
		loadedKey = key;
		controller?.abort();
		sequence += 1;
		summary = null;
		loading = false;
		open = false;
		errorCode = '';
	}
	onDestroy(() => {
		sequence += 1;
		controller?.abort();
	});

	async function generate() {
		if (loading) return;
		const request = ++sequence;
		const requestKey = key;
		controller = new AbortController();
		loading = true;
		errorCode = '';
		try {
			const result = await generateFindingSummary(
				collectionId,
				objectiveId,
				findingId,
				analysisVersion,
				$language,
				controller.signal
			);
			if (request !== sequence || requestKey !== key) return;
			if (
				result.collection_id !== collectionId ||
				result.objective_id !== objectiveId ||
				result.finding_id !== findingId ||
				result.analysis_version !== analysisVersion ||
				result.language !== $language
			)
				throw new Error('summary identity mismatch');
			summary = result;
		} catch (error) {
			if (request === sequence && requestKey === key) {
				const code = getApiErrorCode(error);
				errorCode =
					code &&
					[
						'summary_input_too_large',
						'summary_stale_analysis',
						'summary_no_evidence',
						'summary_evidence_incomplete'
					].includes(code)
						? code
						: 'summary_generation_failed';
			}
		} finally {
			if (request === sequence && requestKey === key) loading = false;
		}
	}

	function citationHref(reference: FindingEvidenceSummary['references'][number]) {
		const findingHref = `${resolve('/collections/[id]/objectives/[objective_id]', { id: collectionId, objective_id: objectiveId })}?${new SvelteURLSearchParams({ finding_id: findingId })}`;
		if (reference.kind === 'finding') return findingHref;
		const params = new SvelteURLSearchParams({
			view: 'parsed-paper',
			source_ref: reference.source_ref ?? '',
			quote: reference.source_excerpt ?? '',
			return_to: returnTo || findingHref
		});
		if (reference.page_numbers?.length) params.set('page', String(reference.page_numbers[0]));
		return `${resolve('/collections/[id]/documents/[document_id]', { id: collectionId, document_id: reference.document_id ?? '' })}?${params}`;
	}
</script>

<details
	class="finding-summary"
	bind:open
	on:toggle={() => {
		if (open && !summary && !loading && !errorCode) void generate();
	}}
>
	<summary
		><Sparkles size={15} aria-hidden="true" /><span>{$t('research.findingSummary.title')}</span
		></summary
	>
	<div class="summary-body" aria-busy={loading}>
		{#if loading}<p role="status">{$t('research.findingSummary.generating')}</p>{/if}
		{#if errorCode}
			<div class="summary-actions">
				<p role="alert" class="summary-error">{$t(`research.findingSummary.${errorCode}`)}</p>
				<button
					type="button"
					class="btn btn--ghost btn--small"
					disabled={loading}
					on:click={generate}
				>
					<RotateCcw size={14} aria-hidden="true" />{$t('research.findingSummary.retry')}
				</button>
			</div>
		{/if}
		{#if summary}
			<p class="summary-text">
				{summary.text}
				{#each summary.references as reference, index}
					<a href={citationHref(reference)} title={reference.label}>[{index + 1}]</a>
				{/each}
			</p>
			<div class="summary-actions">
				<span class="summary-model"
					>{$t('research.findingSummary.model', { model: summary.model })}</span
				>
				<button
					type="button"
					class="btn btn--ghost btn--small summary-refresh"
					disabled={loading}
					on:click={generate}
					title={$t('research.findingSummary.regenerate')}
					aria-label={$t('research.findingSummary.regenerate')}
				>
					<RotateCcw size={14} aria-hidden="true" />
				</button>
			</div>
		{/if}
	</div>
</details>

<style>
	.finding-summary {
		border-block: 1px solid var(--border-default);
	}
	summary {
		padding: 12px 0;
		color: var(--text-secondary);
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}
	summary :global(svg) {
		display: inline;
		vertical-align: -3px;
		margin-right: 6px;
	}
	.summary-body {
		display: grid;
		gap: 12px;
		padding: 0 0 16px;
	}
	.summary-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 8px;
	}
	button {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 32px;
	}
	.summary-refresh {
		width: 32px;
		height: 32px;
		padding: 0;
		justify-content: center;
	}
	p {
		margin: 0;
		font-size: 13px;
		line-height: 1.6;
		overflow-wrap: anywhere;
	}
	a {
		margin-left: 5px;
		color: var(--brand-primary);
		text-decoration: underline;
	}
	.summary-model {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.summary-error {
		color: var(--warning-text);
	}
</style>
