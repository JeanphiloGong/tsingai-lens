<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import ResearchUnderstandingWorkbench from '../../_components/ResearchUnderstandingWorkbench.svelte';
	import { errorMessage, isHttpStatusError } from '../../../../_shared/api';
	import {
		fetchExperimentPlans,
		updateExperimentPlan,
		type ExperimentPlan,
		type ExperimentPlanStatus
	} from '../../../../_shared/experimentPlans';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchGoalAnalysis,
		runGoalAnalysis,
		type GoalAnalysis,
		type GoalAnalysisProgress
	} from '../../../../_shared/researchView';

	const POLL_DELAY_MS = 2500;
	type WorkbenchInitialFocus = '' | 'review_queue' | 'training_ready';

	let analysis: GoalAnalysis | null = null;
	let loading = false;
	let running = false;
	let plans: ExperimentPlan[] = [];
	let selectedPlanId = '';
	let planTitle = '';
	let planContent = '';
	let planStatus: ExperimentPlanStatus = 'draft';
	let plansLoading = false;
	let planSaving = false;
	let error = '';
	let planError = '';
	let loadedKey = '';
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	$: collectionId = $page.params.id ?? '';
	$: goalId = $page.params.goal_id ?? '';
	$: requestedPlanId = $page.url.searchParams.get('plan_id') ?? '';
	$: loadKey = `${collectionId}:${goalId}`;
	$: goal = analysis?.goal ?? null;
	$: understanding = analysis?.understanding ?? null;
	$: workbenchInitialFocus = (
		$page.url.searchParams.get('review') === 'queue'
			? 'review_queue'
			: $page.url.searchParams.get('review') === 'training_ready'
				? 'training_ready'
				: ''
	) as WorkbenchInitialFocus;
	$: workbenchInitialFindingId = $page.url.searchParams.get('finding_id') ?? '';
	$: progress = goal?.analysis_progress ?? null;
	$: isAnalysisRunning = goal?.status === 'running';
	$: analysisErrors = analysis?.errors ?? [];
	$: analysisWarnings = analysis?.warnings ?? [];
	$: hasAnalysisErrors = analysisErrors.length > 0;
	$: hasAnalysisWarnings = analysisWarnings.length > 0;
	$: hasReviewableUnderstanding =
		((understanding?.presentation?.primary_findings?.length ?? 0) > 0 ||
			(understanding?.presentation?.review_queue_findings?.length ?? 0) > 0);
	$: progressPercent = progressPercentLabel(progress);
	$: currentDocumentLabel = progressDocumentLabel(progress);
	$: selectedPlan = plans.find((plan) => plan.plan_id === selectedPlanId) ?? null;
	$: selectedPlanEditWarning = experimentPlanEditWarning(selectedPlan, planContent);
	$: selectedPlanSourceWarning = experimentPlanSourceWarning(selectedPlan);
	$: selectedPlanCanEnterReview = canEnterReview(selectedPlan);
	$: canSaveSelectedPlan = Boolean(
		selectedPlan &&
			planTitle.trim() &&
			planContent.trim() &&
			!selectedPlanEditWarning &&
			(planStatus !== 'ready_for_review' || selectedPlanCanEnterReview)
	);
	$: if (browser && collectionId && goalId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		clearPoll();
		void loadAnalysis();
	}

	onDestroy(() => {
		clearPoll();
	});

	async function loadAnalysis() {
		loading = true;
		error = '';
		try {
			analysis = await fetchGoalAnalysis(collectionId, goalId);
			void loadPlans();
			schedulePollIfRunning();
		} catch (err) {
			analysis = null;
			error = errorMessage(err);
			clearPoll();
		} finally {
			loading = false;
		}
	}

	async function loadPlans() {
		plansLoading = true;
		planError = '';
		try {
			const response = await fetchExperimentPlans(collectionId, goalId);
			plans = response.items;
			const requestedPlan = requestedPlanId
				? (plans.find((plan) => plan.plan_id === requestedPlanId) ?? null)
				: null;
			if (requestedPlan) {
				selectPlan(requestedPlan);
			} else if (!selectedPlanId || !plans.some((plan) => plan.plan_id === selectedPlanId)) {
				selectPlan(plans[0] ?? null);
			}
		} catch (err) {
			plans = [];
			selectPlan(null);
			planError = experimentPlanLoadError(err);
		} finally {
			plansLoading = false;
		}
	}

	function experimentPlanLoadError(err: unknown) {
		if (isHttpStatusError(err, 404)) {
			return $t('research.goalWorkspace.experimentPlansUnavailable');
		}
		return errorMessage(err);
	}

	function selectPlan(plan: ExperimentPlan | null) {
		selectedPlanId = plan?.plan_id ?? '';
		planTitle = plan?.title ?? '';
		planContent = plan?.content ?? '';
		planStatus = plan?.status ?? 'draft';
	}

	async function savePlanEdits() {
		if (!canSaveSelectedPlan || !selectedPlan) return;
		planSaving = true;
		planError = '';
		try {
			const updated = await updateExperimentPlan(collectionId, goalId, selectedPlan.plan_id, {
				title: planTitle.trim(),
				content: planContent.trim(),
				status: planStatus
			});
			plans = plans.map((plan) => (plan.plan_id === updated.plan_id ? updated : plan));
			selectPlan(updated);
		} catch (err) {
			planError = errorMessage(err);
		} finally {
			planSaving = false;
		}
	}

	async function rerunAnalysis() {
		running = true;
		error = '';
		try {
			analysis = await runGoalAnalysis(collectionId, goalId);
			schedulePollIfRunning();
		} catch (err) {
			error = errorMessage(err);
			clearPoll();
		} finally {
			running = false;
		}
	}

	function clearPoll() {
		if (pollTimer) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
	}

	function schedulePollIfRunning() {
		clearPoll();
		if (!browser || analysis?.goal.status !== 'running') return;
		pollTimer = setTimeout(() => {
			void refreshAnalysis();
		}, POLL_DELAY_MS);
	}

	async function refreshAnalysis() {
		try {
			analysis = await fetchGoalAnalysis(collectionId, goalId);
			error = '';
			schedulePollIfRunning();
		} catch (err) {
			error = errorMessage(err);
			clearPoll();
		}
	}

	function statusLabel(status: string | null | undefined) {
		if (!status) return $t('research.emptyValue');
		return status.replace(/_/g, ' ');
	}

	function metadataText(plan: ExperimentPlan | null, key: string) {
		const value = plan?.metadata?.[key];
		return typeof value === 'string' ? value : '';
	}

	function metadataList(plan: ExperimentPlan | null, key: string) {
		const value = plan?.metadata?.[key];
		return Array.isArray(value)
			? value.map((item) => String(item).trim()).filter(Boolean)
			: [];
	}

	function reviewGateLabel(value: string) {
		if (value === 'protocol_ready_findings') {
			return $t('research.goalWorkspace.experimentPlanProtocolReadyGate');
		}
		return statusLabel(value);
	}

	function selectedPlanReviewGateLabel(plan: ExperimentPlan | null) {
		const gate = metadataText(plan, 'review_gate');
		return gate ? reviewGateLabel(gate) : $t('research.goalWorkspace.experimentPlanNoReviewGate');
	}

	function planSourceLabel(plan: ExperimentPlan | null) {
		return isCopilotPlan(plan)
			? $t('research.goalWorkspace.experimentPlanCopilotSource')
			: $t('research.goalWorkspace.experimentPlanManualSource');
	}

	function sourceValidity(plan: ExperimentPlan | null) {
		if (!isCopilotPlan(plan)) return '';
		const value = metadataText(plan, 'source_validity');
		return value === 'current' || value === 'stale' ? value : 'unverified';
	}

	function sourceValidityLabel(plan: ExperimentPlan | null) {
		const value = sourceValidity(plan);
		if (value === 'current') {
			return $t('research.goalWorkspace.experimentPlanSourceCurrent');
		}
		if (value === 'stale') {
			return $t('research.goalWorkspace.experimentPlanSourceStale');
		}
		return $t('research.goalWorkspace.experimentPlanSourceUnverified');
	}

	function experimentPlanSourceWarning(plan: ExperimentPlan | null) {
		const value = sourceValidity(plan);
		if (value === 'stale') {
			return $t('research.goalWorkspace.experimentPlanSourceStaleWarning');
		}
		if (value === 'unverified') {
			return $t('research.goalWorkspace.experimentPlanSourceUnverifiedWarning');
		}
		return '';
	}

	function canEnterReview(plan: ExperimentPlan | null) {
		return !isCopilotPlan(plan) || sourceValidity(plan) === 'current';
	}

	function sourceModeLabel(value: string) {
		if (value === 'collection_grounded') {
			return $t('research.goalWorkspace.experimentPlanCollectionGrounded');
		}
		return statusLabel(value);
	}

	function isCopilotPlan(plan: ExperimentPlan | null) {
		return Boolean(
			plan?.source_message_id ||
				metadataText(plan, 'source') === 'goal_copilot' ||
				metadataText(plan, 'review_gate') === 'protocol_ready_findings'
		);
	}

	function hasProtocolDraftStructure(content: string) {
		const text = content.toLowerCase();
		return [
			['hypothesis', '假设'],
			['variable matrix', '变量矩阵', '变量'],
			['measurement', 'measurements', '表征', '测试指标', '测量'],
			['control', 'controls', '对照'],
			['risk', 'risks', 'limit', 'limits', '风险', '限制']
		].every((terms) => terms.some((term) => text.includes(term)));
	}

	function sourceLabels(plan: ExperimentPlan | null) {
		return (plan?.source_links ?? []).map((link) => link.label.trim()).filter(Boolean);
	}

	function experimentPlanEditWarning(plan: ExperimentPlan | null, content: string) {
		if (!isCopilotPlan(plan) || !content.trim()) return '';
		if (!hasProtocolDraftStructure(content)) {
			return $t('research.goalWorkspace.experimentPlanProtocolStructureRequired');
		}
		const labels = sourceLabels(plan);
		if (labels.length && !labels.some((label) => content.includes(label))) {
			return $t('research.goalWorkspace.experimentPlanSourceLabelRequired');
		}
		return '';
	}

	function progressDocumentLabel(value: GoalAnalysisProgress | null) {
		return (
			value?.active_document_title ||
			value?.active_source_filename ||
			$t('research.goalWorkspace.waitingDocument')
		);
	}

	function progressPercentLabel(value: GoalAnalysisProgress | null) {
		if (!value?.current || !value.total || value.total <= 0) return '';
		return `${value.current}/${value.total} ${value.unit ?? ''}`.trim();
	}
