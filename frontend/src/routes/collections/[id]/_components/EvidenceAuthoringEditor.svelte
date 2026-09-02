<script lang="ts">
	import { errorMessage } from '../../../_shared/api';
	import {
		createEvidenceVersion,
		type EvidenceAuthoringCreate,
		type EvidenceAuthoringResult,
		type ObjectiveEvidence,
		type ObjectiveEvidenceResultDirection,
		type ObjectiveScientificContext
	} from '../../../_shared/researchView';

	export let collectionId: string;
	export let objectiveId: string;
	export let analysisVersion: number;
	export let sourceEvidence: ObjectiveEvidence;
	export let documentTitle = '当前文献';
	export let mode: 'create' | 'revise' = 'create';
	export let onSaved: (result: EvidenceAuthoringResult) => void | Promise<void> = () => {};
	export let onCancel: () => void = () => {};

	type Scalar = string | number | boolean | null;
	type VariableDraft = {
		name: string;
		baseline_value: Scalar;
		target_value: Scalar;
		unit: string;
	};

	let sourceExcerpt = '';
	let evidenceRole: EvidenceAuthoringCreate['evidence_role'] = 'direct_result';
	let attributionScope: EvidenceAuthoringCreate['attribution_scope'] = 'association_only';
	let variables: VariableDraft[] = [];
	let baselineLabel = '';
	let targetLabel = '';
	let comparable = true;
	let axisNames = '';
	let incomparabilityReasons = '';
	let hasComparison = false;
	let hasResult = true;
	let outcome = '';
	let resultValue = '';
	let resultBaseline = '';
	let resultTarget = '';
	let resultUnit = '';
	let direction: ObjectiveEvidenceResultDirection = 'unknown';
	let resultText = '';
	let materialContext = '';
	let sampleContext = '';
	let processContext = '';
	let testContext = '';
	let authoringNote = '';
	let saving = false;
	let formError = '';
	let initializedKey = '';

	$: editorKey = `${analysisVersion}:${sourceEvidence.evidence_id}:${mode}`;
	$: if (editorKey !== initializedKey) initializeDraft();
	$: resultRole = evidenceRole === 'direct_result' || evidenceRole === 'contradictory_result';
	$: if (!resultRole) hasResult = false;

	function initializeDraft() {
		initializedKey = editorKey;
		sourceExcerpt = sourceEvidence.source_excerpt;
		evidenceRole = sourceEvidence.evidence_role as EvidenceAuthoringCreate['evidence_role'];
		attributionScope = sourceEvidence.attribution_scope;
		variables = sourceEvidence.changed_variables.map((item) => ({
			name: item.name,
			baseline_value: item.baseline_value,
			target_value: item.target_value,
			unit: item.unit ?? ''
		}));
		baselineLabel = sourceEvidence.comparison?.baseline_label ?? '';
		targetLabel = sourceEvidence.comparison?.target_label ?? '';
		comparable = sourceEvidence.comparison?.comparable ?? true;
		axisNames = sourceEvidence.comparison?.axis_names.join(', ') ?? '';
		incomparabilityReasons = sourceEvidence.comparison?.incomparability_reasons.join('\n') ?? '';
		hasComparison = Boolean(sourceEvidence.comparison);
		hasResult =
			Boolean(sourceEvidence.reported_result) ||
			evidenceRole === 'direct_result' ||
			evidenceRole === 'contradictory_result';
		outcome = sourceEvidence.reported_result?.outcome ?? '';
		resultValue = scalarText(sourceEvidence.reported_result?.value);
		resultBaseline = scalarText(sourceEvidence.reported_result?.baseline_value);
		resultTarget = scalarText(sourceEvidence.reported_result?.target_value);
		resultUnit = sourceEvidence.reported_result?.unit ?? '';
		direction = sourceEvidence.reported_result?.direction ?? 'unknown';
		resultText = sourceEvidence.reported_result?.result_text ?? '';
		materialContext = contextText(sourceEvidence.scientific_context.material);
		sampleContext = contextText(sourceEvidence.scientific_context.sample);
		processContext = contextText(sourceEvidence.scientific_context.process);
		testContext = contextText(sourceEvidence.scientific_context.test);
		authoringNote = sourceEvidence.authoring_note ?? '';
		formError = '';
	}

	function scalarText(value: Scalar | undefined) {
		return value === null || value === undefined ? '' : String(value);
	}

	function contextText(items: ObjectiveScientificContext['material']) {
		return items
			.map((item) => `${item.name}: ${item.value}${item.unit ? ` ${item.unit}` : ''}`)
			.join('\n');
	}

	function parseScalar(value: string): Scalar {
		const trimmed = value.trim();
		if (!trimmed) return null;
		if (trimmed === 'true') return true;
		if (trimmed === 'false') return false;
		const number = Number(trimmed);
		return Number.isFinite(number) && /^[-+]?\d+(\.\d+)?$/.test(trimmed) ? number : trimmed;
	}

	function parseLines(value: string) {
		return [
			...new Set(
				value
					.split('\n')
					.map((item) => item.trim())
					.filter(Boolean)
			)
		];
	}

	function parseContext(value: string) {
		return parseLines(value).map((line) => {
			const separator = line.indexOf(':');
			if (separator < 1) return { name: line, value: line, unit: null };
			const name = line.slice(0, separator).trim();
			const raw = line.slice(separator + 1).trim();
			return { name, value: parseScalar(raw) ?? raw, unit: null };
		});
	}

	function addVariable() {
		if (variables.length >= 20) return;
		variables = [...variables, { name: '', baseline_value: null, target_value: null, unit: '' }];
	}

	function removeVariable(index: number) {
		variables = variables.filter((_, itemIndex) => itemIndex !== index);
	}

	function updateVariable(index: number, key: keyof VariableDraft, value: string) {
		variables = variables.map((item, itemIndex) =>
			itemIndex === index
				? { ...item, [key]: key === 'name' || key === 'unit' ? value : parseScalar(value) }
				: item
		);
	}

	function evidencePayload(): EvidenceAuthoringCreate {
		const context = {
			material: parseContext(materialContext),
			sample: parseContext(sampleContext),
			process: parseContext(processContext),
			test: parseContext(testContext)
		};
		return {
			source_analysis_version: analysisVersion,
			document_id: sourceEvidence.document_id,
			source_kind: sourceEvidence.source_kind as EvidenceAuthoringCreate['source_kind'],
			source_ref: sourceEvidence.source_ref,
			source_excerpt: sourceExcerpt.trim(),
			evidence_role: evidenceRole,
			changed_variables: variables
				.filter((item) => item.name.trim())
				.map((item) => ({ ...item, name: item.name.trim(), unit: item.unit.trim() || null })),
			comparison: hasComparison
				? {
						baseline_label: baselineLabel.trim(),
						target_label: targetLabel.trim(),
						axis_names: parseLines(axisNames.replaceAll(',', '\n')),
						comparable,
						incomparability_reasons: parseLines(incomparabilityReasons)
					}
				: null,
			reported_result: hasResult
				? {
						outcome: outcome.trim(),
						value: parseScalar(resultValue),
						baseline_value: parseScalar(resultBaseline),
						target_value: parseScalar(resultTarget),
						unit: resultUnit.trim() || null,
						direction,
						result_text: resultText.trim()
					}
				: null,
			attribution_scope: attributionScope,
			scientific_context: context,
			supersedes_evidence_id: mode === 'revise' ? sourceEvidence.evidence_id : null,
			authoring_note: authoringNote.trim() || null
		};
	}

	async function submit() {
		formError = '';
		const payload = evidencePayload();
		if (!payload.source_excerpt) {
			formError = '请保留原文摘录，系统会验证它确实来自该 Source。';
			return;
		}
		if (!payload.evidence_role) {
			formError = '请选择这段原文在研究中的作用。';
			return;
		}
		if (
			payload.comparison &&
			(!payload.comparison.baseline_label || !payload.comparison.target_label)
		) {
			formError = '比较证据需要填写参照条件和比较条件。';
			return;
		}
		if (
			payload.reported_result &&
			(!payload.reported_result.outcome || !payload.reported_result.result_text)
		) {
			formError = '结果证据需要填写结果名称和原文结果描述。';
			return;
		}
		saving = true;
		try {
			const result = await createEvidenceVersion(collectionId, objectiveId, payload);
			await onSaved(result);
		} catch (error) {
			formError = errorMessage(error);
		} finally {
			saving = false;
		}
	}
