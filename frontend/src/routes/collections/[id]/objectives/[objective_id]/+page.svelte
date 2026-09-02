<script lang="ts">
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import FindingAuthoringEditor from '../../_components/FindingAuthoringEditor.svelte';
	import EvidenceAuthoringEditor from '../../_components/EvidenceAuthoringEditor.svelte';
	import FindingWorkbench from '../../_components/FindingWorkbench.svelte';
	import { errorMessage } from '../../../../_shared/api';
	import { fetchDocumentProfiles } from '../../../../_shared/documents';
	import {
		fetchObjectiveAnalysis,
		fetchObjectiveEvidence,
		fetchObjectiveFindings,
		runObjectiveAnalysis,
		type ObjectiveAnalysis,
		type ObjectiveEvidence,
		type ObjectiveFinding,
		type FindingAuthoringResult
	} from '../../../../_shared/researchView';

	const POLL_DELAY_MS = 2500;
	let analysis: ObjectiveAnalysis | null = null;
	let findings: ObjectiveFinding[] = [];
	let evidence: ObjectiveEvidence[] = [];
	let documentTitles: Record<string, string> = {};
	let selectedFinding: ObjectiveFinding | null = null;
	let selectedFindingId = '';
	let loading = false;
	let findingLoading = false;
	let actionRunning = false;
	let error = '';
	let actionError = '';
	let findingError = '';
	let loadedKey = '';
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let findingRequestSequence = 0;
	let authoringRequestSequence = 0;
	let authoringOpen = false;
	let authoringLoading = false;
	let authoringError = '';
	let authoringEvidence: ObjectiveEvidence[] = [];
	let authoringEvidenceVersion: number | null = null;
	let authoringParent: ObjectiveFinding | null = null;
	let evidenceAuthoringOpen = false;
	let evidenceAuthoringSource: ObjectiveEvidence | null = null;
	let evidenceAuthoringMode: 'create' | 'revise' = 'create';

	$: collectionId = $page.params.id ?? '';
	$: objectiveId = $page.params.objective_id ?? '';
	$: currentUrl = $page.url;
	$: requestedFindingId = $page.url.searchParams.get('finding_id') ?? '';
	$: active = analysis?.active_analysis ?? null;
	$: published = analysis?.published_analysis ?? null;
	$: isProcessing = active?.status === 'queued' || active?.status === 'running';
	$: if (browser && collectionId && objectiveId && `${collectionId}:${objectiveId}` !== loadedKey) {
		loadedKey = `${collectionId}:${objectiveId}`;
		void loadObjective();
	}

	onDestroy(clearPoll);

	async function loadObjective(preferredFindingId = '', updateFindingUrl = false) {
		findingRequestSequence += 1;
		loading = true;
		error = '';
		clearPoll();
		try {
			const [objectiveResult, profilesResult] = await Promise.allSettled([
				fetchObjectiveAnalysis(collectionId, objectiveId),
				fetchDocumentProfiles(collectionId)
			]);
			if (objectiveResult.status === 'rejected') throw objectiveResult.reason;
			analysis = objectiveResult.value;
			documentTitles =
				profilesResult.status === 'fulfilled'
					? Object.fromEntries(
							profilesResult.value.items.map((item) => [
								item.document_id,
								item.title || item.source_filename || ''
							])
						)
					: {};
			await loadFindings(preferredFindingId, updateFindingUrl);
			schedulePoll();
		} catch (err) {
			error = errorMessage(err);
			analysis = null;
			findings = [];
			evidence = [];
			selectedFinding = null;
			documentTitles = {};
		} finally {
			loading = false;
		}
	}

	async function loadFindings(preferredFindingId = '', updateFindingUrl = false) {
		if (!analysis?.objective.published_analysis_version) {
			findingRequestSequence += 1;
			findings = [];
			evidence = [];
			selectedFinding = null;
			selectedFindingId = '';
			return;
		}
		const analysisVersion = analysis.objective.published_analysis_version;
		const loadedFindings: ObjectiveFinding[] = [];
		while (true) {
			const page = await fetchObjectiveFindings(
				collectionId,
				objectiveId,
				analysisVersion,
				loadedFindings.length,
				200
			);
			loadedFindings.push(...page.items);
			if (loadedFindings.length >= page.total) break;
			if (!page.items.length) throw new Error('Finding 分页结果不完整。');
		}
		findings = loadedFindings;
		const nextId =
			(preferredFindingId && findings.some((item) => item.finding_id === preferredFindingId)
				? preferredFindingId
				: requestedFindingId && findings.some((item) => item.finding_id === requestedFindingId)
					? requestedFindingId
					: selectedFindingId && findings.some((item) => item.finding_id === selectedFindingId)
						? selectedFindingId
						: findings[0]?.finding_id) ?? '';
		await selectFinding(nextId, updateFindingUrl && Boolean(nextId));
	}

	async function openAuthoring(parent: ObjectiveFinding | null = null) {
		if (!published) return;
		authoringOpen = true;
		authoringParent = parent;
		authoringError = '';
		const version = published.analysis_version;
		if (authoringEvidenceVersion === version && authoringEvidence.length) return;
		const requestSequence = ++authoringRequestSequence;
		authoringLoading = true;
		try {
			const records: ObjectiveEvidence[] = [];
			while (true) {
				const page = await fetchObjectiveEvidence(
					collectionId,
					objectiveId,
					version,
					null,
					records.length,
					500
				);
				records.push(...page.items);
				if (records.length >= page.total) break;
				if (!page.items.length) throw new Error('Evidence 分页结果不完整。');
			}
			if (requestSequence !== authoringRequestSequence) return;
			authoringEvidence = records;
			authoringEvidenceVersion = version;
		} catch (err) {
			if (requestSequence === authoringRequestSequence) authoringError = errorMessage(err);
		} finally {
			if (requestSequence === authoringRequestSequence) authoringLoading = false;
		}
	}

	function closeAuthoring() {
		authoringRequestSequence += 1;
		authoringOpen = false;
		authoringParent = null;
		authoringError = '';
		authoringLoading = false;
	}

	function openEvidenceAuthoring(item: ObjectiveEvidence, mode: 'create' | 'revise') {
		closeAuthoring();
		evidenceAuthoringOpen = true;
		evidenceAuthoringSource = item;
		evidenceAuthoringMode = mode;
	}

	function closeEvidenceAuthoring() {
		evidenceAuthoringOpen = false;
		evidenceAuthoringSource = null;
	}

	async function handleFindingSaved(result: FindingAuthoringResult) {
		const findingId = result.finding?.finding_id ?? '';
		closeAuthoring();
		authoringEvidence = [];
		authoringEvidenceVersion = null;
		await loadObjective(findingId, Boolean(findingId));
	}

	async function handleEvidenceSaved() {
		const selectedId = selectedFindingId;
		closeEvidenceAuthoring();
		authoringEvidence = [];
		authoringEvidenceVersion = null;
		await loadObjective(selectedId, Boolean(selectedId));
	}

	async function selectFinding(findingId: string, updateUrl = true) {
		const requestSequence = ++findingRequestSequence;
		selectedFindingId = findingId;
		selectedFinding = findings.find((item) => item.finding_id === findingId) ?? null;
		evidence = [];
		findingError = '';
		if (!findingId || !analysis?.objective.published_analysis_version) return;
		const analysisVersion = analysis.objective.published_analysis_version;
		const requestKey = `${collectionId}:${objectiveId}:${analysisVersion}:${findingId}`;
		findingLoading = true;
		try {
			const loadedEvidence: ObjectiveEvidence[] = [];
			while (true) {
				const page = await fetchObjectiveEvidence(
					collectionId,
					objectiveId,
					analysisVersion,
					findingId,
					loadedEvidence.length,
					500
				);
				loadedEvidence.push(...page.items);
				if (loadedEvidence.length >= page.total) break;
				if (!page.items.length) throw new Error('Evidence 分页结果不完整。');
			}
			const currentRequestKey = `${collectionId}:${objectiveId}:${analysis?.objective.published_analysis_version ?? ''}:${selectedFindingId}`;
			if (requestSequence !== findingRequestSequence || requestKey !== currentRequestKey) return;
			evidence = loadedEvidence;
			if (updateUrl) {
				const url = new URL(currentUrl);
				url.searchParams.set('finding_id', findingId);
				const objectiveHref: `/collections/${string}/objectives/${string}` = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}${url.search}`;
				await goto(resolve(objectiveHref), {
					replaceState: true,
					noScroll: true,
					keepFocus: true
				});
			}
		} catch (err) {
			if (requestSequence === findingRequestSequence) findingError = errorMessage(err);
		} finally {
			if (requestSequence === findingRequestSequence) findingLoading = false;
		}
	}

	function reviewFinding(findingId: string) {
		closeAuthoring();
		void selectFinding(findingId);
	}

	function directPaperCount(finding: ObjectiveFinding) {
		return finding.paper_contributions.filter(
			(item) => item.supporting_evidence_ids.length || item.contradicting_evidence_ids.length
		).length;
	}

	function synthesisLabel(value: ObjectiveFinding['synthesis_status']) {
		return {
			agreement: '多文献一致',
			conflict: '文献冲突',
			condition_dependent: '条件依赖',
			insufficient_confirmation: '证据待确认'
		}[value];
	}

	function certaintyLabel(value: number) {
		if (value >= 0.8) return '较高确定性';
		if (value >= 0.6) return '中等确定性';
		return '较低确定性';
	}

	function findingOriginLabel(value: ObjectiveFinding['origin'] | undefined) {
		if (value === 'human_authored') return '研究者创建';
		if (value === 'agent_authored') return 'Agent 分析';
		if (value === 'hybrid') return '研究者修订';
		return '系统分析';
	}

	function abstentionLabel(value: string | null) {
		return (
			{
				no_comparable_evidence: '研究者判断：现有结果不可直接比较',
				no_grounded_evidence: '研究者判断：没有足够的原文支持',
				insufficient_evidence: '研究者判断：证据数量或质量不足'
			}[value ?? ''] ?? '研究者记录了证据不足'
		);
	}

	async function startAnalysis() {
		if (!analysis || actionRunning || isProcessing) return;
		const documentIds = (
			analysis.active_analysis?.document_inputs.length
				? analysis.active_analysis.document_inputs
				: analysis.published_analysis?.document_inputs.length
					? analysis.published_analysis.document_inputs
					: analysis.objective.seed_document_ids.map((document_id) => ({
							document_id,
							preparation_fingerprint: ''
						}))
		).map((item) => item.document_id);
		if (!documentIds.length) {
			actionError = '请先从研究目标列表选择已准备的论文。';
			return;
		}
		actionRunning = true;
		actionError = '';
		try {
			analysis = await runObjectiveAnalysis(collectionId, objectiveId, documentIds);
			schedulePoll();
		} catch (err) {
			actionError = errorMessage(err);
		} finally {
			actionRunning = false;
		}
	}

	function schedulePoll() {
		clearPoll();
		const status = analysis?.active_analysis?.status;
		if (!browser || (status !== 'queued' && status !== 'running')) return;
		pollTimer = setTimeout(refreshAnalysis, POLL_DELAY_MS);
	}

	async function refreshAnalysis() {
		try {
			const previousVersion = analysis?.objective.published_analysis_version ?? null;
			const refreshed = await fetchObjectiveAnalysis(collectionId, objectiveId);
			const nextVersion = refreshed.objective.published_analysis_version;
			if (nextVersion !== previousVersion) {
				findingRequestSequence += 1;
				selectedFinding = null;
				evidence = [];
				closeAuthoring();
				authoringEvidence = [];
				authoringEvidenceVersion = null;
			}
			analysis = refreshed;
			if (nextVersion !== previousVersion || analysis.active_analysis?.status === 'succeeded') {
				await loadFindings();
			}
			schedulePoll();
		} catch (err) {
			actionError = errorMessage(err);
			clearPoll();
		}
	}

	function clearPoll() {
		if (!pollTimer) return;
		clearTimeout(pollTimer);
		pollTimer = null;
	}

	function actionLabel() {
		if (actionRunning) return '正在启动...';
		if (active?.status === 'failed') return '重试分析';
		if (published) return '重新分析';
		return '确认并分析';
	}

	function joined(items: string[]) {
		return items.length ? items.join(', ') : '-';
	}

	function datasetUrl() {
		return `/api/v1/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset?format=training_jsonl`;
	}
</script>

<svelte:head><title>{analysis?.objective.question ?? '研究目标'}</title></svelte:head>

{#if loading}
	<p class="page-state" aria-busy="true">正在加载研究目标...</p>
{:else if error || !analysis}
	<p class="page-state page-state--error" role="alert">{error || '研究目标不存在。'}</p>
{:else}
	<section class="objective-page">
		<header class="objective-header">
			<div>
				<a href={resolve('/collections/[id]/objectives', { id: collectionId })}>研究目标</a>
				<h1>{analysis.objective.question}</h1>
				<p>{analysis.objective.requested_comparator || '尚未设置比较意图'}</p>
			</div>
			<div class="header-actions">
				{#if !isProcessing}
					<button
						class="btn btn--primary btn--small"
						type="button"
						disabled={actionRunning}
						on:click={startAnalysis}
					>
						{actionLabel()}
					</button>
				{/if}
			</div>
		</header>

		<div class="scope-strip">
			<div><span>材料</span><strong>{joined(analysis.objective.material_scope)}</strong></div>
			<div><span>变量</span><strong>{joined(analysis.objective.variables)}</strong></div>
			<div><span>结果</span><strong>{joined(analysis.objective.outcomes)}</strong></div>
			<div><span>机制</span><strong>{joined(analysis.objective.mechanisms)}</strong></div>
			<div><span>约束</span><strong>{joined(analysis.objective.constraints)}</strong></div>
			<div><span>文献</span><strong>{analysis.objective.seed_document_ids.length} 篇</strong></div>
		</div>

		{#if active}
			<section class:failed={active.status === 'failed'} class="analysis-state" role="status">
				<div>
					<strong
						>{active.status === 'failed'
							? '本次分析失败'
							: active.status === 'succeeded'
								? '分析完成'
								: '正在分析'}</strong
					>
					<span>{active.progress_message || active.error_message || active.phase}</span>
					{#if active.status === 'failed' && published && active.analysis_version !== published.analysis_version}
						<span class="version-note"
							>正在显示已发布的 v{published.analysis_version}；重试 v{active.analysis_version} 失败。</span
						>
					{/if}
				</div>
				{#if active.total_document_count > 0}
					<span>{active.processed_document_count}/{active.total_document_count} 篇文献</span>
				{/if}
			</section>
		{/if}
		{#if actionError}<p class="action-error" role="alert">{actionError}</p>{/if}

		{#if published?.abstention_reason}
			<section class="authored-abstention" aria-label="研究者证据判断">
				<strong>{abstentionLabel(published.abstention_reason)}</strong>
				{#if published.abstention_note}<span>{published.abstention_note}</span>{/if}
			</section>
		{/if}

		{#if published}
			<section class="findings-workspace" aria-label="Finding 审阅工作区">
				<aside class="findings-sidebar" aria-label="Finding 列表">
					<div class="findings-heading">
						<div>
							<h2>Findings</h2>
							<p>选择一条发现进行证据审阅。</p>
						</div>
						<div class="findings-meta" aria-label="分析元信息">
							<span>{findings.length} 条 · v{published.analysis_version}</span>
							{#if published.model_name}
								<span>模型 {published.model_name}</span>
							{:else}
								<span>模型未记录</span>
							{/if}
						</div>
					</div>
					<button
						class="btn btn--primary btn--small new-finding"
						type="button"
						on:click={() => openAuthoring(null)}
					>
						新建 Finding
					</button>
					{#if findings.length}
						<ul class="finding-list">
							{#each findings as item (item.finding_id)}
								<li>
									<button
										type="button"
										aria-pressed={!authoringOpen && item.finding_id === selectedFindingId}
										class:selected={!authoringOpen && item.finding_id === selectedFindingId}
										on:click={() => reviewFinding(item.finding_id)}
									>
										<span>{item.statement}</span>
										<small>{findingOriginLabel(item.origin)}</small>
										<small
											>{synthesisLabel(item.synthesis_status)} · {certaintyLabel(item.certainty)} · {directPaperCount(
												item
											)} 篇直接文献</small
										>
									</button>
								</li>
							{/each}
						</ul>
					{:else}
						<p class="empty-findings">当前版本尚无 Finding。</p>
					{/if}
					<details class="secondary-actions">
						<summary>更多</summary>
						<a href={datasetUrl()} rel="external">导出训练数据</a>
					</details>
				</aside>

				<section
					class="finding-workspace"
					aria-label="Finding 详情"
					aria-busy={findingLoading || authoringLoading}
				>
					{#if evidenceAuthoringOpen && evidenceAuthoringSource}
						<EvidenceAuthoringEditor
							{collectionId}
							{objectiveId}
							analysisVersion={published.analysis_version}
							sourceEvidence={evidenceAuthoringSource}
							documentTitle={documentTitles[evidenceAuthoringSource.document_id] ?? '当前文献'}
							mode={evidenceAuthoringMode}
							onSaved={handleEvidenceSaved}
							onCancel={closeEvidenceAuthoring}
						/>
					{:else if authoringOpen && authoringLoading}
						<p class="page-state">正在加载当前版本的 Evidence...</p>
					{:else if authoringOpen && authoringError}
						<div class="finding-error" role="alert">
							<p>{authoringError}</p>
							<button
								class="btn btn--ghost btn--small"
								type="button"
								on:click={() => openAuthoring(authoringParent)}>重试加载 Evidence</button
							>
						</div>
					{:else if authoringOpen}
						{#key `${published.analysis_version}:${authoringParent?.finding_id ?? 'blank'}`}
							<FindingAuthoringEditor
								{collectionId}
								{objectiveId}
								analysisVersion={published.analysis_version}
								evidence={authoringEvidence}
								{documentTitles}
								parentFinding={authoringParent}
								onSaved={handleFindingSaved}
								onCancel={closeAuthoring}
							/>
						{/key}
					{:else if findingLoading}
						<p class="page-state">正在加载原文证据...</p>
					{:else if findingError}
						<div class="finding-error" role="alert">
							<p>{findingError}</p>
							<button
								class="btn btn--ghost btn--small"
								type="button"
								on:click={() => selectFinding(selectedFindingId, false)}>重试加载证据</button
							>
						</div>
					{:else if selectedFinding}
						<FindingWorkbench
							finding={selectedFinding}
							{evidence}
							{collectionId}
							{documentTitles}
							onDerive={(finding) => openAuthoring(finding)}
							onAuthorEvidence={openEvidenceAuthoring}
						/>
					{:else}
						<div class="page-state page-state--complete">
							<p>分析已完成，但当前证据未形成可直接比较的 Finding。</p>
							<span
								>v{published.analysis_version} · {published.model_name
									? `模型 ${published.model_name}`
									: '模型未记录'}</span
							>
							<span>可以记录证据不足，或从现有 Evidence 创建研究者 Finding。</span>
						</div>
					{/if}
				</section>
			</section>
		{:else if !isProcessing}
			<p class="page-state">确认并开始分析后，这里将展示可追溯的 Findings。</p>
		{/if}
	</section>
{/if}

<style>
	.objective-page {
		width: min(1360px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}
	.objective-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 20px;
	}
	.objective-header a {
		color: var(--text-secondary);
		font-size: 13px;
	}
	h1,
	h2,
	p {
		margin: 0;
	}
	h1 {
		margin-top: 8px;
		max-width: 850px;
		font-size: 25px;
		line-height: 1.4;
	}
	.objective-header p,
	.findings-heading p {
		margin-top: 6px;
		color: var(--text-secondary);
	}
	.header-actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.scope-strip {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
	}
	.scope-strip div {
		padding: 12px 14px;
		display: grid;
		gap: 4px;
		border-right: 1px solid var(--border-default);
	}
	.scope-strip div:last-child {
		border-right: 0;
	}
	.scope-strip span {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.scope-strip strong {
		font-size: 13px;
		overflow-wrap: anywhere;
	}
	.analysis-state {
		padding: 12px 14px;
		display: flex;
		justify-content: space-between;
		gap: 16px;
		border-left: 3px solid #3676a8;
		background: var(--surface-subtle);
	}
	.analysis-state > div {
		display: grid;
		gap: 3px;
	}
	.analysis-state span {
		color: var(--text-secondary);
	}
	.analysis-state.failed {
		border-color: #b42318;
	}
	.authored-abstention {
		display: grid;
		gap: 4px;
		padding: 12px 14px;
		border-left: 3px solid #8a6d1d;
		background: var(--surface-subtle);
	}
	.authored-abstention span {
		color: var(--text-secondary);
		white-space: pre-line;
	}
	.analysis-state .version-note {
		color: var(--text-primary);
		font-weight: 600;
	}
	.action-error,
	.page-state--error {
		color: var(--danger, #b42318);
	}
	.findings-workspace {
		display: grid;
		grid-template-columns: minmax(260px, 0.34fr) minmax(0, 1fr);
		gap: 28px;
		align-items: start;
	}
	.findings-sidebar {
		position: sticky;
		top: 16px;
		max-height: calc(100vh - 32px);
		overflow-y: auto;
		padding-right: 24px;
		border-right: 1px solid var(--border-default);
	}
	.findings-heading {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		align-items: flex-start;
		margin-bottom: 12px;
	}
	.findings-meta {
		display: grid;
		max-width: 55%;
		gap: 4px;
		justify-items: end;
		text-align: right;
		color: var(--text-secondary);
		font-size: 12px;
	}
	.findings-meta span {
		overflow-wrap: anywhere;
	}
	.finding-list {
		margin: 0;
		padding: 0;
		list-style: none;
		border-top: 1px solid var(--border-default);
	}
	.new-finding {
		width: 100%;
		margin-bottom: 12px;
	}
	.empty-findings {
		padding: 14px 0;
		border-block: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 13px;
	}
	.finding-list button {
		width: 100%;
		border: 0;
		border-bottom: 1px solid var(--border-default);
		background: transparent;
		color: inherit;
		display: grid;
		gap: 7px;
		text-align: left;
		align-items: center;
		padding: 13px 10px 13px 12px;
		cursor: pointer;
	}
	.finding-list button:hover,
	.finding-list button.selected {
		background: var(--surface-subtle);
	}
	.finding-list button.selected {
		box-shadow: inset 3px 0 #3a7d5d;
	}
	.finding-list small {
		color: var(--text-secondary);
		font-style: normal;
		line-height: 1.45;
	}
	.secondary-actions {
		margin-top: 12px;
		color: var(--text-secondary);
		font-size: 12px;
	}
	.finding-workspace {
		min-width: 0;
	}
	.secondary-actions summary {
		cursor: pointer;
	}
	.secondary-actions a {
		display: inline-block;
		margin-top: 8px;
		color: var(--accent);
	}
	.finding-error {
		display: grid;
		justify-items: start;
		gap: 12px;
		padding: 20px 0;
		color: var(--danger, #b42318);
	}
	.page-state {
		padding: 30px 0;
		color: var(--text-secondary);
	}
	.page-state--complete {
		display: grid;
		gap: 6px;
	}
	.page-state--complete span {
		font-size: 12px;
	}
	@media (max-width: 1000px) {
		.findings-workspace {
			grid-template-columns: 1fr;
			gap: 24px;
		}
		.findings-sidebar {
			position: static;
			max-height: none;
			overflow: visible;
			padding: 0 0 20px;
			border-right: 0;
			border-bottom: 1px solid var(--border-default);
		}
	}
	@media (max-width: 820px) {
		.objective-header,
		.findings-heading {
			flex-direction: column;
			align-items: flex-start;
		}
		.findings-meta {
			max-width: 100%;
			justify-items: start;
			text-align: left;
		}
		.scope-strip {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
