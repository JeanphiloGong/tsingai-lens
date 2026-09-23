<script lang="ts">
	import { onMount } from 'svelte';
	import { Archive, CircleAlert, Download, LoaderCircle, X } from '@lucide/svelte';
	import { errorMessage } from '../../../_shared/api';
	import {
		createChatCorrectionDataset,
		downloadChatCorrectionDataset,
		fetchChatCorrectionDatasets,
		fetchChatCorrectionSamples,
		fetchChatCorrectionReviewStatus,
		type ChatCorrectionDataset,
		type ChatCorrectionDatasetSplit,
		type ChatCorrectionSample,
		type ChatCorrectionReviewStatus
	} from '../../../_shared/chatSessions';
	import { t } from '../../../_shared/i18n';

	export let collectionId = '';
	export let sessionId = '';
	export let onClose: () => void = () => {};

	let samples: ChatCorrectionSample[] = [];
	let statuses: Record<string, ChatCorrectionReviewStatus> = {};
	let datasets: ChatCorrectionDataset[] = [];
	let selected: Record<string, boolean> = {};
	let splits: Record<string, ChatCorrectionDatasetSplit> = {};
	let families: Record<string, string> = {};
	let loading = true;
	let submitting = false;
	let downloading = '';
	let error = '';
	let created: ChatCorrectionDataset | null = null;

	function sourceDocumentId(ref: Record<string, unknown>) {
		if (ref.kind === 'message_source' && typeof ref.document_id === 'string') {
			return ref.document_id;
		}
		if (
			ref.kind === 'tool_resource' &&
			ref.resource_type === 'source' &&
			typeof ref.resource_id === 'string'
		) {
			return ref.resource_id.split(':', 1)[0] ?? '';
		}
		return '';
	}

	onMount(() => {
		void load();
	});

	async function load() {
		loading = true;
		error = '';
		try {
			const [sampleResult, datasetResult] = await Promise.all([
				fetchChatCorrectionSamples(sessionId),
				fetchChatCorrectionDatasets(collectionId)
			]);
			samples = sampleResult.items;
			datasets = datasetResult.items;
			const statusEntries = await Promise.all(
				samples.map(async (sample) => [
					sample.sample_id,
					await fetchChatCorrectionReviewStatus(sessionId, sample.sample_id)
				] as const)
			);
			statuses = Object.fromEntries(statusEntries);
			selected = Object.fromEntries(
				samples.map((sample) => [sample.sample_id, statuses[sample.sample_id]?.state === 'accept'])
			);
			splits = Object.fromEntries(samples.map((sample) => [sample.sample_id, 'train']));
			for (const sample of samples) {
				for (const ref of sample.source_refs) {
					const documentId = sourceDocumentId(ref);
					if (!documentId) continue;
					families[documentId] ??= documentId;
				}
			}
		} catch (value) {
			error = errorMessage(value);
		} finally {
			loading = false;
		}
	}

	async function freeze() {
		if (submitting) return;
		submitting = true;
		error = '';
		created = null;
		try {
			created = await createChatCorrectionDataset({
				collection_id: collectionId,
				items: samples
					.filter((sample) => selected[sample.sample_id])
					.map((sample) => ({
						session_id: sessionId,
						sample_id: sample.sample_id,
						split: splits[sample.sample_id] ?? 'train'
					})),
				paper_families: families
			});
			datasets = [created, ...datasets.filter((item) => item.dataset_id !== created?.dataset_id)];
		} catch (value) {
			error = errorMessage(value);
		} finally {
			submitting = false;
		}
	}

	async function download(datasetId: string) {
		if (downloading) return;
		downloading = datasetId;
		error = '';
		try {
			await downloadChatCorrectionDataset(datasetId);
		} catch (value) {
			error = errorMessage(value);
		} finally {
			downloading = '';
		}
	}

	function reasonLabel(reason: string) {
		return $t(`researchAgent.correctionDataset.reason.${reason}`);
	}
</script>

