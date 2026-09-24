<script lang="ts">
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { ArrowLeft, Download, Eye, RefreshCw, Save, TriangleAlert } from '@lucide/svelte';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import { fetchFeedbackCases, fetchFeedbackCase, type FeedbackCaseDetail, type FeedbackCaseSummary } from '../../../../_shared/feedbackCases';
	import {
		createDatasetSnapshot,
		downloadDatasetSnapshot,
		fetchDatasetSnapshots,
		fetchDatasetSnapshot,
		type DatasetSnapshot,
		type DatasetSnapshotSummary,
		type DatasetSplit,
		type DatasetType
	} from '../../../../_shared/datasetSnapshots';

	let acceptedCases: FeedbackCaseSummary[] = [];
	let selectedIds: string[] = [];
	let splitByCase: Record<string, DatasetSplit> = {};
	let details: Record<string, FeedbackCaseDetail> = {};
	let familyByDocument: Record<string, string> = {};
	let documentTitles: Record<string, string> = {};
	let snapshots: DatasetSnapshotSummary[] = [];
	let snapshotDetails: Record<string, DatasetSnapshot> = {};
	let datasetType: DatasetType = 'evaluation';
	let loading = true;
	let saving = false;
	let downloading = '';
	let error = '';
	let notice = '';
	let detailLoading = '';
	let expandedSnapshot = '';

	$: collectionId = $page.params.id ?? '';
	$: selectedCases = acceptedCases.filter((item) => selectedIds.includes(item.case_id));
	$: selectedDocuments = Object.keys(documentTitles).filter((id) =>
		selectedCases.some((item) => details[item.case_id] && caseDocumentIds(details[item.case_id]).includes(id))
	);

	onMount(() => {
		void load();
	});

	async function load() {
		if (!collectionId) return;
		loading = true;
		error = '';
		try {
			const [cases, existing] = await Promise.all([
				fetchFeedbackCases(collectionId, { status: 'accepted', limit: 200 }),
				fetchDatasetSnapshots(collectionId)
			]);
			acceptedCases = cases.items;
			snapshots = existing.items;
			for (const item of acceptedCases) {
				if (!splitByCase[item.case_id]) splitByCase[item.case_id] = 'eval';
			}
			await loadSelectedDetails();
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function loadSelectedDetails() {
		for (const caseId of selectedIds) {
			if (details[caseId]) continue;
			try {
				const detail = await fetchFeedbackCase(collectionId, caseId);
				details = { ...details, [caseId]: detail };
				for (const id of caseDocumentIds(detail)) {
					const item = [...detail.requested_scope, ...detail.inspected_sources, ...detail.omitted_candidates].find(
						(source) => String(source.document_id ?? '') === id
					);
					const title = String(item?.document_title ?? item?.title ?? '').trim();
					documentTitles = {
						...documentTitles,
						[id]: title || $t('datasetSnapshots.selectedPaper')
					};
					if (!familyByDocument[id] && title) familyByDocument[id] = title;
				}
			} catch (err) {
				error = errorMessage(err);
			}
		}
	}

	function caseDocumentIds(detail: FeedbackCaseDetail) {
		return [...detail.requested_scope, ...detail.inspected_sources, ...detail.omitted_candidates, ...detail.claim_support]
			.map((source) => String(source.document_id ?? ''))
			.filter((id, index, values) => id && values.indexOf(id) === index);
	}

	function documentLabel(documentId: string) {
		return documentTitles[documentId] || $t('datasetSnapshots.selectedPaper');
	}

	function caseLabel(caseId: string) {
		const item = acceptedCases.find((candidate) => candidate.case_id === caseId);
		if (!item) return $t('datasetSnapshots.selectedCase');
		return item.question_preview || item.answer_preview || item.document_titles.join(' · ') || $t('datasetSnapshots.selectedCase');
	}

	function exclusionReason(exclusion: Record<string, unknown>) {
		const reason = String(exclusion.reason ?? '').trim().split(':', 1)[0];
		const key =
			{
				duplicate_selection: 'reasonDuplicate',
				split_invalid: 'reasonSplitInvalid',
				case_not_in_collection: 'reasonCaseNotInCollection',
				case_not_accessible: 'reasonCaseNotAccessible',
				annotation_stale: 'reasonAnnotationStale',
				review_not_accepted: 'reasonReviewNotAccepted',
				dataset_use_not_authorized: 'reasonDatasetUseNotAuthorized',
				anchor_answer_missing: 'reasonAnswerMissing',
				input_missing: 'reasonInputMissing',
				answer_missing: 'reasonAnswerMissing',
				paper_family_missing: 'reasonPaperFamilyMissing',
				source_not_in_case: 'reasonSourceNotInCase',
				target_missing: 'reasonTargetMissing',
				support_source_missing: 'reasonSupportSourceMissing',
				preference_pair_missing: 'reasonPreferencePairMissing'
			}[reason] ?? '';
		return key ? $t(`datasetSnapshots.${key}`) : $t('datasetSnapshots.reasonOther');
	}

	async function toggleCase(caseId: string) {
		selectedIds = selectedIds.includes(caseId)
			? selectedIds.filter((id) => id !== caseId)
			: [...selectedIds, caseId];
		await loadSelectedDetails();
	}

	async function saveSnapshot() {
		if (saving || !selectedIds.length) return;
		saving = true;
		error = '';
		notice = '';
		try {
			const snapshot = await createDatasetSnapshot(
				collectionId,
				datasetType,
				selectedIds.map((caseId) => ({ case_id: caseId, split: splitByCase[caseId] ?? 'eval' })),
				Object.fromEntries(selectedDocuments.map((id) => [id, familyByDocument[id] || '']))
			);
			notice = $t('datasetSnapshots.created', { count: snapshot.row_count });
			snapshots = [snapshot, ...snapshots.filter((item) => item.dataset_id !== snapshot.dataset_id)];
		} catch (err) {
			error = errorMessage(err);
		} finally {
			saving = false;
		}
	}

	async function download(snapshot: DatasetSnapshotSummary) {
		if (downloading) return;
		downloading = snapshot.dataset_id;
		error = '';
		try {
			await downloadDatasetSnapshot(snapshot.dataset_id);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			downloading = '';
		}
	}

	async function toggleSnapshot(snapshot: DatasetSnapshotSummary) {
		if (expandedSnapshot === snapshot.dataset_id) {
			expandedSnapshot = '';
			return;
		}
		expandedSnapshot = snapshot.dataset_id;
		if (snapshotDetails[snapshot.dataset_id]) return;
		detailLoading = snapshot.dataset_id;
		try {
			const detail = await fetchDatasetSnapshot(snapshot.dataset_id);
			snapshotDetails = { ...snapshotDetails, [snapshot.dataset_id]: detail };
		} catch (err) {
			error = errorMessage(err);
		} finally {
			detailLoading = '';
		}
	}

	function datasetLabel(value: DatasetType) {
		return $t(`datasetSnapshots.type.${value}`);
	}

	function formatDate(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}
</script>

<svelte:head>
	<title>{$t('datasetSnapshots.title')} | Lens</title>
</svelte:head>

<section class="datasets" aria-labelledby="datasets-title">
	<header class="page-header">
		<div>
			<a class="back-link" href={`/collections/${collectionId}/feedback`}><ArrowLeft size={15} />{$t('datasetSnapshots.back')}</a>
			<p class="eyebrow">{$t('datasetSnapshots.eyebrow')}</p>
			<h1 id="datasets-title">{$t('datasetSnapshots.title')}</h1>
			<p class="lede">{$t('datasetSnapshots.lede')}</p>
		</div>
		<button class="icon-button" type="button" title={$t('datasetSnapshots.refresh')} aria-label={$t('datasetSnapshots.refresh')} on:click={load} disabled={loading}>
			<span class:spin={loading}><RefreshCw size={17} /></span>
		</button>
	</header>

	{#if error}<div class="notice notice--error" role="alert"><TriangleAlert size={17} /><span>{error}</span></div>{/if}
	{#if notice}<div class="notice notice--success" role="status"><Save size={17} /><span>{notice}</span></div>{/if}

	<div class="builder-grid">
		<section class="builder-panel" aria-labelledby="builder-title">
			<div class="section-heading"><div><p class="eyebrow">{$t('datasetSnapshots.step')}</p><h2 id="builder-title">{$t('datasetSnapshots.chooseCases')}</h2></div><span class="count-badge">{selectedIds.length}</span></div>
			<label class="field-label" for="dataset-type">{$t('datasetSnapshots.datasetType')}</label>
			<select id="dataset-type" bind:value={datasetType}>
				<option value="evaluation">{datasetLabel('evaluation')}</option>
				<option value="sft">{datasetLabel('sft')}</option>
				<option value="preference">{datasetLabel('preference')}</option>
			</select>
			<p class="field-hint">{$t(`datasetSnapshots.typeHelp.${datasetType}`)}</p>

			{#if loading}
				<p class="muted">{$t('datasetSnapshots.loading')}</p>
			{:else if !acceptedCases.length}
				<div class="empty-state"><strong>{$t('datasetSnapshots.noAccepted')}</strong><span>{$t('datasetSnapshots.noAcceptedDetail')}</span></div>
			{:else}
				<div class="case-options">
					{#each acceptedCases as item (item.case_id)}
						<div class="case-option">
							<input id={`case-${item.case_id}`} type="checkbox" checked={selectedIds.includes(item.case_id)} on:change={() => toggleCase(item.case_id)} />
							<label class="case-copy" for={`case-${item.case_id}`}><strong>{item.question_preview || $t('datasetSnapshots.untitledCase')}</strong><small>{item.document_titles.join(' · ') || $t('datasetSnapshots.noDocuments')}</small></label>
						<select aria-label={$t('datasetSnapshots.splitFor', { case: caseLabel(item.case_id) })} value={splitByCase[item.case_id] ?? 'eval'} on:change={(event) => (splitByCase[item.case_id] = (event.currentTarget as HTMLSelectElement).value as DatasetSplit)}>
								<option value="eval">eval</option><option value="train">train</option>
							</select>
						</div>
					{/each}
				</div>
			{/if}

			{#if selectedDocuments.length}
				<div class="families">
					<div class="section-heading"><div><h3>{$t('datasetSnapshots.paperFamilies')}</h3><span>{$t('datasetSnapshots.paperFamiliesHint')}</span></div></div>
					{#each selectedDocuments as documentId}
						<label class="family-row"><span>{documentLabel(documentId)}</span><input bind:value={familyByDocument[documentId]} aria-label={$t('datasetSnapshots.familyFor', { document: documentLabel(documentId) })} /></label>
					{/each}
				</div>
			{/if}

			<button class="primary-button" type="button" on:click={saveSnapshot} disabled={saving || !selectedIds.length}>
				<Save size={16} />{saving ? $t('datasetSnapshots.saving') : $t('datasetSnapshots.freeze')}
			</button>
			<p class="privacy-note">{$t('datasetSnapshots.freezeNote')}</p>
		</section>

		<section class="history-panel" aria-labelledby="history-title">
			<div class="section-heading"><div><p class="eyebrow">{$t('datasetSnapshots.historyEyebrow')}</p><h2 id="history-title">{$t('datasetSnapshots.history')}</h2></div><span class="count-badge">{snapshots.length}</span></div>
			{#if !snapshots.length}<div class="empty-state"><strong>{$t('datasetSnapshots.noSnapshots')}</strong><span>{$t('datasetSnapshots.noSnapshotsDetail')}</span></div>{/if}
			<div class="snapshot-list">
				{#each snapshots as snapshot (snapshot.dataset_id)}
					<article class="snapshot-row">
						<div class="snapshot-main"><div class="snapshot-title"><strong>{datasetLabel(snapshot.dataset_type)}</strong><span class="status-chip">{snapshot.row_count} {$t('datasetSnapshots.rows')}</span>{#if snapshot.is_empty}<span class="empty-chip">{$t('datasetSnapshots.empty')}</span>{/if}</div><small>{formatDate(snapshot.created_at)}</small><span class="snapshot-note">{$t('datasetSnapshots.immutable')}</span></div>
						<div class="snapshot-meta"><span>{$t('datasetSnapshots.excluded')}: {snapshot.excluded_count}</span><div class="snapshot-actions"><button class="detail-button" type="button" aria-expanded={expandedSnapshot === snapshot.dataset_id} on:click={() => toggleSnapshot(snapshot)}><Eye size={15} />{expandedSnapshot === snapshot.dataset_id ? $t('datasetSnapshots.hideDetails') : $t('datasetSnapshots.viewDetails')}</button><button class="download-button" type="button" on:click={() => download(snapshot)} disabled={downloading === snapshot.dataset_id}><Download size={15} />{downloading === snapshot.dataset_id ? $t('datasetSnapshots.downloading') : $t('datasetSnapshots.download')}</button></div></div>
						{#if expandedSnapshot === snapshot.dataset_id}
							{@const detail = snapshotDetails[snapshot.dataset_id]}
							<div class="exclusion-details" aria-live="polite">
								{#if detailLoading === snapshot.dataset_id}
									<span class="muted">{$t('datasetSnapshots.loadingDetails')}</span>
								{:else if detail && detail.exclusions.length}
									<strong>{$t('datasetSnapshots.exclusionReasons')}</strong>
									{#each detail.exclusions as exclusion}
										<div class="exclusion-row"><span>{caseLabel(String(exclusion.case_id ?? ''))}</span><span>{exclusionReason(exclusion)}</span></div>
									{/each}
								{:else if detail}
									<span class="muted">{$t('datasetSnapshots.noExclusions')}</span>
								{/if}
							</div>
						{/if}
					</article>
				{/each}
			</div>
		</section>
	</div>
</section>

<style>
	.datasets { max-width: 1240px; margin: 0 auto; padding: 30px 28px 56px; color: var(--text-primary); }
	.page-header, .section-heading, .snapshot-title, .snapshot-meta, .back-link { display: flex; align-items: center; }
	.page-header, .section-heading { justify-content: space-between; gap: 18px; }
	.page-header { margin-bottom: 24px; align-items: flex-start; }
	.back-link { width: fit-content; gap: 6px; color: var(--text-secondary); text-decoration: none; font-size: 13px; margin-bottom: 12px; }
	.back-link:hover { color: var(--text-primary); }
	.eyebrow { margin: 0 0 7px; color: var(--accent-primary); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
	h1, h2, h3, p { margin-top: 0; }
	h1 { margin-bottom: 8px; font-size: 34px; line-height: 1.1; }
	h2 { margin-bottom: 0; font-size: 20px; }
	h3 { margin-bottom: 3px; font-size: 15px; }
	.lede { max-width: 680px; margin-bottom: 0; color: var(--text-secondary); line-height: 1.6; }
	.icon-button, .download-button, .primary-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid var(--border-subtle); border-radius: 6px; cursor: pointer; }
	.icon-button { width: 36px; height: 36px; background: var(--surface-raised); color: var(--text-secondary); }
	.primary-button { min-height: 40px; padding: 0 15px; background: var(--accent-primary); color: white; font-weight: 700; }
	.download-button, .detail-button { padding: 7px 10px; background: var(--surface-raised); color: var(--text-primary); font-size: 12px; }
	.detail-button { border: 1px solid var(--border-subtle); border-radius: 6px; cursor: pointer; }
	button:disabled { opacity: .55; cursor: not-allowed; }
	.primary-button:disabled { opacity: 1; background: var(--surface-sunken); color: var(--text-secondary); border-color: var(--border-subtle); }
	.notice { display: flex; align-items: center; gap: 9px; margin: 0 0 18px; padding: 11px 13px; border-radius: 6px; font-size: 13px; }
	.notice--error { border: 1px solid color-mix(in srgb, #d35d5d 35%, transparent); background: color-mix(in srgb, #d35d5d 9%, transparent); color: #a33434; }
	.notice--success { border: 1px solid color-mix(in srgb, #2b9a72 35%, transparent); background: color-mix(in srgb, #2b9a72 9%, transparent); color: #19704f; }
	.builder-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(340px, .85fr); gap: 20px; align-items: start; }
	.builder-panel, .history-panel { border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--surface-raised); padding: 20px; }
	.section-heading { margin-bottom: 18px; }
	.section-heading span { color: var(--text-secondary); font-size: 12px; }
	.count-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 26px; height: 24px; padding: 0 7px; border-radius: 12px; background: var(--surface-sunken); color: var(--text-secondary); font-size: 12px; }
	.field-label { display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 700; }
	select, input { box-sizing: border-box; border: 1px solid var(--border-subtle); border-radius: 5px; background: var(--surface-base); color: var(--text-primary); }
	select { min-height: 36px; padding: 0 9px; }
	#dataset-type { width: 100%; }
	.field-hint, .privacy-note { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
	.field-hint { margin: 7px 0 18px; }
	.case-options { display: grid; gap: 8px; max-height: 430px; overflow: auto; margin-bottom: 18px; }
	.case-option { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 11px 10px; border: 1px solid var(--border-subtle); border-radius: 6px; background: var(--surface-base); cursor: pointer; }
	.case-option:hover { border-color: var(--accent-primary); }
	.case-option input { accent-color: var(--accent-primary); }
	.case-copy { min-width: 0; display: grid; gap: 3px; cursor: pointer; }
	.case-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
	.case-copy small, .snapshot-main small, .snapshot-note { color: var(--text-secondary); font-size: 11px; }
	.case-option select { min-height: 30px; font-size: 12px; }
	.families { margin: 8px 0 18px; padding-top: 16px; border-top: 1px solid var(--border-subtle); }
	.family-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(120px, .65fr); gap: 10px; align-items: center; margin-top: 9px; font-size: 12px; }
	.family-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
	.family-row input { width: 100%; min-height: 32px; padding: 0 8px; }
	.privacy-note { margin: 10px 0 0; }
	.empty-state { display: grid; gap: 5px; padding: 30px 10px; color: var(--text-secondary); text-align: center; }
	.empty-state strong { color: var(--text-primary); }
	.snapshot-list { display: grid; gap: 9px; }
	.snapshot-row { display: grid; gap: 12px; padding: 13px 0; border-bottom: 1px solid var(--border-subtle); }
	.snapshot-row:last-child { border-bottom: 0; }
	.snapshot-title { gap: 8px; }
	.status-chip, .empty-chip { padding: 3px 6px; border-radius: 4px; background: var(--surface-sunken); color: var(--text-secondary); font-size: 10px; }
	.empty-chip { color: #9a6b1e; background: #fff5df; }
	.snapshot-main { display: grid; gap: 5px; min-width: 0; }
	.snapshot-meta { justify-content: space-between; gap: 8px; color: var(--text-secondary); font-size: 11px; }
	.snapshot-actions { display: flex; align-items: center; gap: 7px; }
	.exclusion-details { display: grid; gap: 7px; padding: 11px; border: 1px solid var(--border-subtle); border-radius: 6px; background: var(--surface-base); font-size: 11px; }
	.exclusion-row { display: grid; grid-template-columns: minmax(90px, .35fr) minmax(0, 1fr); gap: 10px; color: var(--text-secondary); }
	.exclusion-row span { min-width: 0; overflow-wrap: anywhere; }
	button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible { outline: 3px solid color-mix(in srgb, var(--accent-primary) 35%, transparent); outline-offset: 2px; }
	.spin { display: inline-flex; animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 860px) { .datasets { padding: 22px 16px 40px; } .builder-grid { grid-template-columns: 1fr; } }
	@media (max-width: 520px) { .page-header { gap: 10px; } h1 { font-size: 28px; } .builder-panel, .history-panel { padding: 15px; } .case-option { grid-template-columns: 18px minmax(0, 1fr); } .case-option select { grid-column: 2; width: fit-content; } .snapshot-meta { align-items: flex-start; flex-direction: column; } .snapshot-actions { flex-wrap: wrap; } }
</style>