</script>

<section class="authoring" aria-labelledby="evidence-authoring-title" aria-busy={saving}>
	<header>
		<div>
			<span
				>{mode === 'revise' ? '修订不会覆盖历史记录' : '从当前原文来源记录一条新的科研证据'}</span
			>
			<h2 id="evidence-authoring-title">{mode === 'revise' ? '修订 Evidence' : '创建 Evidence'}</h2>
		</div>
		<button class="btn btn--ghost btn--small" type="button" on:click={onCancel}>取消</button>
	</header>

	<section class="source-panel" aria-label="原文来源">
		<div class="source-meta">
			<strong>{documentTitle}</strong><span
				>{sourceEvidence.source_kind} · {sourceEvidence.page_numbers.length
					? `p.${sourceEvidence.page_numbers.join(', ')}`
					: '页码未记录'}</span
			>
		</div>
		<label for="evidence-source-excerpt"
			><span>原文摘录</span><textarea
				id="evidence-source-excerpt"
				rows="4"
				bind:value={sourceExcerpt}
			></textarea></label
		>
		<p>保存时会检查摘录是否属于这段完整原文；改写或补充原文之外的内容会被拒绝。</p>
	</section>

	<div class="form-grid">
		<label for="evidence-role"
			><span>这段原文说明</span><select id="evidence-role" bind:value={evidenceRole}>
				<option value="direct_result">直接结果</option>
				<option value="contradictory_result">相反结果</option>
				<option value="condition_context">实验条件</option>
				<option value="mechanism_context">作用机制</option>
				<option value="baseline_context">参照信息</option>
				<option value="comparison_context">比较上下文</option>
				<option value="background_context">背景信息</option>
			</select></label
		>
		<label for="evidence-attribution"
			><span>能否归因</span><select id="evidence-attribution" bind:value={attributionScope}>
				<option value="isolated_effect">单一变量影响</option>
				<option value="joint_effect">多个变量共同影响</option>
				<option value="association_only">只表达关联</option>
				<option value="descriptive_only">只描述观察</option>
				<option value="not_attributable">不能归因</option>
			</select></label
		>
	</div>

	<section class="structured-section" aria-labelledby="evidence-variables-title">
		<div class="section-heading">
			<div>
				<h3 id="evidence-variables-title">变化的变量</h3>
				<p>只记录原文明确比较或改变的变量。</p>
			</div>
			<button
				class="btn btn--ghost btn--small"
				type="button"
				on:click={addVariable}
				disabled={variables.length >= 20}>添加变量</button
			>
		</div>
		{#if variables.length}
			<div class="variable-list">
				{#each variables as variable, index (index)}
					<div class="variable-row">
						<label
							><span>名称</span><input
								value={variable.name}
								on:input={(event) => updateVariable(index, 'name', event.currentTarget.value)}
							/></label
						>
						<label
							><span>参照值</span><input
								value={scalarText(variable.baseline_value)}
								on:input={(event) =>
									updateVariable(index, 'baseline_value', event.currentTarget.value)}
							/></label
						>
						<label
							><span>比较值</span><input
								value={scalarText(variable.target_value)}
								on:input={(event) =>
									updateVariable(index, 'target_value', event.currentTarget.value)}
							/></label
						>
						<label
							><span>单位</span><input
								value={variable.unit}
								on:input={(event) => updateVariable(index, 'unit', event.currentTarget.value)}
							/></label
						>
						<button
							class="btn btn--ghost btn--small"
							type="button"
							on:click={() => removeVariable(index)}
							aria-label={`移除变量 ${index + 1}`}>移除</button
						>
					</div>
				{/each}
			</div>
		{:else}<p class="empty">尚未记录变量。</p>{/if}
	</section>

	<section class="structured-section">
		<label class="check-row"
			><input type="checkbox" bind:checked={hasComparison} /><span
				>包含一组明确的参照和比较条件</span
			></label
		>
		{#if hasComparison}<div class="form-grid">
				<label><span>参照条件</span><input bind:value={baselineLabel} /></label><label
					><span>比较条件</span><input bind:value={targetLabel} /></label
				><label><span>比较轴（用逗号分隔）</span><input bind:value={axisNames} /></label><label
					class="check-row"
					><input type="checkbox" bind:checked={comparable} /><span>这些条件可以直接比较</span
					></label
				><label class="full"
					><span>不能直接比较的原因（每行一条）</span><textarea
						rows="2"
						bind:value={incomparabilityReasons}
					></textarea></label
				>
			</div>{/if}
	</section>

	<section class="structured-section">
		<label class="check-row"
			><input type="checkbox" bind:checked={hasResult} /><span>包含论文报告的结果</span></label
		>
		{#if hasResult}<div class="form-grid">
				<label><span>结果名称</span><input bind:value={outcome} /></label><label
					><span>方向</span><select bind:value={direction}
						><option value="increase">增加</option><option value="decrease">降低</option><option
							value="improve">改善</option
						><option value="worsen">恶化</option><option value="changed">发生变化</option><option
							value="no_change">无变化</option
						><option value="mixed">结果不一致</option><option value="unknown">未知</option></select
					></label
				><label><span>结果值</span><input bind:value={resultValue} /></label><label
					><span>结果单位</span><input bind:value={resultUnit} /></label
				><label><span>参照结果</span><input bind:value={resultBaseline} /></label><label
					><span>比较结果</span><input bind:value={resultTarget} /></label
				><label class="full"
					><span>原文中的结果描述</span><textarea rows="3" bind:value={resultText}
					></textarea></label
				>
			</div>{/if}
	</section>

	<section class="structured-section context-section">
		<h3>实验上下文</h3>
		<p>每行写“名称: 值”，只填原文支持的条件；没有内容的类别会保持为空。</p>
		<div class="form-grid">
			<label><span>材料</span><textarea rows="2" bind:value={materialContext}></textarea></label
			><label><span>样品</span><textarea rows="2" bind:value={sampleContext}></textarea></label
			><label><span>工艺</span><textarea rows="2" bind:value={processContext}></textarea></label
			><label><span>测试</span><textarea rows="2" bind:value={testContext}></textarea></label>
		</div>
	</section>

	<label
		><span>研究者备注（可选）</span><textarea rows="2" bind:value={authoringNote}></textarea></label
	>
	<footer>
		{#if formError}<p class="error" role="alert">{formError}</p>{/if}<button
			class="btn btn--primary"
			type="button"
			on:click={submit}
			disabled={saving}
			>{saving
				? '正在发布新版本...'
				: mode === 'revise'
					? '确认修订并发布'
					: '确认创建并发布'}</button
		>
	</footer>
</section>

<style>
	.authoring {
		display: grid;
		gap: 18px;
		min-width: 0;
	}
	header,
	footer,
	.section-heading,
	.source-meta {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 14px;
	}
	header span,
	.section-heading p,
	.source-meta span,
	.source-panel p {
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
	.source-panel,
	.structured-section {
		display: grid;
		gap: 12px;
		padding: 14px;
		border: 1px solid var(--border-default);
		background: var(--surface-subtle);
	}
	.source-panel textarea {
		min-height: 90px;
	}
	.form-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}
	.form-grid label,
	label {
		display: grid;
		gap: 5px;
		min-width: 0;
	}
	label > span {
		font-size: 12px;
		color: var(--text-secondary);
	}
	input,
	select,
	textarea {
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: 4px;
		padding: 8px 9px;
		background: var(--surface-default);
		color: var(--text-primary);
		font: inherit;
	}
	textarea {
		resize: vertical;
	}
	.full {
		grid-column: 1 / -1;
	}
	.variable-list {
		display: grid;
		gap: 8px;
	}
	.variable-row {
		display: grid;
		grid-template-columns: 1.2fr repeat(3, minmax(80px, 1fr)) auto;
		gap: 8px;
		align-items: end;
	}
	.check-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.check-row input {
		width: auto;
	}
	.empty {
		color: var(--text-secondary);
		font-size: 13px;
	}
	.error {
		color: var(--danger, #b42318);
		font-size: 13px;
		margin-right: auto;
	}
	@media (max-width: 720px) {
		.form-grid {
			grid-template-columns: 1fr;
		}
		.full {
			grid-column: auto;
		}
		.variable-row {
			grid-template-columns: 1fr 1fr;
		}
		.variable-row label:first-child {
			grid-column: 1 / -1;
		}
		.variable-row button {
			justify-self: start;
		}
		header,
		footer {
			flex-wrap: wrap;
		}
	}
</style>