<div class="backdrop" role="presentation" on:click={(event) => event.target === event.currentTarget && onClose()}>
	<div class="panel" role="dialog" aria-modal="true" aria-labelledby="correction-dataset-title" tabindex="-1">
		<header>
			<div>
				<p class="eyebrow">{$t('researchAgent.correctionDataset.eyebrow')}</p>
				<h2 id="correction-dataset-title">{$t('researchAgent.correctionDataset.title')}</h2>
			</div>
			<button class="icon-button" type="button" aria-label={$t('researchAgent.correctionDataset.close')} on:click={onClose}>
				<X size={18} />
			</button>
		</header>

		{#if loading}
			<div class="state" role="status"><LoaderCircle size={16} class="spin" />{$t('researchAgent.correctionDataset.loading')}</div>
		{:else if error && !samples.length && !datasets.length}
			<div class="state error" role="alert"><CircleAlert size={16} />{error}</div>
		{:else}
			<section class="freeze-section">
				<div class="section-heading">
					<div><h3>{$t('researchAgent.correctionDataset.samples')}</h3><p>{$t('researchAgent.correctionDataset.samplesHint')}</p></div>
					<button class="primary" type="button" disabled={submitting} on:click={freeze}>
						{#if submitting}<LoaderCircle size={15} class="spin" />{:else}<Archive size={15} />{/if}
						<span>{$t('researchAgent.correctionDataset.freeze')}</span>
					</button>
				</div>
				{#if samples.length === 0}
					<p class="muted">{$t('researchAgent.correctionDataset.emptySamples')}</p>
				{:else}
					<div class="sample-list">
						{#each samples as sample (sample.sample_id)}
							<label class="sample-row">
								<input type="checkbox" bind:checked={selected[sample.sample_id]} disabled={statuses[sample.sample_id]?.state !== 'accept'} />
								<span class="sample-main"><strong>{sample.sample_id.slice(-12)}</strong><span>{statuses[sample.sample_id]?.state ?? 'pending'}</span></span>
								<select bind:value={splits[sample.sample_id]} disabled={!selected[sample.sample_id]} aria-label={$t('researchAgent.correctionDataset.split')}>
									<option value="train">train</option>
									<option value="eval">eval</option>
								</select>
							</label>
						{/each}
					</div>
				{/if}
			</section>

			<section class="inventory-section">
				<h3>{$t('researchAgent.correctionDataset.inventory')}</h3>
				<p>{$t('researchAgent.correctionDataset.inventoryHint')}</p>
				<div class="inventory-list">
					{#each Object.keys(families).sort() as documentId}
						<label><span>{documentId}</span><input bind:value={families[documentId]} aria-label={documentId} /></label>
					{/each}
				</div>
			</section>

			{#if error}<div class="state error" role="alert"><CircleAlert size={16} />{error}</div>{/if}
			{#if created}<div class="state success" role="status">{$t('researchAgent.correctionDataset.created', { count: created.row_count })}</div>{/if}

			<section class="dataset-section">
				<h3>{$t('researchAgent.correctionDataset.saved')}</h3>
				{#if datasets.length === 0}
					<p class="muted">{$t('researchAgent.correctionDataset.emptyDatasets')}</p>
				{:else}
					<div class="dataset-list">
						{#each datasets as dataset (dataset.dataset_id)}
							<div class="dataset-row">
								<div><strong>{dataset.dataset_id.slice(-16)}</strong><span>{dataset.row_count} / {dataset.excluded_count}</span><code>{dataset.digest.slice(0, 12)}</code></div>
								<button class="icon-button small" type="button" aria-label={$t('researchAgent.correctionDataset.download')} disabled={downloading === dataset.dataset_id} on:click={() => download(dataset.dataset_id)}>
									{#if downloading === dataset.dataset_id}<LoaderCircle size={15} class="spin" />{:else}<Download size={15} />{/if}
								</button>
							</div>
							{#if dataset.exclusions.length}
								<div class="exclusions">
									{#each dataset.exclusions as exclusion (exclusion.sample_id + exclusion.reason)}
										<span>{exclusion.sample_id.slice(-10)} · {reasonLabel(exclusion.reason)}</span>
									{/each}
								</div>
							{/if}
						{/each}
					</div>
				{/if}
			</section>
		{/if}
	</div>
</div>

<style>
	.backdrop { position: fixed; inset: 0; z-index: 58; display: grid; place-items: center; padding: 20px; background: color-mix(in srgb, var(--surface-page) 72%, transparent); }
	.panel { width: min(860px, 100%); max-height: min(860px, 92vh); overflow: auto; padding: 20px; background: var(--surface-card); border: 1px solid var(--border-default); box-shadow: 0 18px 48px rgb(0 0 0 / 18%); }
	header { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
	.eyebrow { margin: 0 0 4px; color: var(--text-tertiary); font-size: 11px; text-transform: uppercase; }
	h2 { margin: 0; font-size: 20px; }
	h3 { margin: 0; font-size: 14px; }
	.icon-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid var(--border-default); background: transparent; color: var(--text-secondary); cursor: pointer; }
	.icon-button.small { width: 30px; height: 30px; }
	.freeze-section, .inventory-section, .dataset-section { padding: 14px 0; border-top: 1px solid var(--border-default); }
	.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
	p { margin: 4px 0 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.45; }
	.primary { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 11px; border: 1px solid var(--brand-primary); background: var(--brand-primary); color: white; cursor: pointer; white-space: nowrap; }
	.primary:disabled { opacity: .55; cursor: wait; }
	.sample-list, .inventory-list, .dataset-list { display: grid; gap: 7px; margin-top: 12px; }
	.sample-row, .dataset-row { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 8px 9px; border: 1px solid var(--border-default); }
	.sample-main { display: flex; align-items: baseline; gap: 8px; min-width: 0; flex: 1; font-size: 12px; }
	.sample-main span, .dataset-row span { color: var(--text-tertiary); }
	.sample-row select, .inventory-list input { min-height: 30px; padding: 4px 7px; border: 1px solid var(--border-default); background: var(--surface-page); color: var(--text-primary); }
	.inventory-list label { display: grid; grid-template-columns: minmax(120px, .4fr) minmax(180px, 1fr); gap: 8px; align-items: center; font-size: 12px; }
	.dataset-row > div { display: flex; align-items: baseline; gap: 10px; min-width: 0; flex: 1; font-size: 12px; }
	.dataset-row code { color: var(--text-tertiary); font-size: 10px; }
	.exclusions { display: grid; gap: 3px; padding: 5px 10px 2px 30px; color: var(--text-tertiary); font-size: 11px; }
	.state { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border: 1px solid var(--border-default); font-size: 13px; }
	.error { color: var(--status-error, #b42318); }
	.success { color: var(--status-success, #18794e); }
	.muted { margin-top: 10px; }
	:global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 680px) { .backdrop { padding: 0; place-items: end center; } .panel { max-height: 94vh; } .section-heading { flex-direction: column; } .primary { width: 100%; justify-content: center; } .inventory-list label { grid-template-columns: 1fr; } }
</style>
