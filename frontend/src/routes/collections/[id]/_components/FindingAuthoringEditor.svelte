<script lang="ts">
	import { resolve } from '$app/paths';
	import { SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';
	import { errorMessage } from '../../../_shared/api';
	import {
		createFindingVersion,
		type FindingAbstentionReason,
		type FindingAuthoringResult,
		type ObjectiveEvidence,
		type ObjectiveFinding
	} from '../../../_shared/researchView';

	export let collectionId: string;
	export let objectiveId: string;
	export let analysisVersion: number;
	export let evidence: ObjectiveEvidence[] = [];
	export let documentTitles: Record<string, string> = {};
	export let parentFinding: ObjectiveFinding | null = null;
	export let onSaved: (result: FindingAuthoringResult) => void | Promise<void> = () => {};
	export let onCancel: () => void = () => {};

	type DraftMode = 'finding' | 'abstention';
	type EvidenceRole = 'unused' | 'supporting' | 'contradicting' | 'context';

	let initializedKey = '';
	let mode: DraftMode = 'finding';
	let statement = '';
	let assertionStrength: 'causal' | 'associative' | 'descriptive' = 'associative';
	let limitations = '';
	let abstentionReason: FindingAbstentionReason = 'no_comparable_evidence';
	let roleByEvidence: Record<string, EvidenceRole> = {};
	let boundaryEvidenceIds = new SvelteSet<string>();
	let saving = false;
	let formError = '';

	$: editorKey = `${analysisVersion}:${parentFinding?.finding_id ?? 'blank'}`;
	$: if (editorKey !== initializedKey) initializeDraft();
	$: eligibleEvidence = evidence.filter((item) => item.supports_finding);
	$: supportingCount = Object.values(roleByEvidence).filter((role) => role === 'supporting').length;

	function initializeDraft() {
		initializedKey = editorKey;
		mode = 'finding';
		statement = parentFinding?.statement ?? '';
		assertionStrength = parentFinding?.assertion_strength ?? 'associative';
		limitations = parentFinding?.limitations.join('\n') ?? '';
		abstentionReason = 'no_comparable_evidence';
		roleByEvidence = {};
		boundaryEvidenceIds = new SvelteSet<string>();
		for (const contribution of parentFinding?.paper_contributions ?? []) {
			for (const evidenceId of contribution.supporting_evidence_ids) {
				roleByEvidence[evidenceId] = 'supporting';
			}
			for (const evidenceId of contribution.contradicting_evidence_ids) {
				roleByEvidence[evidenceId] = 'contradicting';
			}
			for (const evidenceId of contribution.context_evidence_ids) {
				roleByEvidence[evidenceId] = 'context';
			}
			for (const evidenceId of contribution.condition_boundary_evidence_ids) {
				boundaryEvidenceIds.add(evidenceId);
			}
		}
		roleByEvidence = { ...roleByEvidence };
		boundaryEvidenceIds = new SvelteSet(boundaryEvidenceIds);
		formError = '';
	}

	function availableRoles(item: ObjectiveEvidence) {
		if (item.evidence_role === 'direct_result' || item.evidence_role === 'contradictory_result') {
			return [
				{ value: 'unused', label: '不使用' },
				{ value: 'supporting', label: '支持结论' },
				{ value: 'contradicting', label: '反例' }
			] satisfies Array<{ value: EvidenceRole; label: string }>;
		}
		return [
			{ value: 'unused', label: '不使用' },
			{ value: 'context', label: '适用条件或机制' }
		] satisfies Array<{ value: EvidenceRole; label: string }>;
	}

	function setEvidenceRole(evidenceId: string, role: EvidenceRole) {
		roleByEvidence = { ...roleByEvidence, [evidenceId]: role };
		if (role === 'unused' && boundaryEvidenceIds.has(evidenceId)) {
			const next = new SvelteSet(boundaryEvidenceIds);
			next.delete(evidenceId);
			boundaryEvidenceIds = next;
		}
	}

	function setBoundary(evidenceId: string, checked: boolean) {
		const next = new SvelteSet(boundaryEvidenceIds);
		if (checked) next.add(evidenceId);
		else next.delete(evidenceId);
		boundaryEvidenceIds = next;
	}

	function paperTitle(documentId: string) {
		return documentTitles[documentId]?.trim() || '未命名文献';
	}

	function sourceLabel(item: ObjectiveEvidence) {
		const page = item.page_numbers[0];
		return page ? `${paperTitle(item.document_id)} · p.${page}` : paperTitle(item.document_id);
	}

	function sourceHref(item: ObjectiveEvidence): `/collections/${string}/documents/${string}` {
		const base = resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: item.document_id
		});
		const params = new SvelteURLSearchParams({
			view: 'parsed-paper',
			evidence_id: item.evidence_id,
			source_ref: item.source_ref,
			quote: item.source_excerpt
		});
		if (item.page_numbers[0]) params.set('page', String(item.page_numbers[0]));
		return `${base}?${params.toString()}` as `/collections/${string}/documents/${string}`;
	}

	function cleanLines(value: string) {
		return [
			...new Set(
				value
					.split('\n')
					.map((item) => item.trim())
					.filter(Boolean)
			)
		];
	}

	function idsFor(role: EvidenceRole) {
		return eligibleEvidence
			.filter((item) => roleByEvidence[item.evidence_id] === role)
			.map((item) => item.evidence_id);
	}

	async function submit() {
		formError = '';
		const cleanedLimitations = cleanLines(limitations);
		if (mode === 'finding' && !statement.trim()) {
			formError = '请先写出要保存的研究结论。';
			return;
		}
		if (mode === 'finding' && supportingCount === 0) {
			formError = '至少选择一条直接结果作为支持证据。';
			return;
		}
		if (mode === 'abstention' && cleanedLimitations.length === 0) {
			formError = '请说明为什么当前证据不足以形成结论。';
			return;
		}
		saving = true;
		try {
			const result = await createFindingVersion(collectionId, objectiveId, {
				source_analysis_version: analysisVersion,
				statement: mode === 'finding' ? statement.trim() : null,
				assertion_strength: mode === 'finding' ? assertionStrength : null,
				supporting_evidence_ids: mode === 'finding' ? idsFor('supporting') : [],
				contradicting_evidence_ids: mode === 'finding' ? idsFor('contradicting') : [],
				context_evidence_ids: mode === 'finding' ? idsFor('context') : [],
				condition_boundary_evidence_ids: mode === 'finding' ? [...boundaryEvidenceIds] : [],
				limitations: cleanedLimitations,
				parent_finding_id: mode === 'finding' ? (parentFinding?.finding_id ?? null) : null,
				abstention_reason: mode === 'abstention' ? abstentionReason : null
			});
			await onSaved(result);
		} catch (error) {
			formError = errorMessage(error);
		} finally {
			saving = false;
		}
	}
