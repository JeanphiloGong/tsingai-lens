<script lang="ts">
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import {
		ArrowLeft,
		ArrowRight,
		Check,
		CheckCircle2,
		Download,
		Eye,
		FileJson,
		ListChecks,
		PackageCheck,
		RefreshCw,
		Save,
		TriangleAlert,
		X
	} from '@lucide/svelte';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchFeedbackCases,
		fetchFeedbackCase,
		type FeedbackCaseDetail,
		type FeedbackCaseSummary
	} from '../../../../_shared/feedbackCases';
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
	let noticeTone: 'success' | 'warning' = 'success';
	let detailLoadingByCase: Record<string, boolean> = {};
	let detailErrorsByCase: Record<string, string> = {};
	let detailLoading = '';
	let expandedSnapshot = '';
	let caseSearch = '';
	let problemFilter = '';
	let releasedSelectionKey = '';

	$: collectionId = $page.params.id ?? '';
	$: selectedCases = acceptedCases.filter((item) => selectedIds.includes(item.case_id));
	$: selectedCount = selectedCases.length;
	$: acceptedCount = acceptedCases.length;
	$: filteredCases = acceptedCases.filter((item) => {
		const query = caseSearch.trim().toLowerCase();
		const searchable = [item.question_preview, item.answer_preview, ...item.document_titles]
			.join(' ')
			.toLowerCase();
		return (
			(!query || searchable.includes(query)) &&
			(!problemFilter || item.problem_type === problemFilter)
		);
	});
	$: splitCounts = {
		train: selectedCases.filter((item) => (splitByCase[item.case_id] ?? 'eval') === 'train').length,
		eval: selectedCases.filter((item) => (splitByCase[item.case_id] ?? 'eval') === 'eval').length
	};
	$: allCasesSelected =
		filteredCases.length > 0 && filteredCases.every((item) => selectedIds.includes(item.case_id));
	$: latestSnapshot = snapshots[0] ?? null;
	$: selectedDocumentIds = Array.from(
		new Set(
			selectedCases.flatMap((item) => {
				const detail = details[item.case_id];
				return detail ? caseDocumentIds(detail) : [];
			})
		)
	);
	$: selectedDocuments = selectedDocumentIds;
	$: selectedDetailLoadingCount = selectedCases.filter(
		(item) => detailLoadingByCase[item.case_id]
	).length;
	$: selectedDetailErrorCount = selectedCases.filter((item) =>
		Boolean(detailErrorsByCase[item.case_id])
	).length;
	$: selectedDetailsReady =
		selectedCount > 0 &&
		selectedCases.every(
			(item) =>
				Boolean(details[item.case_id]) &&
				!detailLoadingByCase[item.case_id] &&
				!detailErrorsByCase[item.case_id]
		);
	$: missingFamilyDocuments = selectedDocuments.filter(
		(documentId) => !String(familyByDocument[documentId] ?? '').trim()
	);
	$: datasetValidationIssues = selectedCases.flatMap((item) => {
		const detail = details[item.case_id];
		if (!detail) return [];
		const annotation = detail.annotation;
		const target = String(annotation?.target ?? '').trim();
		const answer = String(detail.answer ?? '').trim();
		const uses = Array.isArray(annotation?.dataset_uses) ? annotation.dataset_uses.map(String) : [];
		const issues: string[] = [];
		if (!uses.includes(datasetType)) issues.push('dataset_use_not_authorized');
		if (datasetType !== 'evaluation' && !target) issues.push('target_missing');
		if (datasetType === 'preference' && (!target || !answer || target === answer)) {
			issues.push('preference_pair_missing');
		}
		return issues.map((reason) => ({ caseId: item.case_id, reason }));
	});
	$: releaseReady =
		selectedDetailsReady &&
		missingFamilyDocuments.length === 0 &&
		datasetValidationIssues.length === 0;
	$: releaseSelectionKey = JSON.stringify({
		type: datasetType,
		cases: selectedIds
			.slice()
			.sort()
			.map((caseId) => ({ caseId, split: splitByCase[caseId] ?? 'eval' })),
		documents: selectedDocuments
			.slice()
			.sort()
			.map((documentId) => [documentId, familyByDocument[documentId] ?? ''])
	});
	$: datasetFlowStep1 = selectedCount ? 'done' : 'active';
	$: datasetFlowStep2 = !selectedCount || !selectedDetailsReady ? 'pending' : releaseReady ? 'done' : 'active';
	$: datasetFlowStep3 = !selectedCount || !selectedDetailsReady || !releaseReady
		? 'pending'
		: releasedSelectionKey === releaseSelectionKey
			? 'done'
			: 'active';

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
			selectedIds = selectedIds.filter((caseId) =>
				acceptedCases.some((item) => item.case_id === caseId)
			);
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

	async function loadSelectedDetails(forceCaseId = '') {
		const caseIds = selectedIds.filter(
			(caseId) => forceCaseId === caseId || (!details[caseId] && !detailLoadingByCase[caseId])
		);
		await Promise.all(caseIds.map((caseId) => loadCaseDetail(caseId)));
	}

	async function loadCaseDetail(caseId: string) {
		detailLoadingByCase = { ...detailLoadingByCase, [caseId]: true };
		detailErrorsByCase = { ...detailErrorsByCase, [caseId]: '' };
			try {
				const detail = await fetchFeedbackCase(collectionId, caseId);
				details = { ...details, [caseId]: detail };
				for (const id of caseDocumentIds(detail)) {
					const item = [
						...detail.requested_scope,
						...detail.inspected_sources,
					...detail.omitted_candidates,
					...detail.claim_support
					].find((source) => String(source.document_id ?? '') === id);
					const title = String(item?.document_title ?? item?.title ?? '').trim();
					documentTitles = {
						...documentTitles,
						[id]: title || $t('datasetSnapshots.selectedPaper')
					};
				if (!familyByDocument[id] && title) {
					familyByDocument = { ...familyByDocument, [id]: title };
				}
			}
		} catch (err) {
			detailErrorsByCase = { ...detailErrorsByCase, [caseId]: errorMessage(err) };
		} finally {
			detailLoadingByCase = { ...detailLoadingByCase, [caseId]: false };
		}
	}

	function caseDocumentIds(detail: FeedbackCaseDetail) {
		return [
			...detail.requested_scope,
			...detail.inspected_sources,
			...detail.omitted_candidates,
			...detail.claim_support
		]
			.map((source) => String(source.document_id ?? ''))
			.filter((id, index, values) => id && values.indexOf(id) === index);
	}

	function documentLabel(documentId: string) {
		return documentTitles[documentId] || $t('datasetSnapshots.selectedPaper');
	}

	function caseLabel(caseId: string) {
		const item = acceptedCases.find((candidate) => candidate.case_id === caseId);
		if (!item) return $t('datasetSnapshots.selectedCase');
		return (
			item.question_preview ||
			item.answer_preview ||
			item.document_titles.join(' · ') ||
			$t('datasetSnapshots.selectedCase')
		);
	}

	function exclusionReason(exclusion: Record<string, unknown>) {
		const reason = String(exclusion.reason ?? '')
			.trim()
			.split(':', 1)[0];
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
				evidence_content_missing: 'reasonEvidenceContentMissing',
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

	async function retryCaseDetail(caseId: string) {
		if (!selectedIds.includes(caseId)) return;
		await loadCaseDetail(caseId);
	}

	async function selectAllCases() {
		selectedIds = Array.from(
			new Set([...selectedIds, ...filteredCases.map((item) => item.case_id)])
		);
		await loadSelectedDetails();
	}

	function clearSelection() {
		selectedIds = [];
	}

	function setSplit(caseId: string, split: DatasetSplit) {
		splitByCase = { ...splitByCase, [caseId]: split };
	}

	async function saveSnapshot() {
		if (saving || !releaseReady) return;
		saving = true;
		error = '';
		notice = '';
		noticeTone = 'success';
		try {
			const snapshot = await createDatasetSnapshot(
				collectionId,
				datasetType,
				selectedIds.map((caseId) => ({ case_id: caseId, split: splitByCase[caseId] ?? 'eval' })),
				Object.fromEntries(selectedDocuments.map((id) => [id, familyByDocument[id] || '']))
			);
			if (snapshot.excluded_count) {
				noticeTone = 'warning';
				notice = $t('datasetSnapshots.createdWithExclusions', {
					count: snapshot.row_count,
					excluded: snapshot.excluded_count
				});
			} else {
				notice = $t('datasetSnapshots.created', { count: snapshot.row_count });
			}
			snapshots = [
				snapshot,
				...snapshots.filter((item) => item.dataset_id !== snapshot.dataset_id)
			];
			releasedSelectionKey = releaseSelectionKey;
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

	function datasetFlowLabel(state: string) {
		return $t(`datasetSnapshots.flowState${state[0].toUpperCase()}${state.slice(1)}`);
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
		<div class="page-heading">
			<a class="back-link" href={resolve('/collections/[id]/feedback', { id: collectionId })}
				><ArrowLeft size={15} aria-hidden="true" />{$t('datasetSnapshots.back')}</a
			>
			<p class="eyebrow">{$t('datasetSnapshots.eyebrow')}</p>
			<h1 id="datasets-title">{$t('datasetSnapshots.title')}</h1>
			<p class="lede">{$t('datasetSnapshots.lede')}</p>
		</div>
		<div class="page-actions">
			<span class="format-badge"
				><FileJson size={15} aria-hidden="true" />{$t('datasetSnapshots.formatBadge')}</span
			>
			<button
				class="icon-button"
				type="button"
				title={$t('datasetSnapshots.refresh')}
				aria-label={$t('datasetSnapshots.refresh')}
				on:click={load}
				disabled={loading}
			>
				<span class:spin={loading}><RefreshCw size={17} aria-hidden="true" /></span>
			</button>
		</div>
	</header>

	{#if error}<div class="notice notice--error" role="alert">
			<TriangleAlert size={17} aria-hidden="true" /><span>{error}</span>
		</div>{/if}
	{#if notice}<div class="notice notice--{noticeTone}" role="status">
			<CheckCircle2 size={17} aria-hidden="true" /><span>{notice}</span>
		</div>{/if}

	<nav class="flow-bar" aria-label={$t('datasetSnapshots.flowLabel')}>
		<div
			class="flow-step flow-step--{datasetFlowStep1}"
			aria-current={datasetFlowStep1 === 'active' ? 'step' : undefined}
		>
			<span class="flow-number">1</span><span
				><strong>{$t('datasetSnapshots.flowScope')}</strong><small
					>{$t('datasetSnapshots.flowScopeDetail')}</small
					><em>{datasetFlowLabel(datasetFlowStep1)}</em></span
			>
		</div>
		<div class="flow-connector" aria-hidden="true"></div>
		<div
			class="flow-step flow-step--{datasetFlowStep2}"
			aria-current={datasetFlowStep2 === 'active' ? 'step' : undefined}
		>
			<span class="flow-number">2</span><span
				><strong>{$t('datasetSnapshots.flowOutput')}</strong><small
					>{$t('datasetSnapshots.flowOutputDetail')}</small
					><em>{datasetFlowLabel(datasetFlowStep2)}</em></span
			>
		</div>
		<div class="flow-connector" aria-hidden="true"></div>
		<div
			class="flow-step flow-step--{datasetFlowStep3}"
			aria-current={datasetFlowStep3 === 'active' ? 'step' : undefined}
		>
			<span class="flow-number">3</span><span
				><strong>{$t('datasetSnapshots.flowRelease')}</strong><small
					>{$t('datasetSnapshots.flowReleaseDetail')}</small
					><em>{datasetFlowLabel(datasetFlowStep3)}</em></span
			>
		</div>
	</nav>

	<div class="release-layout">
		<section class="builder-panel" aria-labelledby="builder-title">
			<div class="panel-heading">
				<div class="step-mark">01</div>
				<div>
					<p class="eyebrow">{$t('datasetSnapshots.step')}</p>
					<h2 id="builder-title">{$t('datasetSnapshots.chooseCases')}</h2>
				</div>
				<span class="count-badge">{selectedCount}/{acceptedCount}</span>
			</div>

			<div class="cases-section">
				<div class="section-heading">
					<div>
						<h3>{$t('datasetSnapshots.caseListTitle')}</h3>
						<span>{$t('datasetSnapshots.caseListDetail')}</span>
					</div>
					{#if acceptedCount}<span class="ready-chip"
							><CheckCircle2 size={14} aria-hidden="true" />{$t('datasetSnapshots.reviewed')}</span
						>{/if}
				</div>
				{#if loading}
					<div class="loading-state" role="status">
						<span class="loading-bar"></span><span class="loading-bar loading-bar--short"
						></span><span class="loading-bar"></span><span class="sr-only"
							>{$t('datasetSnapshots.loading')}</span
						>
					</div>
				{:else if !acceptedCases.length}
					<div class="empty-state empty-state--action">
						<div class="empty-icon"><ListChecks size={20} aria-hidden="true" /></div>
						<strong>{$t('datasetSnapshots.noAccepted')}</strong>
						<span>{$t('datasetSnapshots.noAcceptedDetail')}</span>
						<a
							class="inline-action"
							href={resolve('/collections/[id]/feedback', { id: collectionId })}
							>{$t('datasetSnapshots.openWorkbench')}<ArrowRight size={14} aria-hidden="true" /></a
						>
					</div>
				{:else}
					<div class="case-filters" aria-label={$t('datasetSnapshots.filterCases')}>
						<label class="search-field">
							<span class="sr-only">{$t('datasetSnapshots.searchCases')}</span>
							<input
								type="search"
								bind:value={caseSearch}
								placeholder={$t('datasetSnapshots.searchCases')}
							/>
						</label>
						<label class="filter-field">
							<span class="sr-only">{$t('datasetSnapshots.filterProblem')}</span>
							<select bind:value={problemFilter} aria-label={$t('datasetSnapshots.filterProblem')}>
								<option value="">{$t('datasetSnapshots.allProblems')}</option>
								<option value="fact_error">{$t('feedbackWorkbench.problemFactError')}</option>
								<option value="source_missing"
									>{$t('feedbackWorkbench.problemSourceMissing')}</option
								>
								<option value="evidence_mismatch"
									>{$t('feedbackWorkbench.problemEvidenceMismatch')}</option
								>
								<option value="retrieval_failure"
									>{$t('feedbackWorkbench.problemRetrievalFailure')}</option
								>
								<option value="tool_failure">{$t('feedbackWorkbench.problemToolFailure')}</option>
								<option value="intent_mismatch"
									>{$t('feedbackWorkbench.problemIntentMismatch')}</option
								>
								<option value="incomplete_answer"
									>{$t('feedbackWorkbench.problemIncomplete')}</option
								>
								<option value="style_or_format">{$t('feedbackWorkbench.problemStyle')}</option>
								<option value="undetermined_dissatisfaction"
									>{$t('feedbackWorkbench.problemUndetermined')}</option
								>
							</select>
						</label>
					</div>
					<div class="selection-toolbar">
						<span
							>{$t('datasetSnapshots.selectedSummary', {
								selected: selectedCount,
								total: acceptedCount
							})}</span
						>
						<div class="toolbar-actions">
							<button
								class="text-button"
								type="button"
								on:click={selectAllCases}
								disabled={allCasesSelected}>{$t('datasetSnapshots.selectAll')}</button
							>
							<button
								class="text-button text-button--quiet"
								type="button"
								on:click={clearSelection}
								disabled={!selectedCount}
								><X size={14} aria-hidden="true" />{$t('datasetSnapshots.clearSelection')}</button
							>
						</div>
					</div>
					{#if !filteredCases.length}
						<div class="filtered-empty">{$t('datasetSnapshots.noMatchingCases')}</div>
					{:else}
					<div class="case-options">
						{#each filteredCases as item (item.case_id)}
							<div class="case-option" class:selected={selectedIds.includes(item.case_id)}>
								<input
									id={`case-${item.case_id}`}
									type="checkbox"
									checked={selectedIds.includes(item.case_id)}
									on:change={() => toggleCase(item.case_id)}
								/>
								<div class="case-copy">
									<label for={`case-${item.case_id}`}
											><strong
												>{item.question_preview || $t('datasetSnapshots.untitledCase')}</strong
										></label
									>
									<small
											>{item.document_titles.join(' · ') ||
												$t('datasetSnapshots.noDocuments')}</small
									>
									<span class="case-status"
										><CheckCircle2 size={12} aria-hidden="true" />{$t(
											'datasetSnapshots.reviewed'
										)}</span
									>
										{#if selectedIds.includes(item.case_id)}
											{#if detailLoadingByCase[item.case_id]}
												<span class="case-detail-state case-detail-state--loading"
													>{$t('datasetSnapshots.detailLoading')}</span
												>
											{:else if detailErrorsByCase[item.case_id]}
												<span class="case-detail-state case-detail-state--error" role="alert">
													{$t('datasetSnapshots.detailFailed')}
													<button
														type="button"
														class="retry-link"
														on:click|stopPropagation={() => retryCaseDetail(item.case_id)}
													>
														<RefreshCw size={12} aria-hidden="true" />{$t(
															'datasetSnapshots.retryDetail'
														)}
													</button>
												</span>
											{:else if details[item.case_id]}
												<span class="case-detail-state case-detail-state--ready"
													><CheckCircle2 size={12} aria-hidden="true" />{$t(
														'datasetSnapshots.detailReady'
													)}</span
												>
											{/if}
										{/if}
								</div>
								<label class="split-field"
									><span>{$t('datasetSnapshots.splitLabel')}</span><select
											aria-label={$t('datasetSnapshots.splitFor', {
												case: caseLabel(item.case_id)
											})}
										value={splitByCase[item.case_id] ?? 'eval'}
										on:change={(event) =>
											setSplit(
												item.case_id,
												(event.currentTarget as HTMLSelectElement).value as DatasetSplit
											)}
											><option value="eval">eval</option><option value="train">train</option
											></select
									></label
								>
							</div>
						{/each}
					</div>
					{/if}
				{/if}
			</div>

			<div class="output-section">
				<div class="section-heading">
					<div>
						<p class="section-kicker">02</p>
						<h3>{$t('datasetSnapshots.datasetType')}</h3>
						<span>{$t('datasetSnapshots.outputDetail')}</span>
					</div>
				</div>
				<fieldset class="type-section">
					<legend class="sr-only">{$t('datasetSnapshots.datasetType')}</legend>
					<div class="type-options">
						{#each ['evaluation', 'sft', 'preference'] as option (option)}
							<label class="type-option" class:active={datasetType === option}>
								<input
									type="radio"
									name="dataset-type"
									value={option}
									checked={datasetType === option}
									on:change={() => (datasetType = option as DatasetType)}
								/>
								<span class="type-option-copy"
									><strong>{datasetLabel(option as DatasetType)}</strong><small
										>{$t(`datasetSnapshots.typeHelp.${option}`)}</small
									></span
								>
								{#if datasetType === option}<Check size={16} aria-hidden="true" />{/if}
							</label>
						{/each}
					</div>
					<p class="format-note">
						<FileJson size={14} aria-hidden="true" /><span
							>{$t('datasetSnapshots.formatDetail')}</span
						>
					</p>
				</fieldset>
			</div>

			{#if selectedDocuments.length}
				<details class="validation-section" open>
					<summary
						><span
							><CheckCircle2 size={15} aria-hidden="true" /><strong
								>{$t('datasetSnapshots.validationTitle')}</strong
							></span
						><small>{$t('datasetSnapshots.validationDetail')}</small></summary
					>
					<div class="families">
						<div class="section-heading">
							<div>
								<h3>{$t('datasetSnapshots.paperFamilies')}</h3>
								<span>{$t('datasetSnapshots.paperFamiliesHint')}</span>
							</div>
						</div>
						{#each selectedDocuments as documentId (documentId)}
							<label class="family-row"
								><span>{documentLabel(documentId)}</span><input
									bind:value={familyByDocument[documentId]}
									aria-label={$t('datasetSnapshots.familyFor', {
										document: documentLabel(documentId)
									})}
								/></label
							>
						{/each}
					</div>
				</details>
			{/if}
		</section>

		<aside class="summary-panel" aria-labelledby="summary-title">
			<div class="panel-heading panel-heading--compact">
				<div class="summary-icon"><PackageCheck size={20} aria-hidden="true" /></div>
				<div>
					<p class="eyebrow">{$t('datasetSnapshots.releaseStep')}</p>
					<h2 id="summary-title">{$t('datasetSnapshots.exportSummary')}</h2>
				</div>
			</div>
			<div class="summary-type">
				<span>{$t('datasetSnapshots.datasetType')}</span><strong>{datasetLabel(datasetType)}</strong
				>
			</div>
			<div class="summary-metrics">
				<div>
					<strong>{selectedCount}</strong><span>{$t('datasetSnapshots.selectedCases')}</span>
				</div>
				<div><strong>{splitCounts.train}</strong><span>train</span></div>
				<div><strong>{splitCounts.eval}</strong><span>eval</span></div>
				<div>
					<strong>{latestSnapshot?.row_count ?? 0}</strong><span
						>{$t('datasetSnapshots.lastRows')}</span
					>
				</div>
			</div>
			<div class="summary-format">
				<FileJson size={16} aria-hidden="true" />
				<div>
					<strong>{$t('datasetSnapshots.formatBadge')}</strong><span
						>{$t('datasetSnapshots.formatDetail')}</span
					>
				</div>
			</div>
			{#if selectedCount && !releaseReady}
				<div class="release-validation" role="status">
					<TriangleAlert size={16} aria-hidden="true" />
					<div>
						<strong>{$t('datasetSnapshots.releaseBlocked')}</strong>
						{#if selectedDetailLoadingCount}
							<span
								>{$t('datasetSnapshots.detailsStillLoading', {
									count: selectedDetailLoadingCount
								})}</span
							>
						{:else if selectedDetailErrorCount}
							<span
								>{$t('datasetSnapshots.detailsNeedRetry', {
									count: selectedDetailErrorCount
								})}</span
							>
						{:else if datasetValidationIssues.some((item) => item.reason === 'preference_pair_missing')}
							<span>{$t('datasetSnapshots.preferencePairRequired')}</span>
						{:else if datasetValidationIssues.some((item) => item.reason === 'target_missing')}
							<span>{$t('datasetSnapshots.targetRequired')}</span>
						{:else if datasetValidationIssues.some((item) => item.reason === 'dataset_use_not_authorized')}
							<span>{$t('datasetSnapshots.datasetUseRequired')}</span>
						{:else if missingFamilyDocuments.length}
							<span
								>{$t('datasetSnapshots.familyRequired', {
									count: missingFamilyDocuments.length
								})}</span
							>
						{/if}
					</div>
				</div>
			{/if}
			<button
				class="primary-button"
				type="button"
				on:click={saveSnapshot}
				disabled={saving || !releaseReady}
			>
				<Save size={16} aria-hidden="true" />{saving
					? $t('datasetSnapshots.saving')
					: $t('datasetSnapshots.freeze')}
			</button>
			{#if selectedCount && releaseReady}
				<p class="action-hint action-hint--ready">
					<CheckCircle2 size={14} aria-hidden="true" />{$t('datasetSnapshots.readyToFreeze')}
				</p>
			{:else if !selectedCount}
				<p class="action-hint">{$t('datasetSnapshots.selectToFreeze')}</p>
			{:else}
				<p class="action-hint">{$t('datasetSnapshots.completeChecksToFreeze')}</p>
			{/if}
			<p class="privacy-note">{$t('datasetSnapshots.freezeNote')}</p>
		</aside>
	</div>

	<section class="history-section" aria-labelledby="history-title">
		<div class="panel-heading">
			<div class="step-mark">02</div>
			<div>
				<p class="eyebrow">{$t('datasetSnapshots.historyEyebrow')}</p>
				<h2 id="history-title">{$t('datasetSnapshots.history')}</h2>
			</div>
			<span class="count-badge">{snapshots.length}</span>
		</div>
		{#if !snapshots.length}
			<div class="history-empty">
				<div class="empty-icon"><Download size={20} aria-hidden="true" /></div>
				<div>
					<strong>{$t('datasetSnapshots.noSnapshots')}</strong><span
						>{$t('datasetSnapshots.noSnapshotsDetail')}</span
					>
				</div>
			</div>
		{:else}
			<div class="snapshot-list">
				{#each snapshots as snapshot (snapshot.dataset_id)}
					<article class="snapshot-row">
						<div class="snapshot-main">
							<div class="snapshot-title">
								<strong>{datasetLabel(snapshot.dataset_type)}</strong><span class="status-chip"
									>{snapshot.row_count} {$t('datasetSnapshots.rows')}</span
								>{#if snapshot.is_empty}<span class="empty-chip"
										>{$t('datasetSnapshots.empty')}</span
									>{/if}
							</div>
							<small>{formatDate(snapshot.created_at)}</small><span class="snapshot-note"
								>{$t('datasetSnapshots.immutable')}</span
							>
						</div>
						<div class="snapshot-meta">
							<span>{$t('datasetSnapshots.excluded')}: {snapshot.excluded_count}</span>
							<div class="snapshot-actions">
								<button
									class="detail-button"
									type="button"
									aria-expanded={expandedSnapshot === snapshot.dataset_id}
									on:click={() => toggleSnapshot(snapshot)}
									><Eye size={15} aria-hidden="true" />{expandedSnapshot === snapshot.dataset_id
										? $t('datasetSnapshots.hideDetails')
										: $t('datasetSnapshots.viewDetails')}</button
								><button
									class="download-button"
									type="button"
									on:click={() => download(snapshot)}
									disabled={downloading === snapshot.dataset_id}
									><Download size={15} aria-hidden="true" />{downloading === snapshot.dataset_id
										? $t('datasetSnapshots.downloading')
										: $t('datasetSnapshots.download')}</button
								>
							</div>
						</div>
						{#if expandedSnapshot === snapshot.dataset_id}
							{@const detail = snapshotDetails[snapshot.dataset_id]}
							<div class="exclusion-details" aria-live="polite">
								{#if detailLoading === snapshot.dataset_id}
									<span class="muted">{$t('datasetSnapshots.loadingDetails')}</span>
								{:else if detail && detail.exclusions.length}
									<strong>{$t('datasetSnapshots.exclusionReasons')}</strong>
									{#each detail.exclusions as exclusion, exclusionIndex (`${String(exclusion.case_id ?? '')}-${String(exclusion.reason ?? '')}-${exclusionIndex}`)}
										<div class="exclusion-row">
											<span>{caseLabel(String(exclusion.case_id ?? ''))}</span><span
												>{exclusionReason(exclusion)}</span
											>
										</div>
									{/each}
								{:else if detail}
									<span class="muted">{$t('datasetSnapshots.noExclusions')}</span>
								{/if}
							</div>
						{/if}
					</article>
				{/each}
			</div>
		{/if}
	</section>
</section>

<style>
	.datasets {
		max-width: 1160px;
		margin: 0 auto;
		padding: 8px 0 56px;
		color: var(--text-primary);
	}
	.page-header,
	.panel-heading,
	.section-heading,
	.snapshot-title,
	.snapshot-meta,
	.back-link {
		display: flex;
		align-items: center;
	}
	.page-header {
		justify-content: space-between;
		gap: 24px;
		align-items: flex-start;
		padding-bottom: 22px;
		border-bottom: 1px solid var(--border-default);
	}
	.page-heading {
		min-width: 0;
	}
	.page-actions {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: 0 0 auto;
		padding-top: 28px;
	}
	.back-link {
		width: fit-content;
		gap: 6px;
		color: var(--text-secondary);
		text-decoration: none;
		font-size: 13px;
		margin-bottom: 14px;
	}
	.back-link:hover {
		color: var(--text-primary);
	}
	.eyebrow {
		margin: 0 0 6px;
		color: var(--brand-primary);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	h1,
	h2,
	h3,
	p {
		margin-top: 0;
	}
	h1 {
		margin-bottom: 8px;
		font-size: 32px;
		line-height: 1.15;
		letter-spacing: -0.02em;
	}
	h2 {
		margin-bottom: 0;
		font-size: 19px;
		line-height: 1.3;
	}
	h3 {
		margin-bottom: 3px;
		font-size: 14px;
		line-height: 1.35;
	}
	.lede {
		max-width: 680px;
		margin-bottom: 0;
		color: var(--text-secondary);
		line-height: 1.55;
	}
	.format-badge,
	.ready-chip,
	.case-status {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.format-badge {
		min-height: 32px;
		padding: 0 10px;
		border: 1px solid var(--brand-border);
		border-radius: 999px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 11px;
		font-weight: 800;
	}
	.icon-button,
	.download-button,
	.primary-button,
	.detail-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 7px;
		border: 1px solid var(--border-default);
		border-radius: 7px;
		cursor: pointer;
		font: inherit;
	}
	.icon-button {
		width: 36px;
		height: 36px;
		background: var(--surface-card);
		color: var(--text-secondary);
	}
	.icon-button:hover,
	.detail-button:hover {
		border-color: var(--brand-border);
		color: var(--brand-primary);
	}
	.primary-button {
		width: 100%;
		min-height: 44px;
		padding: 0 15px;
		border-color: var(--brand-primary);
		background: var(--brand-primary);
		color: #fff;
		font-size: 13px;
		font-weight: 750;
	}
	.primary-button:hover:not(:disabled) {
		background: var(--brand-primary-hover);
	}
	.download-button {
		min-height: 34px;
		padding: 0 11px;
		border-color: var(--brand-primary);
		background: var(--brand-primary);
		color: #fff;
		font-size: 12px;
		font-weight: 700;
	}
	.download-button:hover:not(:disabled) {
		background: var(--brand-primary-hover);
	}
	.detail-button {
		min-height: 34px;
		padding: 0 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 12px;
	}
	button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.primary-button:disabled {
		opacity: 1;
		border-color: var(--border-default);
		background: var(--bg-subtle);
		color: var(--text-disabled);
	}
	.notice {
		display: flex;
		align-items: flex-start;
		gap: 9px;
		margin: 18px 0 0;
		padding: 11px 13px;
		border-radius: 8px;
		font-size: 13px;
		line-height: 1.45;
	}
	.notice--error {
		border: 1px solid var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}
	.notice--success {
		border: 1px solid var(--success-border);
		background: var(--success-bg);
		color: var(--success-text);
	}
	.notice--warning {
		border: 1px solid var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
	}
	.flow-bar {
		display: grid;
		grid-template-columns: 1fr 34px 1fr 34px 1fr;
		align-items: center;
		gap: 10px;
		margin: 20px 0;
		padding: 12px 16px;
		border: 1px solid var(--border-default);
		border-radius: 10px;
		background: var(--surface-card);
		box-shadow: var(--shadow-xs);
	}
	.flow-step {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 0;
		color: var(--text-secondary);
	}
	.flow-step--active {
		color: var(--text-primary);
	}
	.flow-step--done {
		color: var(--success-text);
	}
	.flow-number {
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		width: 25px;
		height: 25px;
		border-radius: 50%;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 800;
	}
	.flow-step--active .flow-number {
		background: var(--brand-primary);
		color: #fff;
	}
	.flow-step--done .flow-number {
		background: var(--success-bg);
		color: var(--success-text);
	}
	.flow-step strong,
	.flow-step small {
		display: block;
	}
	.flow-step em {
		display: block;
		margin-top: 3px;
		color: inherit;
		font-size: 9px;
		font-style: normal;
		font-weight: 700;
		line-height: 1.2;
	}
	.flow-step strong {
		font-size: 11px;
	}
	.flow-step small {
		margin-top: 1px;
		color: var(--text-secondary);
		font-size: 10px;
		line-height: 1.35;
	}
	.flow-connector {
		height: 1px;
		background: var(--border-default);
	}
	.summary-icon,
	.empty-icon {
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		width: 34px;
		height: 34px;
		border-radius: 8px;
		background: var(--brand-soft);
		color: var(--brand-primary);
	}
	.release-layout {
		display: grid;
		grid-template-columns: minmax(0, 1.42fr) minmax(280px, 0.58fr);
		gap: 18px;
		align-items: start;
	}
	.builder-panel,
	.summary-panel {
		border: 1px solid var(--border-default);
		border-radius: 11px;
		background: var(--surface-card);
		box-shadow: var(--shadow-xs);
	}
	.builder-panel {
		min-width: 0;
		padding: 22px;
	}
	.summary-panel {
		position: sticky;
		top: 96px;
		min-width: 0;
		padding: 20px;
	}
	.validation-section {
		padding: 17px 0 0;
	}
	.validation-section summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		cursor: pointer;
		list-style: none;
	}
	.validation-section summary::-webkit-details-marker {
		display: none;
	}
	.validation-section summary > span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: var(--text-primary);
		font-size: 12px;
	}
	.validation-section summary > span :global(svg) {
		color: var(--success-text);
	}
	.validation-section summary small {
		color: var(--text-secondary);
		font-size: 10px;
	}
	.history-section {
		margin-top: 26px;
		padding-top: 21px;
		border-top: 1px solid var(--border-default);
	}
	.panel-heading {
		gap: 11px;
		margin-bottom: 21px;
	}
	.panel-heading > :last-child {
		margin-left: auto;
	}
	.panel-heading--compact {
		align-items: flex-start;
	}
	.panel-heading--compact > :last-child {
		margin-left: 0;
	}
	.step-mark {
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		width: 28px;
		height: 28px;
		border-radius: 8px;
		background: var(--brand-primary);
		color: #fff;
		font-size: 11px;
		font-weight: 800;
	}
	.count-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 48px;
		height: 25px;
		padding: 0 8px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.type-section {
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.type-options {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
	}
	.type-option {
		position: relative;
		display: flex;
		min-width: 0;
		min-height: 91px;
		align-items: flex-start;
		gap: 8px;
		padding: 12px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--bg-subtle);
		cursor: pointer;
		transition:
			border-color 0.15s ease,
			background 0.15s ease,
			box-shadow 0.15s ease;
	}
	.type-option:hover {
		border-color: var(--brand-border);
	}
	.type-option.active {
		border-color: var(--brand-primary);
		background: var(--brand-soft);
		box-shadow: inset 0 0 0 1px var(--brand-primary);
	}
	.type-option input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.type-option :global(svg) {
		flex: 0 0 auto;
		margin-left: auto;
		color: var(--brand-primary);
	}
	.type-option-copy {
		display: grid;
		min-width: 0;
		gap: 4px;
	}
	.type-option-copy strong {
		font-size: 12px;
		line-height: 1.3;
	}
	.type-option-copy small {
		color: var(--text-secondary);
		font-size: 10px;
		line-height: 1.4;
	}
	.format-note {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 11px 0 0;
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 1.4;
	}
	.format-note :global(svg) {
		flex: 0 0 auto;
		color: var(--brand-primary);
	}
	.cases-section {
		margin-top: 25px;
	}
	.output-section {
		margin-top: 24px;
		padding-top: 21px;
		border-top: 1px solid var(--border-default);
	}
	.section-heading {
		justify-content: space-between;
		gap: 14px;
		margin-bottom: 11px;
	}
	.section-heading > div {
		min-width: 0;
	}
	.section-kicker {
		margin: 0 0 3px;
		color: var(--brand-primary);
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.08em;
		line-height: 1;
	}
	.section-heading span:not(.ready-chip) {
		display: block;
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 1.45;
	}
	.ready-chip {
		flex: 0 0 auto;
		padding: 4px 7px;
		border-radius: 999px;
		background: var(--success-bg);
		color: var(--success-text);
		font-size: 10px;
		font-weight: 750;
	}
	.case-filters {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 190px;
		gap: 8px;
		margin-bottom: 9px;
	}
	.search-field,
	.filter-field {
		display: block;
		min-width: 0;
	}
	.search-field input,
	.filter-field select {
		width: 100%;
		min-height: 34px;
		padding: 0 9px;
		font-size: 11px;
	}
	.filtered-empty {
		padding: 16px 12px;
		border: 1px dashed var(--border-strong);
		border-radius: 8px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 11px;
	}
	.selection-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 8px;
		color: var(--text-secondary);
		font-size: 11px;
	}
	.toolbar-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.text-button {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		min-height: 28px;
		padding: 0 5px;
		border: 0;
		background: transparent;
		color: var(--brand-primary);
		font: inherit;
		font-size: 11px;
		font-weight: 700;
		cursor: pointer;
	}
	.text-button:hover:not(:disabled) {
		color: var(--brand-primary-hover);
	}
	.text-button--quiet {
		color: var(--text-secondary);
	}
	.case-options {
		display: grid;
		gap: 7px;
		max-height: 470px;
		overflow: auto;
		padding: 2px;
	}
	.case-option {
		display: grid;
		grid-template-columns: 20px minmax(0, 1fr) 94px;
		gap: 10px;
		align-items: center;
		min-width: 0;
		padding: 12px 11px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--bg-subtle);
	}
	.case-option:hover,
	.case-option.selected {
		border-color: var(--brand-border);
	}
	.case-option.selected {
		background: color-mix(in srgb, var(--brand-soft) 52%, var(--surface-card));
		box-shadow: inset 3px 0 0 var(--brand-primary);
	}
	.case-option input {
		width: 16px;
		height: 16px;
		accent-color: var(--brand-primary);
	}
	.case-copy {
		display: grid;
		min-width: 0;
		gap: 3px;
	}
	.case-copy label {
		min-width: 0;
		cursor: pointer;
	}
	.case-copy strong {
		display: -webkit-box;
		overflow: hidden;
		color: var(--text-primary);
		font-size: 12px;
		line-height: 1.4;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
	}
	.case-copy small {
		overflow: hidden;
		color: var(--text-secondary);
		font-size: 10px;
		line-height: 1.3;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.case-status {
		width: fit-content;
		margin-top: 2px;
		color: var(--success-text);
		font-size: 10px;
		line-height: 1.2;
	}
	.case-detail-state {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		width: fit-content;
		margin-top: 3px;
		font-size: 10px;
		line-height: 1.25;
	}
	.case-detail-state--loading {
		color: var(--warning-text);
	}
	.case-detail-state--ready {
		color: var(--success-text);
	}
	.case-detail-state--error {
		color: var(--danger-text);
	}
	.retry-link {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		padding: 0;
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		font-weight: 750;
		text-decoration: underline;
		cursor: pointer;
	}
	.release-validation {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		margin: 16px 0 10px;
		padding: 10px 11px;
		border: 1px solid var(--warning-border);
		border-radius: 7px;
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 11px;
		line-height: 1.4;
	}
	.release-validation strong,
	.release-validation span {
		display: block;
	}
	.release-validation strong {
		margin-bottom: 2px;
		font-size: 11px;
	}
	.split-field {
		display: grid;
		gap: 4px;
		min-width: 0;
		color: var(--text-secondary);
		font-size: 10px;
	}
	.split-field select,
	select,
	input {
		box-sizing: border-box;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
	}
	.split-field select {
		width: 100%;
		min-height: 31px;
		padding: 0 7px;
		font-size: 11px;
	}
	.families {
		margin: 19px 0 0;
		padding-top: 17px;
		border-top: 1px solid var(--border-default);
	}
	.family-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(140px, 0.7fr);
		gap: 10px;
		align-items: center;
		margin-top: 9px;
		font-size: 11px;
	}
	.family-row span {
		overflow: hidden;
		color: var(--text-secondary);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.family-row input {
		width: 100%;
		min-height: 33px;
		padding: 0 8px;
		font-size: 12px;
	}
	.summary-icon {
		width: 34px;
		height: 34px;
	}
	.summary-type {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 11px 0;
		border-top: 1px solid var(--border-default);
		border-bottom: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 11px;
	}
	.summary-type strong {
		color: var(--text-primary);
		font-size: 12px;
	}
	.summary-metrics {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1px;
		margin: 16px 0;
		overflow: hidden;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--border-default);
	}
	.summary-metrics > div {
		display: grid;
		gap: 2px;
		padding: 11px;
		background: var(--bg-subtle);
	}
	.summary-metrics strong {
		font-size: 20px;
		line-height: 1.1;
		font-variant-numeric: tabular-nums;
	}
	.summary-metrics span {
		color: var(--text-secondary);
		font-size: 10px;
	}
	.summary-format {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		margin-bottom: 16px;
		color: var(--brand-primary);
	}
	.summary-format > div {
		display: grid;
		gap: 2px;
	}
	.summary-format strong {
		font-size: 11px;
	}
	.summary-format span {
		color: var(--text-secondary);
		font-size: 10px;
		line-height: 1.4;
	}
	.action-hint {
		display: flex;
		align-items: flex-start;
		gap: 6px;
		margin: 9px 0 0;
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 1.4;
	}
	.action-hint--ready {
		color: var(--success-text);
	}
	.action-hint :global(svg) {
		flex: 0 0 auto;
		margin-top: 2px;
	}
	.privacy-note {
		margin: 14px 0 0;
		color: var(--text-secondary);
		font-size: 10px;
		line-height: 1.5;
	}
	.empty-state,
	.history-empty {
		display: flex;
		align-items: center;
		gap: 11px;
		padding: 22px 15px;
		border: 1px dashed var(--border-strong);
		border-radius: 8px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
	}
	.empty-state strong,
	.history-empty strong {
		display: block;
		color: var(--text-primary);
		font-size: 12px;
	}
	.empty-state span,
	.history-empty span {
		display: block;
		margin-top: 3px;
		font-size: 11px;
		line-height: 1.45;
	}
	.empty-state--action {
		flex-wrap: wrap;
	}
	.empty-state--action > div:not(.empty-icon) {
		min-width: 0;
		flex: 1 1 180px;
	}
	.empty-icon {
		width: 34px;
		height: 34px;
	}
	.inline-action {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		margin-left: 45px;
		color: var(--brand-primary);
		font-size: 11px;
		font-weight: 750;
		text-decoration: none;
	}
	.inline-action:hover {
		color: var(--brand-primary-hover);
	}
	.loading-state {
		display: grid;
		gap: 9px;
		padding: 14px 2px;
	}
	.loading-bar {
		display: block;
		width: 100%;
		height: 48px;
		border-radius: 8px;
		background: linear-gradient(
			90deg,
			var(--bg-subtle) 25%,
			var(--brand-soft) 50%,
			var(--bg-subtle) 75%
		);
		background-size: 200% 100%;
		animation: loading 1.2s ease-in-out infinite;
	}
	.loading-bar--short {
		width: 72%;
		height: 12px;
	}
	.snapshot-list {
		display: grid;
	}
	.snapshot-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 18px;
		align-items: center;
		padding: 15px 0;
		border-bottom: 1px solid var(--border-default);
	}
	.snapshot-row:last-child {
		border-bottom: 0;
	}
	.snapshot-title {
		flex-wrap: wrap;
		gap: 7px;
	}
	.status-chip,
	.empty-chip {
		padding: 3px 7px;
		border-radius: 999px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 10px;
		font-weight: 700;
	}
	.empty-chip {
		color: var(--warning-text);
		background: var(--warning-bg);
	}
	.snapshot-main {
		display: grid;
		gap: 4px;
		min-width: 0;
	}
	.snapshot-main small,
	.snapshot-note {
		color: var(--text-secondary);
		font-size: 10px;
	}
	.snapshot-note {
		font-size: 10px;
	}
	.snapshot-meta {
		justify-content: flex-end;
		gap: 14px;
		color: var(--text-secondary);
		font-size: 11px;
		white-space: nowrap;
	}
	.snapshot-actions {
		display: flex;
		align-items: center;
		gap: 7px;
	}
	.exclusion-details {
		grid-column: 1 / -1;
		display: grid;
		gap: 7px;
		padding: 11px;
		border: 1px solid var(--border-default);
		border-radius: 7px;
		background: var(--bg-subtle);
		font-size: 11px;
	}
	.exclusion-row {
		display: grid;
		grid-template-columns: minmax(90px, 0.7fr) minmax(0, 1fr);
		gap: 10px;
		color: var(--text-secondary);
	}
	.exclusion-row span {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	button:focus-visible,
	a:focus-visible,
	input:focus-visible,
	select:focus-visible {
		outline: 3px solid color-mix(in srgb, var(--brand-primary) 35%, transparent);
		outline-offset: 2px;
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
	.spin {
		display: inline-flex;
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@keyframes loading {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}
	@media (max-width: 960px) {
		.datasets {
			padding-top: 0;
		}
		.release-layout {
			grid-template-columns: 1fr;
		}
		.summary-panel {
			position: static;
		}
	}
	@media (max-width: 720px) {
		.flow-bar {
			grid-template-columns: 1fr;
			gap: 8px;
		}
		.flow-connector {
			display: none;
		}
		.type-options {
			grid-template-columns: 1fr;
		}
		.type-option {
			min-height: auto;
		}
		.snapshot-row {
			grid-template-columns: 1fr;
			gap: 10px;
		}
		.snapshot-meta {
			justify-content: space-between;
		}
	}
	@media (max-width: 520px) {
		.datasets {
			padding-bottom: 40px;
		}
		.page-header {
			gap: 12px;
		}
		.page-actions {
			padding-top: 26px;
		}
		h1 {
			font-size: 28px;
		}
		.builder-panel,
		.summary-panel {
			padding: 16px;
		}
		.case-option {
			grid-template-columns: 20px minmax(0, 1fr);
			align-items: start;
		}
		.split-field {
			grid-column: 2;
			width: 110px;
		}
		.selection-toolbar {
			align-items: flex-start;
			flex-direction: column;
			gap: 4px;
		}
		.case-filters {
			grid-template-columns: 1fr;
		}
		.inline-action {
			margin-left: 45px;
		}
		.snapshot-meta {
			align-items: flex-start;
			flex-direction: column;
			gap: 9px;
		}
		.snapshot-actions {
			flex-wrap: wrap;
		}
		.exclusion-row {
			grid-template-columns: 1fr;
			gap: 2px;
		}
	}
</style>
