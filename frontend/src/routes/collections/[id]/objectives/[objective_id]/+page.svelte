<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchObjectiveResearchView,
		getResearchViewStateTone,
		type ObjectivePaperFrame,
		type ObjectiveResearchView
	} from '../../../../_shared/researchView';

	let objectiveView: ObjectiveResearchView | null = null;
	let loading = false;
	let error = '';
	let loadedKey = '';

	$: collectionId = $page.params.id ?? '';
	$: objectiveId = $page.params.objective_id ?? '';
	$: loadKey = `${collectionId}:${objectiveId}`;
	$: frames = objectiveView?.paper_frames ?? [];
	$: relevantFrameCount = frames.filter((frame) => frame.relevance !== 'irrelevant').length;
	$: tableCount = frames.reduce(
		(total, frame) => total + frame.relevant_tables.length + frame.excluded_tables.length,
		0
	);
	$: routeCount = objectiveView?.evidence_routes.length ?? 0;
	$: evidenceUnitCount = objectiveView?.evidence_units.length ?? 0;
	$: if (collectionId && objectiveId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadObjectiveView();
	}

	async function loadObjectiveView() {
		loading = true;
		error = '';
		try {
			objectiveView = await fetchObjectiveResearchView(collectionId, objectiveId);
		} catch (err) {
			objectiveView = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function listLabel(items: string[]) {
		return items.length ? items.join(', ') : $t('research.emptyValue');
	}

	function frameTitle(frame: ObjectivePaperFrame) {
		return frame.title || frame.source_filename || frame.document_id;
	}

	function confidenceLabel(value: number) {
		return value > 0 ? `${Math.round(value * 100)}%` : $t('research.emptyValue');
	}

	function boolState(value: boolean) {
		return value
			? $t('research.objectiveWorkspace.ready')
			: $t('research.objectiveWorkspace.pending');
	}

	function routeSchemaLabel(value: Record<string, unknown>) {
		const headers = value.column_headers;
		if (Array.isArray(headers) && headers.length) {
			return headers.map((item) => String(item)).join(', ');
		}
		return Object.keys(value).length ? JSON.stringify(value) : $t('research.emptyValue');
	}
</script>

<svelte:head>
	<title>{objectiveView?.objective.question || $t('research.objectiveWorkspace.title')}</title>
</svelte:head>

<section class="objective-workspace fade-up">
	<a
		class="back-link"
		href={resolve('/collections/[id]/objectives', {
			id: collectionId
		})}
	>
		{$t('research.objectiveWorkspace.back')}
	</a>

	{#if loading}
		<section class="objective-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.objectiveWorkspace.loading')}</div>
		</section>
	{:else if error}
		<section class="objective-state-card objective-state-card--error" role="alert">
			<h2>{$t('research.objectiveWorkspace.errorTitle')}</h2>
			<p>{error}</p>
		</section>
	{:else if !objectiveView}
		<section class="objective-state-card">
			<h2>{$t('research.objectiveWorkspace.emptyTitle')}</h2>
			<p>{$t('research.objectiveWorkspace.emptyBody')}</p>
		</section>
	{:else}
		<header class="objective-hero">
			<div class="objective-hero__main">
				<p class="objective-eyebrow">{$t('research.objectiveWorkspace.eyebrow')}</p>
				<h2>{objectiveView.objective.question}</h2>
				<p>
					{objectiveView.objective.comparison_intent || $t('research.objectiveWorkspace.noIntent')}
				</p>
				<div class="objective-chip-row">
					{#each objectiveView.objective.material_scope as material (material)}
						<span>{material}</span>
					{/each}
					{#each objectiveView.objective.process_axes as axis (axis)}
						<span>{axis}</span>
					{/each}
					{#each objectiveView.objective.property_axes as axis (axis)}
						<span>{axis}</span>
					{/each}
				</div>
			</div>
			<div class="objective-hero__status">
				<span class={`status-badge status-badge--${getResearchViewStateTone(objectiveView.state)}`}>
					{$t(`research.state.${objectiveView.state}`)}
				</span>
				<strong>{confidenceLabel(objectiveView.objective.confidence)}</strong>
				<span>{$t('research.objectives.confidence')}</span>
			</div>
		</header>

		<section class="objective-summary-grid" aria-label={$t('research.objectiveWorkspace.summary')}>
			<article>
				<span>{$t('research.objectiveWorkspace.relevantPapers')}</span>
				<strong>{relevantFrameCount}</strong>
			</article>
			<article>
				<span>{$t('research.objectives.paperFrames')}</span>
				<strong>{frames.length}</strong>
			</article>
			<article>
				<span>{$t('research.objectives.routes')}</span>
				<strong>{routeCount}</strong>
			</article>
			<article>
				<span>{$t('research.objectives.evidenceUnits')}</span>
				<strong>{evidenceUnitCount}</strong>
			</article>
		</section>

		<section class="objective-section">
			<div class="section-heading">
				<h3>{$t('research.objectiveWorkspace.contextTitle')}</h3>
				<span>{boolState(objectiveView.readiness.objectives_ready)}</span>
			</div>
			<div class="context-grid">
				<div>
					<span>{$t('research.objectives.materialScope')}</span>
					<strong>{listLabel(objectiveView.objective.material_scope)}</strong>
				</div>
				<div>
					<span>{$t('research.objectives.processAxes')}</span>
					<strong>{listLabel(objectiveView.objective.process_axes)}</strong>
				</div>
				<div>
					<span>{$t('research.objectives.propertyAxes')}</span>
					<strong>{listLabel(objectiveView.objective.property_axes)}</strong>
				</div>
				<div>
					<span>{$t('research.objectiveWorkspace.variableAxes')}</span>
					<strong>{listLabel(objectiveView.objective_context?.variable_process_axes ?? [])}</strong>
				</div>
			</div>
		</section>

		<section class="objective-section">
			<div class="section-heading">
				<h3>{$t('research.objectiveWorkspace.framesTitle')}</h3>
				<span>{$t('research.objectiveWorkspace.tableCount', { count: tableCount })}</span>
			</div>
			{#if frames.length}
				<div class="frame-list">
					{#each frames as frame (frame.frame_id)}
						<article class="frame-card">
							<div class="frame-card__header">
								<div>
									<h4>{frameTitle(frame)}</h4>
									<p>{frame.background || $t('research.objectiveWorkspace.noBackground')}</p>
								</div>
								<div class="frame-card__badges">
									<span>{frame.relevance}</span>
									<span>{frame.paper_role}</span>
								</div>
							</div>
							<dl>
								<div>
									<dt>{$t('research.objectives.materialScope')}</dt>
									<dd>{listLabel(frame.material_match)}</dd>
								</div>
								<div>
									<dt>{$t('research.objectiveWorkspace.changedVariables')}</dt>
									<dd>{listLabel(frame.changed_variables)}</dd>
								</div>
								<div>
									<dt>{$t('research.objectiveWorkspace.measuredScope')}</dt>
									<dd>{listLabel(frame.measured_property_scope)}</dd>
								</div>
								<div>
									<dt>{$t('research.objectiveWorkspace.relevantSections')}</dt>
									<dd>{listLabel(frame.relevant_sections)}</dd>
								</div>
								<div>
									<dt>{$t('research.objectiveWorkspace.relevantTables')}</dt>
									<dd>{listLabel(frame.relevant_tables)}</dd>
								</div>
								<div>
									<dt>{$t('research.objectiveWorkspace.excludedTables')}</dt>
									<dd>{listLabel(frame.excluded_tables)}</dd>
								</div>
							</dl>
						</article>
					{/each}
				</div>
			{:else}
				<div class="empty-panel">{$t('research.objectiveWorkspace.noFrames')}</div>
			{/if}
		</section>

		<section class="objective-section">
			<div class="section-heading">
				<h3>{$t('research.objectiveWorkspace.routesTitle')}</h3>
				<span>{boolState(objectiveView.readiness.routes_ready)}</span>
			</div>
			{#if objectiveView.evidence_routes.length}
				<div class="route-table-wrap">
					<table class="route-table">
						<thead>
							<tr>
								<th>{$t('research.objectiveWorkspace.source')}</th>
								<th>{$t('research.objectiveWorkspace.role')}</th>
								<th>{$t('research.objectiveWorkspace.extractable')}</th>
								<th>{$t('research.objectiveWorkspace.schema')}</th>
							</tr>
						</thead>
						<tbody>
							{#each objectiveView.evidence_routes as route (route.route_id)}
								<tr>
									<td>{route.source_kind}: {route.source_ref}</td>
									<td>{route.role}</td>
									<td>{boolState(route.extractable)}</td>
									<td>{routeSchemaLabel(route.table_schema)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<div class="empty-panel">{$t('research.objectiveWorkspace.noRoutes')}</div>
			{/if}
		</section>

		<section class="objective-section objective-section--two">
			<div>
				<div class="section-heading">
					<h3>{$t('research.objectiveWorkspace.evidenceUnitsTitle')}</h3>
					<span>{boolState(objectiveView.readiness.evidence_units_ready)}</span>
				</div>
				<div class="empty-panel">{$t('research.objectiveWorkspace.noEvidenceUnits')}</div>
			</div>
			<div>
				<div class="section-heading">
					<h3>{$t('research.objectiveWorkspace.logicChainTitle')}</h3>
					<span>{boolState(objectiveView.readiness.logic_chain_ready)}</span>
				</div>
				{#if objectiveView.logic_chain}
					<p class="logic-summary">
						{objectiveView.logic_chain.summary || objectiveView.logic_chain.question}
					</p>
				{:else}
					<div class="empty-panel">{$t('research.objectiveWorkspace.noLogicChain')}</div>
				{/if}
			</div>
		</section>
	{/if}
</section>

<style>
	.objective-workspace {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 18px;
	}

	.back-link {
		width: fit-content;
		color: var(--color-accent);
		font-size: 14px;
		text-decoration: none;
	}

	.objective-hero,
	.objective-state-card,
	.objective-summary-grid article,
	.objective-section,
	.frame-card {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.objective-hero {
		display: flex;
		justify-content: space-between;
		gap: 24px;
		padding: 26px;
	}

	.objective-hero__main {
		display: grid;
		gap: 10px;
	}

	.objective-eyebrow {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		text-transform: uppercase;
	}

	.objective-hero h2,
	.objective-state-card h2,
	.objective-section h3,
	.frame-card h4 {
		margin: 0;
		color: var(--text-primary);
	}

	.objective-hero h2 {
		max-width: 900px;
		font-size: 30px;
		line-height: 38px;
	}

	.objective-hero p,
	.frame-card p,
	.logic-summary {
		margin: 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.objective-hero__status {
		min-width: 150px;
		display: grid;
		justify-items: end;
		align-content: start;
		gap: 8px;
		color: var(--text-secondary);
	}

	.objective-hero__status strong {
		color: var(--text-primary);
		font-size: 28px;
		line-height: 34px;
	}

	.objective-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.objective-chip-row span,
	.frame-card__badges span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 5px 10px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--bg-subtle);
	}

	.objective-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.objective-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.objective-summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
	}

	.objective-summary-grid article,
	.objective-section {
		padding: 20px;
	}

	.objective-summary-grid article {
		display: grid;
		gap: 4px;
	}

	.objective-summary-grid span,
	.context-grid span,
	.section-heading span,
	.frame-card dt,
	.route-table th {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.objective-summary-grid strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 30px;
	}

	.objective-section {
		display: grid;
		gap: 16px;
	}

	.section-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.context-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
	}

	.context-grid div {
		display: grid;
		gap: 5px;
		min-width: 0;
	}

	.context-grid strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.frame-list {
		display: grid;
		gap: 12px;
	}

	.frame-card {
		display: grid;
		gap: 16px;
		padding: 18px;
		box-shadow: none;
	}

	.frame-card__header {
		display: flex;
		justify-content: space-between;
		gap: 12px;
	}

	.frame-card__badges {
		display: flex;
		flex-wrap: wrap;
		align-content: flex-start;
		justify-content: flex-end;
		gap: 6px;
	}

	.frame-card dl {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
		margin: 0;
	}

	.frame-card dd {
		margin: 4px 0 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.route-table-wrap {
		overflow-x: auto;
	}

	.route-table {
		width: 100%;
		border-collapse: collapse;
	}

	.route-table th,
	.route-table td {
		border-bottom: 1px solid var(--border-default);
		padding: 10px 8px;
		text-align: left;
		vertical-align: top;
	}

	.route-table td {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.empty-panel {
		border: 1px dashed var(--border-default);
		border-radius: var(--radius-md);
		padding: 16px;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		background: var(--bg-subtle);
	}

	.objective-section--two {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}

	.objective-section--two > div {
		display: grid;
		gap: 14px;
	}

	@media (max-width: 860px) {
		.objective-hero,
		.frame-card__header {
			flex-direction: column;
		}

		.objective-hero__status {
			justify-items: start;
		}

		.objective-summary-grid,
		.context-grid,
		.frame-card dl,
		.objective-section--two {
			grid-template-columns: 1fr;
		}
	}
</style>