</script>

<section class="authoring" aria-labelledby="finding-authoring-title" aria-busy={saving}>
	<header>
		<div>
			<span>{parentFinding ? '从已发布结果派生，不改动原结果' : '基于当前已发布 Evidence'}</span>
			<h2 id="finding-authoring-title">
				{parentFinding ? '修订为新 Finding' : '创建 Finding'}
			</h2>
		</div>
		<button class="btn btn--ghost btn--small" type="button" on:click={onCancel}>取消</button>
	</header>

	<fieldset class="mode-selector">
		<legend>记录类型</legend>
		<label>
			<input type="radio" bind:group={mode} value="finding" />
			<span>形成 Finding</span>
		</label>
		<label>
			<input type="radio" bind:group={mode} value="abstention" />
			<span>记录证据不足</span>
		</label>
	</fieldset>

	{#if mode === 'finding'}
		<div class="statement-grid">
			<label for="finding-statement">
				<span>结论</span>
				<textarea id="finding-statement" rows="4" bind:value={statement}></textarea>
			</label>
			<label for="finding-assertion-strength">
				<span>陈述强度</span>
				<select id="finding-assertion-strength" bind:value={assertionStrength}>
					<option value="descriptive">描述观察</option>
					<option value="associative">表达关联</option>
					<option value="causal">表达因果</option>
				</select>
			</label>
		</div>

		<section class="evidence-selection" aria-labelledby="finding-evidence-title">
			<div class="section-heading">
				<div>
					<h3 id="finding-evidence-title">选择原文证据</h3>
					<p>{supportingCount} 条支持证据 · {eligibleEvidence.length} 条可用 Evidence</p>
				</div>
			</div>
			{#if eligibleEvidence.length}
				<div class="evidence-list">
					{#each eligibleEvidence as item (item.evidence_id)}
						<article class="evidence-row">
							<div class="evidence-copy">
								<a href={resolve(sourceHref(item))}>{sourceLabel(item)}</a>
								<blockquote>{item.source_excerpt}</blockquote>
							</div>
							<div class="evidence-controls">
								<label>
									<span>在 Finding 中的作用</span>
									<select
										aria-label="在 Finding 中的作用"
										value={roleByEvidence[item.evidence_id] ?? 'unused'}
										on:change={(event) =>
											setEvidenceRole(
												item.evidence_id,
												(event.currentTarget as HTMLSelectElement).value as EvidenceRole
											)}
									>
										{#each availableRoles(item) as option (option.value)}
											<option value={option.value}>{option.label}</option>
										{/each}
									</select>
								</label>
								<label class="boundary">
									<input
										type="checkbox"
										checked={boundaryEvidenceIds.has(item.evidence_id)}
										disabled={(roleByEvidence[item.evidence_id] ?? 'unused') === 'unused'}
										on:change={(event) =>
											setBoundary(item.evidence_id, event.currentTarget.checked)}
									/>
									<span>限定适用条件</span>
								</label>
							</div>
						</article>
					{/each}
				</div>
			{:else}
				<p class="empty">当前版本没有可用于 Finding 的 Evidence。</p>
			{/if}
		</section>
	{:else}
		<div class="abstention-grid">
			<label for="abstention-reason">
				<span>证据状态</span>
				<select id="abstention-reason" bind:value={abstentionReason}>
					<option value="no_comparable_evidence">现有结果不可直接比较</option>
					<option value="no_grounded_evidence">没有原文支持的结果</option>
					<option value="insufficient_evidence">证据数量或质量不足</option>
				</select>
			</label>
		</div>
	{/if}

	<label class="limitations" for="finding-limitations">
		<span>{mode === 'finding' ? '适用边界与局限' : '证据不足说明'}</span>
		<textarea id="finding-limitations" rows="4" bind:value={limitations} placeholder="每行一条"
		></textarea>
	</label>

	<footer>
		{#if formError}<p class="error" role="alert">{formError}</p>{/if}
		<button class="btn btn--primary" type="button" disabled={saving} on:click={submit}>
			{saving ? '正在保存...' : mode === 'finding' ? '创建 Finding' : '记录证据不足'}
		</button>
	</footer>
</section>

<style>
	.authoring {
		display: grid;
		gap: 20px;
		min-width: 0;
	}
	header,
	.section-heading,
	footer {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
	}
	header span,
	.section-heading p {
		color: var(--text-secondary);
		font-size: 12px;
	}
	h2,
	h3,
	p {
		margin: 0;
	}
	h2 {
		margin-top: 5px;
		font-size: 22px;
	}
	h3 {
		font-size: 15px;
	}
	.mode-selector {
		display: flex;
		gap: 16px;
		margin: 0;
		padding: 12px 0;
		border: 0;
		border-block: 1px solid var(--border-default);
	}
	.mode-selector legend {
		padding: 0 0 8px;
		font-size: 12px;
		color: var(--text-secondary);
	}
	.mode-selector label,
	.boundary {
		display: inline-flex;
		align-items: center;
		gap: 7px;
	}
	.statement-grid,
	.abstention-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(180px, 0.3fr);
		gap: 14px;
		align-items: start;
	}
	.statement-grid label,
	.abstention-grid label,
	.limitations,
	.evidence-controls label:not(.boundary) {
		display: grid;
		gap: 6px;
		font-size: 12px;
	}
	textarea,
	select {
		width: 100%;
		border: 1px solid var(--border-default);
		background: var(--surface-primary);
		color: var(--text-primary);
		padding: 9px 10px;
		font: inherit;
	}
	textarea {
		resize: vertical;
		line-height: 1.55;
	}
	.evidence-selection {
		display: grid;
		gap: 10px;
	}
	.evidence-list {
		border-top: 1px solid var(--border-default);
	}
	.evidence-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(190px, 0.28fr);
		gap: 18px;
		padding: 14px 0;
		border-bottom: 1px solid var(--border-default);
	}
	.evidence-copy {
		min-width: 0;
	}
	.evidence-copy a {
		font-size: 13px;
		font-weight: 600;
	}
	blockquote {
		margin: 8px 0 0;
		padding-left: 12px;
		border-left: 2px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 1.55;
		overflow-wrap: anywhere;
	}
	.evidence-controls {
		display: grid;
		align-content: start;
		gap: 10px;
	}
	.boundary {
		font-size: 12px;
	}
	footer {
		align-items: center;
		justify-content: flex-end;
	}
	footer .error {
		margin-right: auto;
		color: var(--danger, #b42318);
	}
	.empty {
		color: var(--text-secondary);
	}
	@media (max-width: 760px) {
		.statement-grid,
		.abstention-grid,
		.evidence-row {
			grid-template-columns: 1fr;
		}
		header,
		footer {
			align-items: stretch;
			flex-direction: column;
		}
		footer button {
			width: 100%;
		}
	}
</style>
