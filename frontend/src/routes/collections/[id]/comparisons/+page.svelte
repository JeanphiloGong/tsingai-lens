<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionResearchView,
		formatEvidenceBackedValue,
		getResearchViewStateTone,
		type CollectionAggregation,
		type ComparableGroup,
		type CrossPaperMatrixRow,
		type EvidenceBackedValue
	} from '../../../_shared/researchView';

	let researchView: CollectionAggregation | null = null;
	let selectedGroupId = '';
	let selectedEvidenceValue: EvidenceBackedValue | null = null;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: researchGroups = researchView?.comparable_groups ?? [];
	$: comparisonArtifactsPending =
		Boolean(researchView) &&
		!researchGroups.length &&
		Boolean(
			researchView?.warnings.some((warning) => warning.code === 'comparison_projection_unavailable')
		);
	$: activeGroup =
		researchGroups.find((group) => group.group_id === selectedGroupId) ?? researchGroups[0] ?? null;
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadResearchComparison();
	}

	async function loadResearchComparison() {
		loading = true;
		error = '';
		selectedEvidenceValue = null;
		try {
			researchView = await fetchCollectionResearchView(collectionId);
			if (
				researchView.comparable_groups.length &&
				!researchView.comparable_groups.some((group) => group.group_id === selectedGroupId)
			) {
				selectedGroupId = researchView.comparable_groups[0].group_id;
			}
		} catch (err) {
			researchView = null;
			selectedGroupId = '';
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function groupStatusTone(group: ComparableGroup) {
		if (group.comparability_status === 'comparable') return 'success';
		if (group.comparability_status === 'limited') return 'warning';
		return 'danger';
	}

	function matrixRows(group: ComparableGroup): CrossPaperMatrixRow[] {
		if (group.matrix.rows.length) return group.matrix.rows;
		return (
			researchView?.cross_paper_matrices.find((matrix) => matrix.group_id === group.group_id)
				?.rows ?? []
		);
	}

	function recordSummary(record: Record<string, string>) {
		const entries = Object.entries(record);
		if (!entries.length) return $t('research.emptyValue');
		return entries.map(([key, value]) => `${key}: ${value}`).join(' | ');
	}

	function openEvidenceDrawer(value: EvidenceBackedValue) {
		selectedEvidenceValue = value;
	}

	function closeEvidenceDrawer() {
		selectedEvidenceValue = null;
	}
</script>

<svelte:head>
	<title>{$t('research.comparison.title')}</title>
</svelte:head>

<section class="research-comparison-page fade-up">
	<header class="research-comparison-header">
		<div>
			<h2>{$t('research.comparison.title')}</h2>
			<p>{$t('research.comparison.directBody')}</p>
			{#if researchView}
				<div class="comparison-meta-row">
					<span
						class={`status-badge status-badge--${getResearchViewStateTone(researchView.state)}`}
					>
						{$t(`research.state.${researchView.state}`)}
					</span>
					<span>{$t('research.comparison.groupCount', { count: researchGroups.length })}</span>
				</div>
			{/if}
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadResearchComparison}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('research.comparison.refresh')}
		</button>
	</header>

	{#if loading}
		<section class="comparison-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.comparison.loading')}</div>
		</section>
	{:else if error}
		<section class="comparison-state-card comparison-state-card--error" role="alert">
			<h3>{$t('research.comparison.errorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if comparisonArtifactsPending}
		<section class="comparison-state-card comparison-state-card--pending" role="status">
			<h3>{$t('research.comparison.pendingTitle')}</h3>
			<p>{$t('research.comparison.pendingBody')}</p>
			<div class="comparison-state-card__actions">
				<a class="btn btn--primary btn--small" href={resolve('/collections/[id]', { id: collectionId })}>
					{$t('research.comparison.openOverview')}
				</a>
				<button class="btn btn--ghost btn--small" type="button" on:click={loadResearchComparison}>
					{$t('research.comparison.refresh')}
				</button>
			</div>
		</section>
	{:else if !researchView || !researchGroups.length}
		<section class="comparison-state-card">
			<h3>{$t('research.comparison.emptyTitle')}</h3>
			<p>{$t('research.comparison.emptyBody')}</p>
		</section>
	{:else}
		<section class="research-comparison-layout" aria-label={$t('research.comparison.title')}>
			<aside class="research-group-list" aria-label={$t('research.comparison.groups')}>
				<div class="research-group-list__header">
					<h3>{$t('research.comparison.groups')}</h3>
					<span>{$t('research.comparison.groupCount', { count: researchGroups.length })}</span>
				</div>
				{#each researchGroups as group (group.group_id)}
					<button
						type="button"
						class:selected={activeGroup?.group_id === group.group_id}
						class="research-group-card"
						on:click={() => (selectedGroupId = group.group_id)}
					>
						<span class={`comparison-badge comparison-badge--${groupStatusTone(group)}`}>
							{$t(`research.comparison.status.${group.comparability_status}`)}
						</span>
						<strong>{group.title}</strong>
						<small>{group.material_system} / {group.process_family}</small>
						{#if group.variable_axis}
							<small>{$t('research.comparison.variableAxis')}: {group.variable_axis}</small>
						{/if}
					</button>
				{/each}
			</aside>

			{#if activeGroup}
				<section class="research-matrix-panel">
					<div class="research-matrix-header">
						<div>
							<h3>{activeGroup.title}</h3>
							<p>
								{$t('research.comparison.fixedConditions')}:
								{recordSummary(activeGroup.fixed_conditions)}
							</p>
						</div>
						<span class={`comparison-badge comparison-badge--${groupStatusTone(activeGroup)}`}>
							{$t(`research.comparison.status.${activeGroup.comparability_status}`)}
						</span>
					</div>

					<div class="research-chip-row">
						<span>{$t('research.comparison.material')}: {activeGroup.material_system}</span>
						<span>{$t('research.comparison.process')}: {activeGroup.process_family}</span>
						<span
							>{$t('research.comparison.properties')}:
							{activeGroup.properties.join(', ') || $t('research.emptyValue')}</span
						>
						<span>{$t('research.comparison.documents')}: {activeGroup.documents.length}</span>
						<span>{$t('research.comparison.samples')}: {activeGroup.samples.length}</span>
					</div>

					{#if activeGroup.warnings.length}
						<div class="comparison-alert comparison-alert--warning" role="status">
							<strong>{$t('research.warnings')}</strong>
							<span>{activeGroup.warnings.map((warning) => warning.message).join(' | ')}</span>
						</div>
					{/if}

					{#if matrixRows(activeGroup).length}
						<div class="research-matrix-table-wrapper">
							<table class="research-matrix-table">
								<thead>
									<tr>
										<th>{$t('research.documents.document')}</th>
										<th>{$t('research.sampleMatrix.sample')}</th>
										<th>{$t('research.comparison.material')}</th>
										<th>{$t('research.comparison.process')}</th>
										<th>{$t('research.comparison.variableValue')}</th>
										<th>{$t('research.comparison.testCondition')}</th>
										<th>{$t('research.comparison.result')}</th>
										<th>{$t('research.comparison.evidence')}</th>
									</tr>
								</thead>
								<tbody>
									{#each matrixRows(activeGroup) as row (row.row_id)}
										<tr>
											<td>{row.document_id || '--'}</td>
											<td>{row.sample_label ?? row.sample_id ?? '--'}</td>
											<td>{row.material}</td>
											<td>{recordSummary(row.process_context)}</td>
											<td>{row.variable_value ?? '--'}</td>
											<td>{row.test_condition ?? '--'}</td>
											<td>
												<button
													type="button"
													class={`matrix-value-button matrix-value-button--${row.result.status}`}
													on:click={() => openEvidenceDrawer(row.result)}
												>
													{formatEvidenceBackedValue(row.result)}
												</button>
											</td>
											<td>
												<button
													class="btn btn--ghost btn--small"
													type="button"
													on:click={() => openEvidenceDrawer(row.result)}
												>
													{$t('research.evidence.open')}
												</button>
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{:else}
						<div class="comparison-empty-filter" role="status">
							{$t('research.comparison.emptyMatrix')}
						</div>
					{/if}

					{#if selectedEvidenceValue}
						<aside class="research-evidence-drawer" aria-label={$t('research.evidence.title')}>
							<div class="research-evidence-drawer__header">
								<h3>{$t('research.evidence.title')}</h3>
								<button type="button" on:click={closeEvidenceDrawer}>
									{$t('research.evidence.close')}
								</button>
							</div>
							<dl>
								<div>
									<dt>{$t('research.comparison.result')}</dt>
									<dd>{formatEvidenceBackedValue(selectedEvidenceValue)}</dd>
								</div>
								<div>
									<dt>{$t('research.evidence.status')}</dt>
									<dd>{$t(`research.valueStatus.${selectedEvidenceValue.status}`)}</dd>
								</div>
								<div>
									<dt>{$t('research.evidence.confidence')}</dt>
									<dd>{selectedEvidenceValue.confidence ?? '--'}</dd>
								</div>
								<div>
									<dt>{$t('research.evidence.duplicates')}</dt>
									<dd>{selectedEvidenceValue.duplicate_count}</dd>
								</div>
							</dl>
							{#if selectedEvidenceValue.evidence_refs.length}
								<ul class="research-evidence-list">
									{#each selectedEvidenceValue.evidence_refs as ref (ref.evidence_ref_id)}
										<li>
											<strong>{ref.evidence_ref_id}</strong>
											<span>{ref.document_id ?? '--'} / {ref.locator ?? '--'}</span>
										</li>
									{/each}
								</ul>
							{:else}
								<p>{$t('research.evidence.missing')}</p>
							{/if}
						</aside>
					{/if}
				</section>
			{/if}
		</section>
	{/if}
</section>

<style>
	.research-comparison-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 24px;
	}

	.research-comparison-header,
	.comparison-state-card,
	.research-group-list,
	.research-matrix-panel,
	.research-evidence-drawer {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.research-comparison-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
		padding: 24px;
	}

	.research-comparison-header h2,
	.comparison-state-card h3,
	.research-group-list__header h3,
	.research-matrix-header h3,
	.research-evidence-drawer__header h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.research-comparison-header h2 {
		font-size: 30px;
		line-height: 38px;
	}

	.research-comparison-header p,
	.comparison-state-card p,
	.research-matrix-header p {
		max-width: 780px;
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.comparison-meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
		margin-top: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.comparison-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.comparison-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.comparison-state-card--pending {
		border-color: var(--warning-border);
		background: var(--warning-bg);
	}

	.comparison-state-card__actions {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		margin-top: 8px;
	}

	.research-comparison-layout {
		display: grid;
		grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
		gap: 18px;
		align-items: start;
	}

	.research-group-list {
		display: grid;
		gap: 10px;
		padding: 14px;
	}

	.research-group-list__header,
	.research-matrix-header,
	.research-evidence-drawer__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.research-group-list__header h3,
	.research-matrix-header h3,
	.research-evidence-drawer__header h3 {
		font-size: 18px;
		line-height: 24px;
	}

	.research-group-list__header span {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-group-card {
		display: grid;
		gap: 8px;
		width: 100%;
		padding: 14px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
		color: var(--text-primary);
		text-align: left;
		cursor: pointer;
	}

	.research-group-card:hover,
	.research-group-card.selected {
		border-color: var(--brand-border);
		background: var(--brand-soft);
	}

	.research-group-card strong {
		overflow-wrap: anywhere;
		font-size: 14px;
		line-height: 20px;
	}

	.research-group-card small {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-matrix-panel {
		display: grid;
		gap: 16px;
		padding: 18px;
		min-width: 0;
	}

	.research-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.research-chip-row span,
	.comparison-badge {
		display: inline-flex;
		min-height: 26px;
		align-items: center;
		padding: 4px 9px;
		border-radius: 999px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.comparison-badge--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.comparison-badge--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.comparison-badge--danger {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.comparison-alert {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		padding: 10px 12px;
		border: 1px solid var(--warning-border);
		border-radius: var(--radius-md);
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 14px;
		line-height: 22px;
	}

	.research-matrix-table-wrapper {
		max-width: 100%;
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background:
			linear-gradient(90deg, var(--surface-card) 28%, rgba(255, 255, 255, 0)),
			linear-gradient(270deg, var(--surface-card) 28%, rgba(255, 255, 255, 0)) 100% 0,
			linear-gradient(90deg, rgba(15, 23, 42, 0.08), rgba(15, 23, 42, 0)),
			linear-gradient(270deg, rgba(15, 23, 42, 0.08), rgba(15, 23, 42, 0)) 100% 0;
		background-attachment: local, local, scroll, scroll;
		background-repeat: no-repeat;
		background-size:
			32px 100%,
			32px 100%,
			12px 100%,
			12px 100%;
	}

	.research-matrix-table {
		width: 100%;
		min-width: 980px;
		border-collapse: collapse;
		font-size: 14px;
	}

	.research-matrix-table th,
	.research-matrix-table td {
		padding: 12px 14px;
		border-top: 1px solid var(--border-default);
		text-align: left;
		vertical-align: middle;
	}

	.research-matrix-table th {
		color: var(--text-secondary);
		font-size: 13px;
		font-weight: 700;
		background: var(--bg-subtle);
	}

	.matrix-value-button {
		display: inline-flex;
		min-height: 32px;
		align-items: center;
		justify-content: center;
		padding: 4px 10px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		cursor: pointer;
	}

	.matrix-value-button--missing {
		color: var(--text-secondary);
		background: var(--bg-subtle);
	}

	.matrix-value-button--conflicted {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.research-evidence-drawer {
		display: grid;
		gap: 12px;
		padding: 14px;
		border-color: var(--brand-border);
	}

	.research-evidence-drawer__header button {
		border: 0;
		background: transparent;
		color: var(--brand-primary);
		font-size: 13px;
		font-weight: 700;
		cursor: pointer;
	}

	.research-evidence-drawer dl {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 10px;
		margin: 0;
	}

	.research-evidence-drawer dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.research-evidence-drawer dd {
		margin: 0;
		overflow-wrap: anywhere;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-evidence-list {
		display: grid;
		gap: 8px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.research-evidence-list li {
		display: grid;
		gap: 3px;
		padding: 10px;
		border-radius: var(--radius-md);
		background: var(--bg-subtle);
		font-size: 13px;
		line-height: 20px;
	}

	@media (max-width: 900px) {
		.research-comparison-header,
		.research-comparison-layout {
			display: grid;
			grid-template-columns: 1fr;
		}

		.research-matrix-panel {
			width: 100%;
			max-width: calc(100vw - 32px);
		}

		.research-matrix-table {
			min-width: 760px;
		}

		.research-evidence-drawer dl {
			grid-template-columns: 1fr 1fr;
		}
	}

	@media (max-width: 520px) {
		.research-comparison-header,
		.research-matrix-panel,
		.research-group-list {
			padding: 16px;
		}
	}
</style>
