<script lang="ts">
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import FindingAuthoringEditor from '../../_components/FindingAuthoringEditor.svelte';
	import EvidenceAuthoringEditor from '../../_components/EvidenceAuthoringEditor.svelte';
	import FindingWorkbench from '../../_components/FindingWorkbench.svelte';
	import { downloadBlob, errorMessage } from '../../../../_shared/api';
	import { fetchDocumentProfiles } from '../../../../_shared/documents';
	import {
		fetchObjectiveAnalysis,
		fetchObjectiveEvidence,
		fetchObjectiveFindings,
		objectiveFindingDatasetUrl,
		runObjectiveAnalysis,
		type FindingDatasetLabelStatus,
		type FindingDatasetUseStatus,
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
	let datasetLabelStatus: FindingDatasetLabelStatus | '' = '';
	let datasetUseStatus: FindingDatasetUseStatus | '' = '';
	let datasetDownloading = false;
	let datasetError = '';

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

	function evidenceStatusLabel(value: string) {
		return (
			{
				comparable: '可直接比较',
				association_only: '只能说明关联',
				descriptive: '仅描述结果',
				needs_context: '需要补充上下文',
				non_comparable: '条件不可直接比较',
				extraction_failed: '技术提取失败'
			}[value] ?? '待判断'
		);
	}

	function evidenceGapHref(gap: ObjectiveAnalysis['evidence_review']['gaps'][number]) {
		const base = resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: gap.document_id
		});
		const params = new SvelteURLSearchParams({
			view: 'parsed-paper',
			evidence_id: gap.evidence_id,
			source_ref: gap.source_ref,
			quote: gap.source_excerpt
		});
		if (gap.page_numbers[0]) params.set('page', String(gap.page_numbers[0]));
		return `${base}?${params.toString()}` as `/collections/${string}/documents/${string}`;
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

	function datasetFilters() {
		return {
			...(datasetLabelStatus ? { label_status: datasetLabelStatus } : {}),
			...(datasetUseStatus ? { dataset_use_status: datasetUseStatus } : {})
		};
	}

	async function downloadDataset(format: 'json' | 'training_jsonl') {
		if (!published || datasetDownloading) return;
		datasetDownloading = true;
		datasetError = '';
		try {
			const extension = format === 'json' ? 'json' : 'jsonl';
			await downloadBlob(
				objectiveFindingDatasetUrl(collectionId, objectiveId, format, datasetFilters()),
				`objective-${objectiveId}-finding-dataset.${extension}`
			);
		} catch (err) {
			datasetError = errorMessage(err);
		} finally {
			datasetDownloading = false;
		}
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

		{#if published && analysis.evidence_review.total_evidence_count > 0}
			<section class="evidence-review" aria-label="证据覆盖审阅">
				<div class="evidence-review__header">
					<div>
						<h2>证据覆盖</h2>
						<p>保留每条原文记录，并把暂时不能支撑结论的原因列出来。</p>
					</div>
					<span class="evidence-review__total">
						{analysis.evidence_review.total_evidence_count} 条原文记录 ·
						{analysis.evidence_review.result_count} 条结果
					</span>
				</div>
				<div class="evidence-review__counts" aria-label="证据状态统计">
					{#each Object.entries(analysis.evidence_review.status_counts) as [status, count] (status)}
						<span class="evidence-count">
							<strong>{count}</strong>
							{evidenceStatusLabel(status)}
						</span>
					{/each}
				</div>
				{#if analysis.evidence_review.gaps.length}
					<div class="evidence-review__gaps">
						<h3>需要研究者判断的记录</h3>
						{#each analysis.evidence_review.gaps as gap (gap.evidence_id)}
							<article class="evidence-gap">
								<div class="evidence-gap__heading">
									<strong>{evidenceStatusLabel(gap.evidence_status)}</strong>
									<span>
										{documentTitles[gap.document_id] || gap.document_id}
										{#if gap.page_numbers.length}
											· p.{gap.page_numbers.join(', ')}{/if}
									</span>
								</div>
								<p>{gap.reason}</p>
								{#if gap.outcome}<small>结果轴：{gap.outcome}</small>{/if}
								{#if gap.source_excerpt}<blockquote>{gap.source_excerpt}</blockquote>{/if}
								<a href={resolve(evidenceGapHref(gap))}>查看原文</a>
							</article>
						{/each}
						{#if analysis.evidence_review.omitted_gap_count > 0}
							<p class="evidence-review__omitted">
								还有 {analysis.evidence_review.omitted_gap_count} 条记录未展开，请从原文和 Evidence 列表继续审阅。
							</p>
						{/if}
					</div>
				{/if}
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
					<section class="export-panel" aria-label="导出 Finding 数据">
						<div class="export-panel__heading">
							<div>
								<h3>导出研究结果</h3>
								<p>
									下载当前已发布分析 v{published.analysis_version} 的 Finding 数据，用于复核或后续标注。
								</p>
							</div>
						</div>
						<div class="export-filters">
							<label>
								<span>标注状态</span>
								<select bind:value={datasetLabelStatus} disabled={datasetDownloading}>
									<option value="">全部</option>
									<option value="candidate">候选</option>
									<option value="silver">银标</option>
									<option value="gold">金标</option>
									<option value="rejected">已拒绝</option>
								</select>
							</label>
							<label>
								<span>数据用途</span>
								<select bind:value={datasetUseStatus} disabled={datasetDownloading}>
									<option value="">全部</option>
									<option value="training_ready">可训练</option>
									<option value="review_candidate">待审阅</option>
									<option value="rejected">已拒绝</option>
								</select>
							</label>
						</div>
						<div class="export-actions">
							<button
								class="btn btn--ghost btn--small"
								type="button"
								disabled={datasetDownloading}
								on:click={() => downloadDataset('json')}
							>
								导出 JSON
							</button>
							<button
								class="btn btn--ghost btn--small"
								type="button"
								disabled={datasetDownloading}
								on:click={() => downloadDataset('training_jsonl')}
							>
								导出训练 JSONL
							</button>
							{#if datasetDownloading}<span class="export-status" role="status"
									>正在准备下载...</span
								>{/if}
						</div>
						{#if datasetError}<p class="export-error" role="alert">{datasetError}</p>{/if}
					</section>
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
	.evidence-review {
		display: grid;
		gap: 14px;
		padding: 16px 18px;
		border: 1px solid var(--border-default);
		background: var(--surface-subtle);
	}
	.evidence-review__header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
	}
	.evidence-review h2 {
		font-size: 17px;
	}
	.evidence-review h3 {
		font-size: 14px;
	}
	.evidence-review p,
	.evidence-review__total,
	.evidence-gap span,
	.evidence-gap small {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 1.5;
	}
	.evidence-review__header p {
		margin-top: 4px;
	}
	.evidence-review__total {
		white-space: nowrap;
	}
	.evidence-review__counts {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.evidence-count {
		display: inline-flex;
		align-items: baseline;
		gap: 5px;
		padding: 5px 8px;
		border: 1px solid var(--border-default);
		background: var(--surface-card);
		font-size: 12px;
	}
	.evidence-count strong {
		font-size: 14px;
	}
	.evidence-review__gaps {
		display: grid;
		gap: 8px;
	}
	.evidence-gap {
		display: grid;
		gap: 5px;
		padding: 10px 12px;
		border-left: 3px solid #8a6d1d;
		background: var(--surface-card);
	}
	.evidence-gap__heading {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 10px;
		align-items: baseline;
	}
	.evidence-gap__heading strong {
		font-size: 12px;
	}
	.evidence-gap blockquote {
		margin: 2px 0 0;
		padding-left: 10px;
		border-left: 2px solid var(--border-default);
		font-size: 13px;
		line-height: 1.55;
		white-space: pre-line;
	}
	.evidence-gap a {
		width: fit-content;
		color: var(--accent, #2d6a4f);
		font-size: 12px;
		font-weight: 600;
	}
	.evidence-review__omitted {
		margin-top: 2px;
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
	.export-panel {
		margin-top: 18px;
		padding-top: 16px;
		border-top: 1px solid var(--border-default);
	}
	.export-panel__heading {
		display: grid;
		gap: 5px;
	}
	.export-panel h3 {
		font-size: 14px;
	}
	.export-panel p,
	.export-panel label span,
	.export-status {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 1.5;
	}
	.export-filters {
		display: grid;
		gap: 8px;
		margin-top: 12px;
	}
	.export-filters label {
		display: grid;
		gap: 4px;
	}
	.export-filters select {
		width: 100%;
		min-height: 34px;
		padding: 6px 8px;
		border: 1px solid var(--border-default);
		border-radius: 4px;
		background: var(--surface-card);
		color: inherit;
		font: inherit;
		font-size: 12px;
	}
	.export-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-top: 12px;
	}
	.export-error {
		margin-top: 10px;
		color: var(--danger, #b42318) !important;
	}
	.finding-workspace {
		min-width: 0;
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
		.evidence-review__header {
			flex-direction: column;
		}
		.evidence-review__total {
			white-space: normal;
		}
	}
</style>
