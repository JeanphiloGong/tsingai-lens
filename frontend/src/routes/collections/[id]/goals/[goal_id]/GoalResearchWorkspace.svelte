<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { authState } from '../../../../_shared/auth';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchResearchUnderstandingCurations,
		fetchResearchUnderstandingDataset,
		fetchResearchUnderstandingFeedback,
		type ResearchUnderstanding,
		type ResearchUnderstandingAxisCoverageItem,
		type ResearchUnderstandingCuration,
		type ResearchUnderstandingDataset,
		type ResearchUnderstandingFeedback,
		type ResearchUnderstandingPaperContribution,
		type ResearchUnderstandingPresentationEvidence,
		type ResearchUnderstandingPresentationFinding
	} from '../../../../_shared/researchView';
	import GoalReviewDialog from './GoalReviewDialog.svelte';

	type WorkspaceView = 'findings' | 'coverage';
	type FindingFilter = 'all' | 'needs_review' | 'accepted' | 'limited';
	type ReviewState = 'accepted' | 'rejected' | 'curated' | 'needs_review' | 'unreviewed';
	type EvidenceOption = {
		evidenceRefId: string;
		label: string;
		detail: string;
	};
	type PaperEvidenceRow = {
		key: string;
		title: string;
		role: string;
		statement: string;
		evidence: ResearchUnderstandingPresentationEvidence[];
	};

	export let understanding: ResearchUnderstanding | null = null;
	export let collectionId = '';
	export let goalId = '';
	export let returnTo = '';
	export let initialFocus: '' | 'review_queue' | 'training_ready' = '';
	export let initialFindingId = '';

	let activeView: WorkspaceView = 'findings';
	let findingFilter: FindingFilter = 'all';
	let searchQuery = '';
	let selectedFindingId = '';
	let reviewOpen = false;
	let feedback: ResearchUnderstandingFeedback[] = [];
	let curations: ResearchUnderstandingCuration[] = [];
	let dataset: ResearchUnderstandingDataset | null = null;
	let reviewLoadError = '';
	let loadedScopeKey = '';
	let appliedInitialKey = '';

	$: presentation = understanding?.presentation ?? null;
	$: scopeType = understanding?.scope.scope_type || 'goal';
	$: scopeId = understanding?.scope.goal_id || goalId;
	$: scopeKey = `${collectionId}:${scopeType}:${scopeId}`;
	$: baseFindings = presentation
		? dedupeFindings(
				presentation.findings.length
					? presentation.findings
					: [...presentation.primary_findings, ...presentation.review_queue_findings]
			)
		: [];
	$: feedbackByFindingId = groupFeedback(feedback);
	$: curationsByFindingId = groupCurations(curations);
	$: findings = baseFindings.map((finding) =>
		applyCuration(finding, curationsByFindingId.get(finding.finding_id) ?? null)
	);
	$: selectedFinding = findings.find((finding) => finding.finding_id === selectedFindingId) ?? null;
	$: selectedBaseFinding =
		baseFindings.find((finding) => finding.finding_id === selectedFindingId) ?? null;
	$: selectedFeedback = selectedFinding
		? (feedbackByFindingId.get(selectedFinding.finding_id) ?? [])
		: [];
	$: selectedCuration = selectedFinding
		? (curationsByFindingId.get(selectedFinding.finding_id) ?? null)
		: null;
	$: filteredFindings = findings.filter(matchesFindingFilters);
	$: needsReviewCount = findings.filter((finding) =>
		['needs_review', 'unreviewed'].includes(reviewState(finding))
	).length;
	$: sourcePaperCount = countSourcePapers(findings);
	$: selectedPaperRows = selectedFinding ? paperEvidenceRows(selectedFinding) : [];
	$: selectedEvidenceOptions = selectedFinding ? evidenceOptions(selectedFinding) : [];
	$: selectedDatasetSample = selectedFinding
		? (dataset?.items.find((item) => item.finding_id === selectedFinding.finding_id) ?? null)
		: null;
	$: selectedAcceptBlocked = Boolean(
		selectedDatasetSample?.acceptance_gate &&
		(!selectedDatasetSample.acceptance_gate.accept_allowed ||
			selectedDatasetSample.acceptance_gate.requires_correction ||
			selectedDatasetSample.acceptance_gate.accept_blockers.length)
	);
	$: selectedAcceptanceChecks = selectedDatasetSample?.acceptance_gate?.review_checks ?? [];
	$: reviewer = $authState.user?.email?.trim() || $authState.user?.display_name?.trim() || '';
	$: axisCoverage = presentation?.summary.axis_coverage ?? { variables: [], properties: [] };
	$: totalAxisCount = axisCoverage.variables.length + axisCoverage.properties.length;
	$: coveredAxisCount = [...axisCoverage.variables, ...axisCoverage.properties].filter(
		(item) => item.status !== 'missing'
	).length;
	$: if (browser && understanding && scopeId && scopeKey !== loadedScopeKey) {
		loadedScopeKey = scopeKey;
		void loadReviewState();
	}
	$: if (understanding && `${scopeKey}:${initialFocus}:${initialFindingId}` !== appliedInitialKey) {
		appliedInitialKey = `${scopeKey}:${initialFocus}:${initialFindingId}`;
		if (initialFocus === 'review_queue') findingFilter = 'needs_review';
		if (initialFocus === 'training_ready') findingFilter = 'accepted';
		if (
			initialFindingId &&
			baseFindings.some((finding) => finding.finding_id === initialFindingId)
		) {
			selectedFindingId = initialFindingId;
			activeView = 'findings';
		}
	}

	async function loadReviewState() {
		reviewLoadError = '';
		try {
			const [nextFeedback, nextCurations, nextDataset] = await Promise.all([
				fetchResearchUnderstandingFeedback(collectionId, {
					scope_type: scopeType,
					scope_id: scopeId
				}),
				fetchResearchUnderstandingCurations(collectionId, {
					scope_type: scopeType,
					scope_id: scopeId
				}),
				fetchResearchUnderstandingDataset(collectionId, {
					scope_type: scopeType,
					scope_id: scopeId
				})
			]);
			feedback = nextFeedback;
			curations = nextCurations;
			dataset = nextDataset;
		} catch (error) {
			reviewLoadError =
				error instanceof Error
					? error.message
					: $t('research.goalWorkspace.reviewStateUnavailable');
		}
	}

	function dedupeFindings(currentFindings: ResearchUnderstandingPresentationFinding[]) {
		const seen = new Set<string>();
		return currentFindings.filter((finding) => {
			if (!finding.finding_id || seen.has(finding.finding_id)) return false;
			seen.add(finding.finding_id);
			return true;
		});
	}

	function reviewTargetId(record: ResearchUnderstandingFeedback | ResearchUnderstandingCuration) {
		return record.finding_id || record.claim_id || '';
	}

	function groupFeedback(records: ResearchUnderstandingFeedback[]) {
		const grouped = new Map<string, ResearchUnderstandingFeedback[]>();
		for (const record of records) {
			const targetId = reviewTargetId(record);
			if (!targetId) continue;
			grouped.set(targetId, [...(grouped.get(targetId) ?? []), record]);
		}
		return grouped;
	}

	function groupCurations(records: ResearchUnderstandingCuration[]) {
		const grouped = new Map<string, ResearchUnderstandingCuration>();
		for (const record of records) {
			const targetId = reviewTargetId(record);
			if (targetId) grouped.set(targetId, record);
		}
		return grouped;
	}

	function applyCuration(
		finding: ResearchUnderstandingPresentationFinding,
		curation: ResearchUnderstandingCuration | null
	): ResearchUnderstandingPresentationFinding {
		if (!curation) return finding;
		return {
			...finding,
			statement: curation.curated_statement || finding.statement,
			variables: curation.curated_variables?.length
				? curation.curated_variables
				: finding.variables,
			mediators: curation.curated_mediators?.length
				? curation.curated_mediators
				: finding.mediators,
			outcomes: curation.curated_outcomes?.length ? curation.curated_outcomes : finding.outcomes,
			direction: curation.curated_direction || finding.direction,
			scope_summary: curation.curated_scope_summary || finding.scope_summary,
			support_grade: curation.curated_support_grade || finding.support_grade,
			review_status: curation.curated_review_status || 'curated',
			evidence_ref_ids: curation.curated_evidence_ref_ids.length
				? curation.curated_evidence_ref_ids
				: finding.evidence_ref_ids,
			context_ids: curation.curated_context_ids.length
				? curation.curated_context_ids
				: finding.context_ids
		};
	}

	function latestFeedback(finding: ResearchUnderstandingPresentationFinding) {
		const records = feedbackByFindingId.get(finding.finding_id) ?? [];
		return records[records.length - 1] ?? null;
	}

	function reviewState(finding: ResearchUnderstandingPresentationFinding): ReviewState {
		if (curationsByFindingId.has(finding.finding_id)) return 'curated';
		const record = latestFeedback(finding);
		if (record?.review_status === 'correct' && record.issue_type === 'none') return 'accepted';
		if (record?.review_status === 'incorrect') return 'rejected';
		if (record) return 'needs_review';
		if (finding.review_status === 'accepted') return 'accepted';
		if (finding.review_status === 'curated') return 'curated';
		if (finding.review_status === 'needs_review' || finding.review_status === 'pending_review') {
			return 'needs_review';
		}
		return 'unreviewed';
	}

	function reviewStateLabel(finding: ResearchUnderstandingPresentationFinding) {
		return $t(`research.goalWorkspace.reviewStates.${reviewState(finding)}`);
	}

	function matchesFindingFilters(finding: ResearchUnderstandingPresentationFinding) {
		const query = searchQuery.trim().toLowerCase();
		const searchable = [
			finding.statement,
			...finding.variables,
			...finding.mediators,
			...finding.outcomes,
			finding.scope_summary
		]
			.join(' ')
			.toLowerCase();
		if (query && !searchable.includes(query)) return false;
		const state = reviewState(finding);
		if (findingFilter === 'needs_review') {
			return state === 'needs_review' || state === 'unreviewed';
		}
		if (findingFilter === 'accepted') return state === 'accepted' || state === 'curated';
		if (findingFilter === 'limited') {
			return ['weak', 'partial', 'insufficient', 'conflict'].includes(finding.support_grade);
		}
		return true;
	}

	function countSourcePapers(currentFindings: ResearchUnderstandingPresentationFinding[]) {
		const documentIds = new Set<string>();
		for (const finding of currentFindings) {
			for (const contribution of finding.paper_contributions) {
				if (contribution.document_id) documentIds.add(contribution.document_id);
			}
			for (const evidence of evidenceForFinding(finding)) {
				if (evidence.document_id) documentIds.add(evidence.document_id);
			}
		}
		return documentIds.size;
	}

	function evidenceById() {
		return new Map(
			(presentation?.evidence_items ?? []).map((evidence) => [evidence.evidence_ref_id, evidence])
		);
	}

	function evidenceForFinding(finding: ResearchUnderstandingPresentationFinding) {
		const byId = evidenceById();
		return finding.evidence_ref_ids
			.map((evidenceRefId) => byId.get(evidenceRefId))
			.filter((item): item is ResearchUnderstandingPresentationEvidence => Boolean(item));
	}

	function cleanPaperTitle(value: string | null | undefined) {
		const clean = (value ?? '')
			.replace(/\s*\/\s*p\.\s*\d+.*$/i, '')
			.replace(/\.pdf$/i, '')
			.replace(/^[a-f0-9]{24,}[_-]/i, '')
			.replace(/[_]+/g, ' ')
			.trim();
		return clean || $t('research.goalWorkspace.untitledPaper');
	}

	function contributionTitle(contribution: ResearchUnderstandingPaperContribution) {
		return cleanPaperTitle(contribution.source_filename || contribution.title);
	}

	function fallbackEvidenceTitle(evidence: ResearchUnderstandingPresentationEvidence) {
		return cleanPaperTitle(evidence.source_label || evidence.title);
	}

	function paperEvidenceRows(
		finding: ResearchUnderstandingPresentationFinding
	): PaperEvidenceRow[] {
		const evidence = evidenceForFinding(finding);
		const rows = new Map<string, PaperEvidenceRow>();
		for (const contribution of finding.paper_contributions) {
			const key = contribution.document_id || contributionTitle(contribution);
			rows.set(key, {
				key,
				title: contributionTitle(contribution),
				role: contribution.role,
				statement: contribution.statement,
				evidence: []
			});
		}
		for (const item of evidence) {
			const key = item.document_id || fallbackEvidenceTitle(item);
			const existing = rows.get(key) ?? {
				key,
				title: fallbackEvidenceTitle(item),
				role: 'supporting',
				statement: '',
				evidence: []
			};
			existing.evidence.push(item);
			rows.set(key, existing);
		}
		return [...rows.values()];
	}

	function paperTitleForEvidence(
		finding: ResearchUnderstandingPresentationFinding,
		evidence: ResearchUnderstandingPresentationEvidence
	) {
		const contribution = finding.paper_contributions.find(
			(item) => item.document_id && item.document_id === evidence.document_id
		);
		return contribution ? contributionTitle(contribution) : fallbackEvidenceTitle(evidence);
	}

	function evidenceOptions(finding: ResearchUnderstandingPresentationFinding): EvidenceOption[] {
		return evidenceForFinding(finding).map((evidence) => ({
			evidenceRefId: evidence.evidence_ref_id,
			label: paperTitleForEvidence(finding, evidence),
			detail: evidenceMeta(evidence)
		}));
	}

	function evidenceRole(finding: ResearchUnderstandingPresentationFinding, evidenceRefId: string) {
		for (const role of [
			'direct_result',
			'mechanism',
			'condition_context',
			'conflict',
			'background',
			'uncategorized'
		] as const) {
			if (finding.evidence_bundle[role].includes(evidenceRefId)) return role;
		}
		return 'uncategorized';
	}

	function evidenceRoleLabel(
		finding: ResearchUnderstandingPresentationFinding,
		evidenceRefId: string
	) {
		const role = evidenceRole(finding, evidenceRefId);
		return role === 'uncategorized'
			? $t('research.goalWorkspace.additionalEvidence')
			: $t(`research.understanding.findingEvidenceGroups.${role}`);
	}

	function evidenceText(evidence: ResearchUnderstandingPresentationEvidence) {
		return (
			evidence.quote || evidence.source_text || $t('research.understanding.noEvidenceSourceText')
		);
	}

	function evidenceTextIsLong(evidence: ResearchUnderstandingPresentationEvidence) {
		return evidenceText(evidence).length > 520;
	}

	function evidencePreview(evidence: ResearchUnderstandingPresentationEvidence) {
		const text = evidenceText(evidence);
		return text.length > 520 ? `${text.slice(0, 520).trim()}...` : text;
	}

	function evidenceMeta(evidence: ResearchUnderstandingPresentationEvidence) {
		return [
			readableToken(evidence.block_type || evidence.source_kind),
			evidence.page ? $t('research.goalWorkspace.pageNumber', { page: evidence.page }) : '',
			evidence.heading_path
		]
			.filter(Boolean)
			.join(' · ');
	}

	function evidenceHref(evidence: ResearchUnderstandingPresentationEvidence) {
		let href = evidence.href ?? '';
		if (!href && evidence.document_id) {
			href = resolve('/collections/[id]/documents/[document_id]', {
				id: collectionId,
				document_id: evidence.document_id
			});
		}
		if (!href) return '';
		const url = new URL(href, 'http://localhost');
		if (returnTo && !url.searchParams.get('return_to')) {
			url.searchParams.set('return_to', returnTo);
		}
		return `${url.pathname}${url.search}`;
	}

	function readableToken(value: string | null | undefined) {
		if (!value) return $t('research.emptyValue');
		return value.replace(/_/g, ' ');
	}

	function supportGradeLabel(grade: string) {
		return $t(`research.understanding.supportGrades.${grade}`);
	}

	function directionLabel(direction: string) {
		if (!direction) return $t('research.goalWorkspace.relationshipUnspecified');
		return $t(`research.understanding.relations.${direction}`) ===
			`research.understanding.relations.${direction}`
			? readableToken(direction)
			: $t(`research.understanding.relations.${direction}`);
	}

	function listLabel(values: string[]) {
		return values.length ? values.join(', ') : $t('research.emptyValue');
	}

	function synthesisStatusLabel(status: string) {
		return $t(`research.goalWorkspace.synthesisStates.${status}`) ===
			`research.goalWorkspace.synthesisStates.${status}`
			? readableToken(status)
			: $t(`research.goalWorkspace.synthesisStates.${status}`);
	}

	function contributionRoleLabel(role: string) {
		return $t(`research.goalWorkspace.paperRoles.${role}`) ===
			`research.goalWorkspace.paperRoles.${role}`
			? readableToken(role)
			: $t(`research.goalWorkspace.paperRoles.${role}`);
	}

	function coverageStatusLabel(item: ResearchUnderstandingAxisCoverageItem) {
		if (item.finding_id) {
			const finding = findings.find((candidate) => candidate.finding_id === item.finding_id);
			if (finding) {
				const state = reviewState(finding);
				if (state === 'accepted' || state === 'curated') {
					return $t('research.goalWorkspace.coverageStates.reviewed');
				}
			}
		}
		return $t(`research.goalWorkspace.coverageStates.${item.status}`);
	}

	function openFinding(findingId: string) {
		selectedFindingId = findingId;
		activeView = 'findings';
		reviewOpen = false;
	}

	function closeFinding() {
		selectedFindingId = '';
		reviewOpen = false;
	}

	function selectView(view: WorkspaceView) {
		activeView = view;
		selectedFindingId = '';
		reviewOpen = false;
	}

	function reviewSubmitted(record: ResearchUnderstandingFeedback | ResearchUnderstandingCuration) {
		if ('feedback_id' in record) {
			feedback = [...feedback, record];
		} else {
			curations = [
				...curations.filter((item) => reviewTargetId(item) !== reviewTargetId(record)),
				record
			];
		}
		void refreshDataset();
	}

	async function refreshDataset() {
		try {
			dataset = await fetchResearchUnderstandingDataset(collectionId, {
				scope_type: scopeType,
				scope_id: scopeId
			});
		} catch {
			// The saved expert decision remains visible even if dataset refresh is temporarily unavailable.
		}
	}

	function visibleWarnings(finding: ResearchUnderstandingPresentationFinding) {
		const values = [...finding.review_reasons, ...finding.warnings];
		const labels = values
			.map((value) => {
				const translated = $t(`research.understanding.reviewReasons.${value}`);
				if (translated !== `research.understanding.reviewReasons.${value}`) return translated;
				return /\s/.test(value) ? value : '';
			})
			.filter(Boolean);
		return [...new Set(labels)];
	}