</script>

<svelte:head>
	<title>{goal?.question ?? goalId}</title>
</svelte:head>

<section class="goal-page fade-up">
	<nav class="breadcrumb" aria-label="Breadcrumb">
		<a href={resolve('/collections/[id]/objectives', { id: collectionId })}>
			{$t('research.objectiveWorkspace.back')}
		</a>
		<span>{goal?.question ?? goalId}</span>
	</nav>

	<header class="goal-header">
		<div>
			<p class="eyebrow">{$t('research.goalWorkspace.eyebrow')}</p>
			<h2>{goal?.question ?? goalId}</h2>
			{#if goal}
				<div class="goal-meta">
					<span>{statusLabel(goal.status)}</span>
				</div>
			{/if}
		</div>
		<div class="goal-actions">
			<a
				class="btn btn--ghost btn--small"
				href={`${resolve('/collections/[id]/assistant', {
					id: collectionId
				})}?goal_id=${encodeURIComponent(goalId)}`}
			>
				{$t('research.goalWorkspace.askCopilot')}
			</a>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadAnalysis}>
				{$t('research.objectives.refresh')}
			</button>
			<button
				class="btn btn--primary btn--small"
				type="button"
				disabled={running || isAnalysisRunning}
				on:click={rerunAnalysis}
			>
				{running || isAnalysisRunning
					? $t('research.objectives.analyzing')
					: $t('research.objectives.confirmAndAnalyze')}
			</button>
		</div>
	</header>

	{#if loading}
		<section class="goal-state" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.objectiveWorkspace.loading')}</div>
		</section>
	{:else if error}
		<section class="goal-state goal-state--error" role="alert">
			<h3>{$t('research.objectives.analysisErrorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if !analysis}
		<section class="goal-state">
			<h3>{$t('research.objectiveWorkspace.emptyTitle')}</h3>
			<p>{$t('research.objectiveWorkspace.emptyBody')}</p>
		</section>
	{:else}
		{#if hasAnalysisErrors}
			<section class="goal-state goal-state--error" role="alert">
				<h3>{$t('research.objectives.analysisErrorTitle')}</h3>
				{#each analysisErrors as item}
					<p>{item}</p>
				{/each}
			</section>
		{/if}
		{#if !hasAnalysisErrors && hasAnalysisWarnings}
			<section class="goal-state goal-state--warning" role="status">
				<h3>{$t('research.objectives.analysisWarningTitle')}</h3>
				{#each analysisWarnings as item}
					<p>{item}</p>
				{/each}
			</section>
		{/if}
		{#if isAnalysisRunning}
			<section class="goal-progress" aria-live="polite" aria-busy="true">
				<div>
					<p class="goal-progress__eyebrow">{$t('research.goalWorkspace.progressEyebrow')}</p>
					<h3>{$t('research.goalWorkspace.progressTitle')}</h3>
					<p>{progress?.message ?? $t('research.goalWorkspace.progressBody')}</p>
				</div>
				<div class="goal-progress__grid">
					<div>
						<span>{$t('research.goalWorkspace.phase')}</span>
						<strong>{statusLabel(progress?.phase ?? 'running')}</strong>
					</div>
					<div>
						<span>{$t('research.goalWorkspace.currentDocument')}</span>
						<strong>{currentDocumentLabel}</strong>
					</div>
					{#if progressPercent}
						<div>
							<span>{$t('research.goalWorkspace.stepProgress')}</span>
							<strong>{progressPercent}</strong>
						</div>
					{/if}
				</div>
			</section>
		{/if}
		{#if !hasAnalysisErrors || hasReviewableUnderstanding}
			<ResearchUnderstandingWorkbench
				{understanding}
				{collectionId}
				returnTo={resolve('/collections/[id]/goals/[goal_id]', {
					id: collectionId,
					goal_id: goalId
				})}
				initialFocus={workbenchInitialFocus}
				initialFindingId={workbenchInitialFindingId}
				bodyKey="research.understanding.objectiveBody"
				titleId="goal-understanding-title"
			/>
		{/if}
		<section class="experiment-plans" aria-labelledby="experiment-plans-title">
			<div class="experiment-plans__header">
				<div>
					<p class="eyebrow">{$t('research.goalWorkspace.experimentPlansEyebrow')}</p>
					<h3 id="experiment-plans-title">{$t('research.goalWorkspace.experimentPlansTitle')}</h3>
				</div>
				<button class="btn btn--ghost btn--small" type="button" on:click={loadPlans}>
					{$t('research.objectives.refresh')}
				</button>
			</div>
			{#if plansLoading}
				<p class="experiment-plans__state">{$t('research.goalWorkspace.experimentPlansLoading')}</p>
			{:else if planError}
				<p class="experiment-plans__state experiment-plans__state--error">{planError}</p>
			{:else if !plans.length}
				<p class="experiment-plans__state">{$t('research.goalWorkspace.experimentPlansEmpty')}</p>
			{:else}
				<div class="experiment-plans__grid">
					<div class="experiment-plans__list" aria-label={$t('research.goalWorkspace.experimentPlansList')}>
						{#each plans as plan}
							<button
								type="button"
								class:active={plan.plan_id === selectedPlanId}
								on:click={() => selectPlan(plan)}
							>
								<strong>{plan.title}</strong>
								<span>{statusLabel(plan.status)}</span>
								<small>
									{planSourceLabel(plan)}{#if isCopilotPlan(plan)} · {sourceValidityLabel(plan)}{/if}
								</small>
							</button>
						{/each}
					</div>
					<form class="experiment-plans__editor" on:submit|preventDefault={savePlanEdits}>
						{#if selectedPlanSourceWarning}
							<p class="experiment-plans__source-warning" role="alert">
								{selectedPlanSourceWarning}
							</p>
						{/if}
						<label>
							<span>{$t('research.goalWorkspace.experimentPlanTitle')}</span>
							<input id="experiment-plan-title" name="experiment_plan_title" bind:value={planTitle} />
						</label>
						<label>
							<span>{$t('research.goalWorkspace.experimentPlanStatus')}</span>
							<select
								id="experiment-plan-status"
								name="experiment_plan_status"
								bind:value={planStatus}
							>
								<option value="draft">{$t('research.goalWorkspace.experimentPlanDraft')}</option>
								<option value="ready_for_review" disabled={!selectedPlanCanEnterReview}>
									{$t('research.goalWorkspace.experimentPlanReady')}
								</option>
								<option value="archived">{$t('research.goalWorkspace.experimentPlanArchived')}</option>
							</select>
						</label>
						<label class="experiment-plans__content">
							<span>{$t('research.goalWorkspace.experimentPlanContent')}</span>
							<textarea
								id="experiment-plan-content"
								name="experiment_plan_content"
								rows="12"
								bind:value={planContent}
							></textarea>
						</label>
						{#if selectedPlanEditWarning}
							<p class="experiment-plans__edit-warning" role="status">{selectedPlanEditWarning}</p>
						{/if}
						{#if selectedPlan}
							<div
								class="experiment-plans__provenance"
								aria-label={$t('research.goalWorkspace.experimentPlanProvenance')}
							>
								<div>
									<strong>
										{planSourceLabel(selectedPlan)}
									</strong>
									{#if isCopilotPlan(selectedPlan)}
										<span>{sourceValidityLabel(selectedPlan)}</span>
									{/if}
									<span>{selectedPlanReviewGateLabel(selectedPlan)}</span>
								</div>
								<div class="experiment-plans__provenance-meta">
									{#if metadataText(selectedPlan, 'source_mode')}
										<span>{sourceModeLabel(metadataText(selectedPlan, 'source_mode'))}</span>
									{/if}
									{#if metadataList(selectedPlan, 'used_evidence_ids').length}
										<span>
											{$t('research.goalWorkspace.experimentPlanEvidenceCount', {
												count: metadataList(selectedPlan, 'used_evidence_ids').length
											})}
										</span>
									{/if}
								</div>
								{#if selectedPlan.source_links.length}
									<div class="experiment-plans__source-links">
										<strong>{$t('research.goalWorkspace.experimentPlanSources')}</strong>
										<div>
											{#each selectedPlan.source_links as link}
												<a href={link.href}>{link.label}</a>
											{/each}
										</div>
									</div>
								{/if}
							</div>
						{/if}
						<div class="experiment-plans__footer">
							<button
								class="btn btn--primary btn--small"
								type="submit"
								disabled={planSaving || !canSaveSelectedPlan}
							>
								{planSaving
									? $t('research.goalWorkspace.experimentPlanSaving')
									: $t('research.goalWorkspace.experimentPlanSave')}
							</button>
						</div>
					</form>
				</div>
			{/if}
		</section>
	{/if}
</section>

<style>
	.goal-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 18px;
	}

	.breadcrumb {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.breadcrumb a {
		flex: 0 0 auto;
		color: var(--accent);
		text-decoration: none;
	}

	.breadcrumb span {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.goal-header,
	.goal-state,
	.goal-progress,
	.experiment-plans {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.goal-header {
		display: grid;
		gap: 12px;
		padding: 16px 18px;
	}

	.eyebrow {
		margin: 0 0 6px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.goal-header h2,
	.goal-state h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.goal-header h2 {
		max-width: 1120px;
		font-size: 20px;
		line-height: 28px;
		overflow-wrap: anywhere;
	}

	.goal-meta,
	.goal-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}

	.goal-meta {
		margin-top: 6px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
		text-transform: capitalize;
	}

	.goal-state {
		padding: 24px;
	}

	.goal-state p {
		margin: 8px 0 0;
		color: var(--text-secondary);
	}

	.goal-progress {
		display: grid;
		gap: 18px;
		padding: 22px 24px;
	}

	.goal-progress__eyebrow {
		margin: 0 0 6px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.goal-progress h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		line-height: 26px;
	}

	.goal-progress p {
		margin: 8px 0 0;
		color: var(--text-secondary);
	}

	.goal-progress__grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
	}

	.goal-progress__grid div {
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--bg-subtle);
	}

	.goal-progress__grid span,
	.goal-progress__grid strong {
		display: block;
	}

	.experiment-plans {
		display: grid;
		gap: 16px;
		padding: 22px 24px;
	}

	.experiment-plans__header,
	.experiment-plans__footer {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.experiment-plans h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		line-height: 26px;
	}

	.experiment-plans__state {
		margin: 0;
		color: var(--text-secondary);
		line-height: 22px;
	}

	.experiment-plans__state--error {
		color: var(--danger);
	}

	.experiment-plans__grid {
		display: grid;
		grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
		gap: 16px;
	}

	.experiment-plans__list {
		display: grid;
		align-content: start;
		gap: 8px;
	}

	.experiment-plans__list button {
		display: grid;
		gap: 4px;
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
		padding: 12px;
		text-align: left;
		cursor: pointer;
	}

	.experiment-plans__list button.active,
	.experiment-plans__list button:hover {
		border-color: var(--accent);
		background: var(--bg-subtle);
	}

	.experiment-plans__list strong,
	.experiment-plans__list span {
		overflow-wrap: anywhere;
	}

	.experiment-plans__list strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.experiment-plans__list span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: capitalize;
	}

	.experiment-plans__editor {
		display: grid;
		gap: 12px;
	}

	.experiment-plans__editor label {
		display: grid;
		gap: 6px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.experiment-plans__editor input,
	.experiment-plans__editor select,
	.experiment-plans__editor textarea {
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		line-height: 22px;
		padding: 10px 12px;
	}

	.experiment-plans__editor textarea {
		min-height: 220px;
		resize: vertical;
	}

	.experiment-plans__edit-warning {
		margin: 0;
		border: 1px solid rgba(217, 119, 6, 0.32);
		border-radius: var(--radius-md);
		background: rgba(255, 251, 235, 0.86);
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
		padding: 10px 12px;
	}

	.experiment-plans__source-warning {
		margin: 0;
		border: 1px solid rgba(185, 28, 28, 0.35);
		border-radius: var(--radius-md);
		background: rgba(254, 242, 242, 0.92);
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
		padding: 10px 12px;
	}

	.experiment-plans__provenance {
		display: grid;
		gap: 10px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-subtle);
		padding: 12px;
	}

	.experiment-plans__provenance div {
		display: grid;
		gap: 4px;
	}

	.experiment-plans__provenance strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
	}

	.experiment-plans__provenance span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		overflow-wrap: anywhere;
	}

	.experiment-plans__provenance .experiment-plans__provenance-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.experiment-plans__provenance-meta span {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		background: var(--surface-card);
		padding: 4px 7px;
	}

	.experiment-plans__source-links > div {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.experiment-plans__source-links a {
		display: inline-flex;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		background: var(--surface-card);
		color: var(--accent);
		font-size: 12px;
		line-height: 18px;
		padding: 4px 8px;
		text-decoration: none;
	}

	.experiment-plans__source-links a:hover {
		border-color: var(--accent);
	}

	.goal-progress__grid span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.goal-progress__grid strong {
		margin-top: 4px;
		overflow-wrap: anywhere;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.goal-state--error {
		border-color: rgba(185, 28, 28, 0.28);
		background: rgba(254, 242, 242, 0.72);
	}

	.goal-state--warning {
		border-color: rgba(217, 119, 6, 0.32);
		background: rgba(255, 251, 235, 0.86);
	}

	@media (max-width: 760px) {
		.goal-progress__grid {
			grid-template-columns: 1fr;
		}

		.experiment-plans__grid {
			grid-template-columns: 1fr;
		}
	}
</style>