</script>

{#if !understanding}
	<section class="workspace-state">
		<h2>{$t('research.goalWorkspace.findingsTitle')}</h2>
		<p>{$t('research.understanding.unavailable')}</p>
	</section>
{:else}
	<section class="goal-research-workspace" aria-labelledby="goal-findings-title">
		<header class="workspace-header">
			<div>
				<p class="eyebrow">{$t('research.goalWorkspace.researchEvidence')}</p>
				<h2 id="goal-findings-title">{$t('research.goalWorkspace.findingsTitle')}</h2>
			</div>
			<div class="workspace-stats" aria-label={$t('research.goalWorkspace.workspaceSummary')}>
				<div>
					<strong>{findings.length}</strong>
					<span>{$t('research.goalWorkspace.findingsMetric')}</span>
				</div>
				<div>
					<strong>{sourcePaperCount}</strong>
					<span>{$t('research.goalWorkspace.sourcePapersMetric')}</span>
				</div>
				<div class:attention={needsReviewCount > 0}>
					<strong>{needsReviewCount}</strong>
					<span>{$t('research.goalWorkspace.needsReviewMetric')}</span>
				</div>
			</div>
		</header>

		<nav class="workspace-tabs" aria-label={$t('research.goalWorkspace.workspaceViews')}>
			<button
				type="button"
				class:active={activeView === 'findings'}
				aria-current={activeView === 'findings' ? 'page' : undefined}
				on:click={() => selectView('findings')}
			>
				{$t('research.goalWorkspace.findingsTab')}
				<span>{findings.length}</span>
			</button>
			<button
				type="button"
				class:active={activeView === 'coverage'}
				aria-current={activeView === 'coverage' ? 'page' : undefined}
				on:click={() => selectView('coverage')}
			>
				{$t('research.goalWorkspace.coverageTab')}
				<span>{coveredAxisCount}/{totalAxisCount}</span>
			</button>
		</nav>

		{#if reviewLoadError}
			<p class="review-load-error" role="status">
				{$t('research.goalWorkspace.reviewStateUnavailable')}
			</p>
		{/if}

		{#if activeView === 'findings' && !selectedFinding}
			<div class="finding-toolbar">
				<label class="finding-search">
					<span>{$t('research.goalWorkspace.searchFindings')}</span>
					<input
						type="search"
						name="finding_search"
						bind:value={searchQuery}
						placeholder={$t('research.goalWorkspace.searchPlaceholder')}
					/>
				</label>
				<label class="finding-filter">
					<span>{$t('research.goalWorkspace.filterFindings')}</span>
					<select name="finding_filter" bind:value={findingFilter}>
						<option value="all">{$t('research.goalWorkspace.filters.all')}</option>
						<option value="needs_review">
							{$t('research.goalWorkspace.filters.needsReview')}
						</option>
						<option value="accepted">{$t('research.goalWorkspace.filters.accepted')}</option>
						<option value="limited">{$t('research.goalWorkspace.filters.limited')}</option>
					</select>
				</label>
			</div>

			{#if !filteredFindings.length}
				<div class="workspace-state">
					<h3>{$t('research.goalWorkspace.noFindingsTitle')}</h3>
					<p>{$t('research.understanding.noFindings')}</p>
				</div>
			{:else}
				<div class="findings-table-wrap">
					<table class="findings-table">
						<caption>{$t('research.goalWorkspace.findingsTable')}</caption>
						<thead>
							<tr>
								<th scope="col">{$t('research.goalWorkspace.finding')}</th>
								<th scope="col">{$t('research.goalWorkspace.relationship')}</th>
								<th scope="col">{$t('research.goalWorkspace.applicability')}</th>
								<th scope="col">{$t('research.goalWorkspace.evidence')}</th>
								<th scope="col">{$t('research.goalWorkspace.reviewStatus')}</th>
							</tr>
						</thead>
						<tbody>
							{#each filteredFindings as finding, index (finding.finding_id)}
								<tr>
									<td class="finding-cell">
										<span class="mobile-label">{$t('research.goalWorkspace.finding')}</span>
										<button type="button" on:click={() => openFinding(finding.finding_id)}>
											<small
												>{$t('research.goalWorkspace.findingNumber', { number: index + 1 })}</small
											>
											<strong>{finding.statement}</strong>
											<span>{$t('research.goalWorkspace.openFinding')}</span>
										</button>
									</td>
									<td>
										<span class="mobile-label">{$t('research.goalWorkspace.relationship')}</span>
										<div class="relation-summary">
											<strong>{listLabel(finding.variables)}</strong>
											<span>{directionLabel(finding.direction)}</span>
											<strong>{listLabel(finding.outcomes)}</strong>
											{#if finding.mediators.length}
												<small>
													{$t('research.goalWorkspace.viaMechanism', {
														mechanism: finding.mediators.join(', ')
													})}
												</small>
											{/if}
										</div>
									</td>
									<td>
										<span class="mobile-label">{$t('research.goalWorkspace.applicability')}</span>
										<p class="scope-text">{finding.scope_summary || $t('research.emptyValue')}</p>
									</td>
									<td>
										<span class="mobile-label">{$t('research.goalWorkspace.evidence')}</span>
										<span class={`grade grade--${finding.support_grade}`}>
											{supportGradeLabel(finding.support_grade)}
										</span>
										<small class="evidence-count">
											{$t('research.goalWorkspace.paperEvidenceCount', {
												papers: paperEvidenceRows(finding).length || finding.paper_count,
												evidence: finding.evidence_bundle.direct_result.length
											})}
										</small>
									</td>
									<td>
										<span class="mobile-label">{$t('research.goalWorkspace.reviewStatus')}</span>
										<span class={`review-state review-state--${reviewState(finding)}`}>
											{reviewStateLabel(finding)}
										</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{:else if activeView === 'findings' && selectedFinding}
			<article class="finding-detail">
				<header class="finding-detail__header">
					<div>
						<button class="back-button" type="button" on:click={closeFinding}>
							<span aria-hidden="true">&larr;</span>
							{$t('research.goalWorkspace.backToFindings')}
						</button>
						<p class="eyebrow">{$t('research.goalWorkspace.findingDetail')}</p>
						<h3>{selectedFinding.statement}</h3>
					</div>
					<button class="btn btn--primary" type="button" on:click={() => (reviewOpen = true)}>
						{$t('research.goalWorkspace.review')}
					</button>
				</header>

				<div class="finding-status-line">
					<span class={`review-state review-state--${reviewState(selectedFinding)}`}>
						{reviewStateLabel(selectedFinding)}
					</span>
					<span class={`grade grade--${selectedFinding.support_grade}`}>
						{supportGradeLabel(selectedFinding.support_grade)}
					</span>
					<span>{synthesisStatusLabel(selectedFinding.synthesis_status)}</span>
					<span>
						{$t('research.goalWorkspace.paperCount', {
							count: selectedPaperRows.length || selectedFinding.paper_count
						})}
					</span>
					<span>
						{$t('research.goalWorkspace.directEvidenceCount', {
							count: selectedFinding.evidence_bundle.direct_result.length
						})}
					</span>
				</div>

				<section class="detail-section relationship-section" aria-labelledby="relationship-title">
					<h4 id="relationship-title">{$t('research.goalWorkspace.relationship')}</h4>
					<div class="logic-chain">
						<div class="logic-node">
							<span>{$t('research.goalWorkspace.variables')}</span>
							<strong>{listLabel(selectedFinding.variables)}</strong>
						</div>
						<div class="logic-connector">
							<span aria-hidden="true">&rarr;</span>
							<strong>{directionLabel(selectedFinding.direction)}</strong>
						</div>
						{#if selectedFinding.mediators.length}
							<div class="logic-node logic-node--mechanism">
								<span>{$t('research.goalWorkspace.mediators')}</span>
								<strong>{listLabel(selectedFinding.mediators)}</strong>
							</div>
							<div class="logic-connector logic-connector--arrow" aria-hidden="true">
								<span>&rarr;</span>
							</div>
						{/if}
						<div class="logic-node logic-node--outcome">
							<span>{$t('research.goalWorkspace.outcomes')}</span>
							<strong>{listLabel(selectedFinding.outcomes)}</strong>
						</div>
					</div>
				</section>

				<section class="detail-section" aria-labelledby="applicability-title">
					<h4 id="applicability-title">{$t('research.goalWorkspace.applicability')}</h4>
					<dl class="applicability-list">
						<div>
							<dt>{$t('research.goalWorkspace.scope')}</dt>
							<dd>{selectedFinding.scope_summary || $t('research.emptyValue')}</dd>
						</div>
						{#if selectedFinding.common_conditions.length}
							<div>
								<dt>{$t('research.goalWorkspace.commonConditions')}</dt>
								<dd>{selectedFinding.common_conditions.join('; ')}</dd>
							</div>
						{/if}
						{#if selectedFinding.incomparable_conditions.length}
							<div>
								<dt>{$t('research.goalWorkspace.incomparableConditions')}</dt>
								<dd>{selectedFinding.incomparable_conditions.join('; ')}</dd>
							</div>
						{/if}
					</dl>
				</section>

				<section class="detail-section" aria-labelledby="paper-evidence-title">
					<div class="section-heading">
						<div>
							<h4 id="paper-evidence-title">{$t('research.goalWorkspace.paperEvidence')}</h4>
							<p>{selectedFinding.generalization_note}</p>
						</div>
					</div>
					{#if selectedPaperRows.length}
						<div class="paper-table-wrap">
							<table class="paper-evidence-table">
								<caption>{$t('research.goalWorkspace.paperEvidenceTable')}</caption>
								<thead>
									<tr>
										<th scope="col">{$t('research.goalWorkspace.paper')}</th>
										<th scope="col">{$t('research.goalWorkspace.paperContribution')}</th>
										<th scope="col">{$t('research.goalWorkspace.sourceEvidence')}</th>
									</tr>
								</thead>
								<tbody>
									{#each selectedPaperRows as row (row.key)}
										<tr>
											<td class="paper-title-cell">
												<span class="mobile-label">{$t('research.goalWorkspace.paper')}</span>
												<strong>{row.title}</strong>
												<span>{contributionRoleLabel(row.role)}</span>
											</td>
											<td>
												<span class="mobile-label">
													{$t('research.goalWorkspace.paperContribution')}
												</span>
												<p>{row.statement || $t('research.goalWorkspace.noContributionSummary')}</p>
											</td>
											<td class="source-evidence-cell">
												<span class="mobile-label">
													{$t('research.goalWorkspace.sourceEvidence')}
												</span>
												{#if row.evidence.length}
													{#each row.evidence as evidence (evidence.evidence_ref_id)}
														<article class="source-quote">
															<div class="source-quote__meta">
																<span>
																	{evidenceRoleLabel(selectedFinding, evidence.evidence_ref_id)}
																</span>
																<small>{evidenceMeta(evidence)}</small>
															</div>
															<blockquote>{evidencePreview(evidence)}</blockquote>
															{#if evidenceTextIsLong(evidence)}
																<details class="full-evidence">
																	<summary>{$t('research.goalWorkspace.showFullEvidence')}</summary>
																	<blockquote>{evidenceText(evidence)}</blockquote>
																</details>
															{/if}
															{#if evidenceHref(evidence)}
																<a href={evidenceHref(evidence)}>
																	{$t('research.goalWorkspace.openSource')}
																	<span aria-hidden="true">&rarr;</span>
																</a>
															{/if}
														</article>
													{/each}
												{:else}
													<p>{$t('research.understanding.noFindingEvidence')}</p>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{:else}
						<p class="empty-row">{$t('research.understanding.noFindingEvidence')}</p>
					{/if}
				</section>

				{#if visibleWarnings(selectedFinding).length}
					<section class="detail-section verification-section" aria-labelledby="verification-title">
						<h4 id="verification-title">{$t('research.goalWorkspace.pointsToVerify')}</h4>
						<ul>
							{#each visibleWarnings(selectedFinding) as warning}
								<li>{warning}</li>
							{/each}
						</ul>
					</section>
				{/if}

				{#if selectedCuration || selectedFeedback.length}
					<section class="review-record" aria-labelledby="review-record-title">
						<h4 id="review-record-title">{$t('research.goalWorkspace.expertDecision')}</h4>
						<strong>{reviewStateLabel(selectedFinding)}</strong>
						{#if selectedCuration?.note}
							<p>{selectedCuration.note}</p>
						{:else if selectedFeedback[selectedFeedback.length - 1]?.note}
							<p>{selectedFeedback[selectedFeedback.length - 1].note}</p>
						{/if}
					</section>
				{/if}
			</article>
		{:else}
			<section class="coverage-view" aria-labelledby="coverage-title">
				<header class="coverage-header">
					<div>
						<p class="eyebrow">{$t('research.goalWorkspace.goalCoverage')}</p>
						<h3 id="coverage-title">{$t('research.goalWorkspace.coverageTitle')}</h3>
					</div>
					<div class="coverage-summary">
						<strong>{coveredAxisCount}/{totalAxisCount}</strong>
						<span>{$t('research.goalWorkspace.axesWithEvidence')}</span>
					</div>
				</header>

				<section class="coverage-section">
					<h4>{$t('research.goalWorkspace.variableCoverage')}</h4>
					<table class="coverage-table">
						<thead>
							<tr>
								<th scope="col">{$t('research.goalWorkspace.axis')}</th>
								<th scope="col">{$t('research.goalWorkspace.coverageStatus')}</th>
								<th scope="col">{$t('research.goalWorkspace.linkedFinding')}</th>
							</tr>
						</thead>
						<tbody>
							{#each axisCoverage.variables as item}
								<tr>
									<td><strong>{item.axis}</strong></td>
									<td
										><span class={`coverage-status coverage-status--${item.status}`}
											>{coverageStatusLabel(item)}</span
										></td
									>
									<td>
										{#if item.finding_id && findings.some((finding) => finding.finding_id === item.finding_id)}
											<button type="button" on:click={() => openFinding(item.finding_id)}>
												{findings.find((finding) => finding.finding_id === item.finding_id)
													?.statement}
											</button>
										{:else}
											<span>{$t('research.goalWorkspace.noLinkedFinding')}</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</section>

				<section class="coverage-section">
					<h4>{$t('research.goalWorkspace.outcomeCoverage')}</h4>
					<table class="coverage-table">
						<thead>
							<tr>
								<th scope="col">{$t('research.goalWorkspace.axis')}</th>
								<th scope="col">{$t('research.goalWorkspace.coverageStatus')}</th>
								<th scope="col">{$t('research.goalWorkspace.linkedFinding')}</th>
							</tr>
						</thead>
						<tbody>
							{#each axisCoverage.properties as item}
								<tr>
									<td><strong>{item.axis}</strong></td>
									<td
										><span class={`coverage-status coverage-status--${item.status}`}
											>{coverageStatusLabel(item)}</span
										></td
									>
									<td>
										{#if item.finding_id && findings.some((finding) => finding.finding_id === item.finding_id)}
											<button type="button" on:click={() => openFinding(item.finding_id)}>
												{findings.find((finding) => finding.finding_id === item.finding_id)
													?.statement}
											</button>
										{:else}
											<span>{$t('research.goalWorkspace.noLinkedFinding')}</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</section>
			</section>
		{/if}
	</section>
{/if}

<GoalReviewDialog
	open={reviewOpen}
	{collectionId}
	{scopeType}
	{scopeId}
	finding={selectedBaseFinding ? applyCuration(selectedBaseFinding, selectedCuration) : null}
	evidenceOptions={selectedEvidenceOptions}
	{reviewer}
	acceptBlocked={selectedAcceptBlocked}
	acceptanceChecks={selectedAcceptanceChecks}
	onClose={() => (reviewOpen = false)}
	onSubmitted={reviewSubmitted}
/>

<style>
	.goal-research-workspace,
	.workspace-state {
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
	}

	.goal-research-workspace {
		overflow: hidden;
	}

	.workspace-state {
		padding: 24px;
	}

	.workspace-state h2,
	.workspace-state h3,
	.workspace-state p {
		margin: 0;
	}

	.workspace-state p {
		margin-top: 8px;
		color: var(--text-secondary);
	}

	.workspace-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 24px;
		padding: 22px 24px 18px;
	}

	.eyebrow {
		margin: 0 0 5px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.workspace-header h2,
	.finding-detail h3,
	.coverage-header h3,
	.detail-section h4,
	.coverage-section h4,
	.review-record h4 {
		margin: 0;
		letter-spacing: 0;
	}

	.workspace-header h2 {
		font-size: 20px;
		line-height: 28px;
	}

	.workspace-stats {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 20px;
	}

	.workspace-stats div {
		display: grid;
		min-width: 72px;
		gap: 1px;
	}

	.workspace-stats strong {
		font-size: 18px;
		line-height: 24px;
	}

	.workspace-stats span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.workspace-stats .attention strong {
		color: #b45309;
	}

	.workspace-tabs {
		display: flex;
		gap: 4px;
		border-top: 1px solid var(--border-default);
		border-bottom: 1px solid var(--border-default);
		padding: 0 24px;
		background: var(--bg-subtle);
	}

	.workspace-tabs button {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 46px;
		border: 0;
		border-bottom: 2px solid transparent;
		background: transparent;
		color: var(--text-secondary);
		font: inherit;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.workspace-tabs button.active {
		border-bottom-color: var(--accent);
		color: var(--text-primary);
	}

	.workspace-tabs span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		background: var(--surface-card);
		padding: 0 6px;
		font-size: 11px;
		line-height: 18px;
	}

	.review-load-error {
		margin: 16px 24px 0;
		border: 1px solid rgba(217, 119, 6, 0.32);
		border-radius: var(--radius-md);
		background: rgba(255, 251, 235, 0.9);
		padding: 10px 12px;
		font-size: 13px;
		line-height: 20px;
	}

	.finding-toolbar {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 14px;
		padding: 18px 24px;
	}

	.finding-toolbar label {
		display: grid;
		gap: 5px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.finding-search {
		width: min(440px, 100%);
	}

	.finding-filter {
		width: 180px;
		flex: 0 0 180px;
	}

	.finding-toolbar input,
	.finding-toolbar select {
		width: 100%;
		height: 40px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		padding: 0 11px;
	}

	.findings-table-wrap,
	.paper-table-wrap {
		overflow-x: auto;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
	}

	caption {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}

	th {
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 700;
		line-height: 17px;
		text-align: left;
		text-transform: uppercase;
	}

	th,
	td {
		border-top: 1px solid var(--border-default);
		padding: 13px 12px;
		vertical-align: top;
	}

	.findings-table th:first-child,
	.findings-table td:first-child {
		width: 34%;
		padding-left: 24px;
	}

	.findings-table th:nth-child(2),
	.findings-table td:nth-child(2) {
		width: 20%;
	}

	.findings-table th:nth-child(3),
	.findings-table td:nth-child(3) {
		width: 19%;
	}

	.findings-table th:nth-child(4),
	.findings-table td:nth-child(4) {
		width: 15%;
	}

	.findings-table th:last-child,
	.findings-table td:last-child {
		width: 12%;
		padding-right: 24px;
	}

	.finding-cell button {
		display: grid;
		gap: 4px;
		width: 100%;
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.finding-cell button:hover strong {
		color: var(--accent);
	}

	.finding-cell small {
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 17px;
		text-transform: uppercase;
	}

	.finding-cell strong {
		font-size: 13px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.finding-cell button > span {
		color: var(--accent);
		font-size: 12px;
		font-weight: 600;
		line-height: 18px;
	}

	.relation-summary {
		display: grid;
		gap: 3px;
	}

	.relation-summary strong,
	.relation-summary span,
	.relation-summary small {
		overflow-wrap: anywhere;
	}

	.relation-summary strong {
		font-size: 12px;
		line-height: 18px;
	}

	.relation-summary span {
		color: var(--accent);
		font-size: 11px;
		font-weight: 700;
		line-height: 17px;
		text-transform: uppercase;
	}

	.relation-summary small,
	.scope-text,
	.evidence-count {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.scope-text {
		display: -webkit-box;
		margin: 0;
		overflow: hidden;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 4;
		line-clamp: 4;
		overflow-wrap: anywhere;
	}

	.grade,
	.review-state,
	.coverage-status {
		display: inline-flex;
		align-items: center;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		background: var(--bg-subtle);
		padding: 2px 7px;
		font-size: 11px;
		font-weight: 700;
		line-height: 17px;
	}

	.grade--strong,
	.review-state--accepted,
	.review-state--curated,
	.coverage-status--primary {
		border-color: rgba(5, 150, 105, 0.3);
		background: rgba(236, 253, 245, 0.9);
		color: #047857;
	}

	.grade--partial,
	.grade--weak,
	.review-state--needs_review,
	.review-state--unreviewed,
	.coverage-status--review_queue {
		border-color: rgba(217, 119, 6, 0.3);
		background: rgba(255, 251, 235, 0.9);
		color: #a16207;
	}

	.grade--conflict,
	.grade--insufficient,
	.review-state--rejected {
		border-color: rgba(185, 28, 28, 0.28);
		background: rgba(254, 242, 242, 0.9);
		color: #b91c1c;
	}

	.evidence-count {
		display: block;
		margin-top: 5px;
	}

	.mobile-label {
		display: none;
	}

	.finding-detail,
	.coverage-view {
		display: grid;
		gap: 0;
	}

	.finding-detail__header,
	.coverage-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 24px;
		padding: 22px 24px;
	}

	.finding-detail__header > div {
		min-width: 0;
	}

	.finding-detail h3 {
		max-width: 920px;
		font-size: 18px;
		line-height: 28px;
		overflow-wrap: anywhere;
	}

	.back-button {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin: 0 0 16px;
		border: 0;
		background: transparent;
		color: var(--accent);
		font: inherit;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.finding-status-line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		border-top: 1px solid var(--border-default);
		border-bottom: 1px solid var(--border-default);
		background: var(--bg-subtle);
		padding: 10px 24px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.detail-section,
	.review-record,
	.coverage-section {
		padding: 22px 24px;
		border-bottom: 1px solid var(--border-default);
	}

	.detail-section:last-child,
	.coverage-section:last-child {
		border-bottom: 0;
	}

	.detail-section h4,
	.coverage-section h4,
	.review-record h4 {
		font-size: 14px;
		line-height: 21px;
	}

	.logic-chain {
		display: grid;
		grid-template-columns: minmax(160px, 1fr) minmax(100px, auto) minmax(160px, 1fr) auto minmax(
				160px,
				1fr
			);
		align-items: stretch;
		gap: 10px;
		margin-top: 14px;
	}

	.logic-node {
		display: grid;
		align-content: center;
		gap: 4px;
		min-height: 72px;
		border: 1px solid rgba(37, 99, 235, 0.24);
		border-radius: var(--radius-md);
		background: rgba(239, 246, 255, 0.72);
		padding: 11px 13px;
	}

	.logic-node--mechanism {
		border-color: rgba(8, 145, 178, 0.25);
		background: rgba(236, 254, 255, 0.76);
	}

	.logic-node--outcome {
		border-color: rgba(5, 150, 105, 0.25);
		background: rgba(236, 253, 245, 0.76);
	}

	.logic-node span {
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 17px;
		text-transform: uppercase;
	}

	.logic-node strong {
		font-size: 13px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.logic-connector {
		display: grid;
		place-content: center;
		place-items: center;
		gap: 1px;
		color: var(--accent);
		font-size: 13px;
		text-align: center;
	}

	.logic-connector span {
		font-size: 20px;
		line-height: 22px;
	}

	.logic-connector--arrow {
		min-width: 28px;
	}

	.applicability-list {
		display: grid;
		gap: 0;
		margin: 12px 0 0;
	}

	.applicability-list div {
		display: grid;
		grid-template-columns: 180px minmax(0, 1fr);
		gap: 16px;
		border-top: 1px solid var(--border-default);
		padding: 11px 0;
	}

	.applicability-list dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 600;
		line-height: 19px;
	}

	.applicability-list dd {
		margin: 0;
		font-size: 13px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.section-heading p {
		max-width: 900px;
		margin: 5px 0 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 21px;
	}

	.paper-evidence-table {
		margin-top: 14px;
		border: 1px solid var(--border-default);
	}

	.paper-evidence-table th:first-child,
	.paper-evidence-table td:first-child {
		width: 23%;
	}

	.paper-evidence-table th:nth-child(2),
	.paper-evidence-table td:nth-child(2) {
		width: 27%;
	}

	.paper-evidence-table th:nth-child(3),
	.paper-evidence-table td:nth-child(3) {
		width: 50%;
	}

	.paper-title-cell strong,
	.paper-title-cell span {
		display: block;
		overflow-wrap: anywhere;
	}

	.paper-title-cell strong {
		font-size: 13px;
		line-height: 20px;
	}

	.paper-title-cell span {
		margin-top: 5px;
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 700;
		line-height: 17px;
		text-transform: uppercase;
	}

	.paper-evidence-table td > p,
	.empty-row {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 21px;
		overflow-wrap: anywhere;
	}

	.source-evidence-cell {
		display: grid;
		gap: 12px;
	}

	.source-quote {
		display: grid;
		gap: 7px;
		border-bottom: 1px solid var(--border-default);
		padding-bottom: 12px;
	}

	.source-quote:last-child {
		border-bottom: 0;
		padding-bottom: 0;
	}

	.source-quote__meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
	}

	.source-quote__meta span {
		color: #047857;
		font-size: 11px;
		font-weight: 700;
		line-height: 17px;
	}

	.source-quote__meta small {
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 17px;
	}

	.source-quote blockquote {
		margin: 0;
		border-left: 2px solid rgba(5, 150, 105, 0.32);
		padding-left: 10px;
		font-size: 13px;
		line-height: 21px;
		overflow-wrap: anywhere;
	}

	.source-quote a {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		width: fit-content;
		color: var(--accent);
		font-size: 12px;
		font-weight: 600;
		line-height: 18px;
		text-decoration: none;
	}

	.full-evidence summary {
		width: fit-content;
		color: var(--accent);
		font-size: 12px;
		font-weight: 600;
		line-height: 18px;
		cursor: pointer;
	}

	.full-evidence blockquote {
		margin-top: 8px;
	}

	.verification-section ul {
		margin: 10px 0 0;
		padding-left: 20px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 21px;
	}

	.review-record {
		display: grid;
		gap: 6px;
		background: rgba(236, 253, 245, 0.54);
	}

	.review-record strong {
		color: #047857;
		font-size: 13px;
	}

	.review-record p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 21px;
	}

	.coverage-header {
		align-items: center;
	}

	.coverage-header h3 {
		font-size: 18px;
		line-height: 26px;
	}

	.coverage-summary {
		display: grid;
		min-width: 112px;
		gap: 2px;
		text-align: right;
	}

	.coverage-summary strong {
		font-size: 20px;
		line-height: 26px;
	}

	.coverage-summary span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.coverage-table {
		margin-top: 12px;
		border: 1px solid var(--border-default);
	}

	.coverage-table th:first-child,
	.coverage-table td:first-child {
		width: 24%;
	}

	.coverage-table th:nth-child(2),
	.coverage-table td:nth-child(2) {
		width: 22%;
	}

	.coverage-table td {
		font-size: 13px;
		line-height: 20px;
	}

	.coverage-table button {
		max-width: 100%;
		border: 0;
		background: transparent;
		color: var(--accent);
		font: inherit;
		font-size: 13px;
		line-height: 20px;
		text-align: left;
		cursor: pointer;
		overflow-wrap: anywhere;
	}

	.coverage-table td > span:not(.coverage-status) {
		color: var(--text-secondary);
	}

	.coverage-status--missing {
		border-color: rgba(100, 116, 139, 0.28);
		background: rgba(248, 250, 252, 0.9);
		color: var(--text-secondary);
	}

	.coverage-status--mechanism,
	.coverage-status--context {
		border-color: rgba(8, 145, 178, 0.28);
		background: rgba(236, 254, 255, 0.8);
		color: #0e7490;
	}

	@media (max-width: 900px) {
		.workspace-header,
		.finding-detail__header,
		.coverage-header {
			align-items: stretch;
			flex-direction: column;
		}

		.workspace-stats {
			justify-content: flex-start;
		}

		.logic-chain {
			grid-template-columns: 1fr;
		}

		.logic-connector {
			min-height: 38px;
			transform: rotate(90deg);
		}

		.logic-connector strong {
			transform: rotate(-90deg);
		}

		.coverage-summary {
			text-align: left;
		}
	}

	@media (max-width: 760px) {
		.workspace-header,
		.finding-toolbar,
		.finding-detail__header,
		.detail-section,
		.review-record,
		.coverage-header,
		.coverage-section {
			padding-left: 16px;
			padding-right: 16px;
		}

		.workspace-tabs {
			padding: 0 16px;
		}

		.finding-toolbar {
			align-items: stretch;
			flex-direction: column;
		}

		.finding-search,
		.finding-filter {
			width: 100%;
			flex: auto;
		}

		.findings-table,
		.findings-table tbody,
		.findings-table tr,
		.findings-table td,
		.paper-evidence-table,
		.paper-evidence-table tbody,
		.paper-evidence-table tr,
		.paper-evidence-table td {
			display: block;
			width: 100% !important;
		}

		.findings-table thead,
		.paper-evidence-table thead {
			display: none;
		}

		.findings-table tr,
		.paper-evidence-table tr {
			border-top: 1px solid var(--border-default);
			padding: 10px 16px;
		}

		.findings-table td,
		.findings-table td:first-child,
		.findings-table td:last-child,
		.paper-evidence-table td {
			border: 0;
			padding: 8px 0;
		}

		.mobile-label {
			display: block;
			margin-bottom: 4px;
			color: var(--text-secondary);
			font-size: 10px;
			font-weight: 700;
			line-height: 16px;
			text-transform: uppercase;
		}

		.paper-evidence-table {
			border-right: 0;
			border-left: 0;
		}

		.applicability-list div {
			grid-template-columns: 1fr;
			gap: 4px;
		}

		.coverage-table {
			table-layout: auto;
			min-width: 620px;
		}
	}
</style>
