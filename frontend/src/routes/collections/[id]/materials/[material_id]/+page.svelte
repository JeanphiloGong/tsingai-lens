<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchMaterialResearchView,
		formatShortIdentifier,
		formatEvidenceBackedValue,
		getResearchViewStateTone,
		type ComparableGroup,
		type ConditionSeries,
		type CrossPaperMatrixRow,
		type EvidenceBackedValue,
		type MaterialPaperCoverage,
		type MaterialProfile,
		type ProcessParameterRange,
		type PropertySummary,
		type SampleMatrixColumn,
		type SampleMatrixRow
	} from '../../../../_shared/researchView';

	let materialProfile: MaterialProfile | null = null;
	let selectedEvidenceValue: EvidenceBackedValue | null = null;
	let loading = false;
	let error = '';
	let loadedKey = '';

	$: collectionId = $page.params.id ?? '';
	$: materialId = $page.params.material_id ?? '';
	$: loadKey = `${collectionId}:${materialId}`;
	$: sampleRows = materialProfile?.sample_matrix.rows ?? [];
	$: sampleColumns = sampleMatrixColumns(materialProfile, sampleRows);
	$: if (collectionId && materialId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadMaterialProfile();
	}

	async function loadMaterialProfile() {
		loading = true;
		error = '';
		selectedEvidenceValue = null;
		try {
			materialProfile = await fetchMaterialResearchView(collectionId, materialId);
		} catch (err) {
			materialProfile = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function materialPapers(): MaterialPaperCoverage[] {
		return materialProfile?.papers ?? [];
	}

	function sampleMatrixColumns(
		profile: MaterialProfile | null,
		rows: SampleMatrixRow[]
	): SampleMatrixColumn[] {
		if (profile?.sample_matrix.columns.length) {
			return profile.sample_matrix.columns;
		}

		const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row.values))));
		return keys.map((key) => ({
			column_id: key,
			key,
			label: key,
			kind: 'value',
			unit: null
		}));
	}

	function processRanges(): ProcessParameterRange[] {
		return materialProfile?.process_parameter_ranges ?? [];
	}

	function propertySummaries(): PropertySummary[] {
		return materialProfile?.measured_properties ?? [];
	}

	function materialComparisonGroups(): ComparableGroup[] {
		return materialProfile?.comparison_groups ?? [];
	}

	function materialConditionSeries(): ConditionSeries[] {
		return materialProfile?.condition_series ?? [];
	}

	function rowDocumentLabel(row: SampleMatrixRow): string {
		return formatShortIdentifier(row.document_id ?? row.evidence_refs[0]?.document_id);
	}

	function openEvidenceDrawer(value: EvidenceBackedValue) {
		selectedEvidenceValue = value;
	}

	function closeEvidenceDrawer() {
		selectedEvidenceValue = null;
	}

	function recordSummary(record: Record<string, string>) {
		const entries = Object.entries(record);
		if (!entries.length) return $t('research.emptyValue');
		return entries.map(([key, value]) => `${key}: ${value}`).join(' | ');
	}

	function listLabel(items: string[]) {
		return items.length ? items.slice(0, 6).join(', ') : $t('research.emptyValue');
	}

	function rangeLabel(item: ProcessParameterRange | PropertySummary) {
		if (item.display_range && item.display_range !== '--') return item.display_range;
		if (item.min_value !== null && item.max_value !== null) {
			const unit = item.unit ? ` ${item.unit}` : '';
			return `${item.min_value}${unit} - ${item.max_value}${unit}`;
		}
		return $t('research.emptyValue');
	}

	function groupStatusTone(group: ComparableGroup) {
		if (group.comparability_status === 'comparable') return 'success';
		if (group.comparability_status === 'limited') return 'warning';
		return 'danger';
	}

	function matrixRows(group: ComparableGroup): CrossPaperMatrixRow[] {
		return group.matrix.rows;
	}
</script>

<svelte:head>
	<title>{materialProfile?.canonical_name ?? $t('research.materialProfile.title')}</title>
</svelte:head>

<section class="material-profile-page fade-up">
	<header class="material-profile-header">
		<div>
			<a
				class="material-back-link"
				href={resolve('/collections/[id]/materials', { id: collectionId })}
				>{$t('research.materialProfile.back')}</a
			>
			<h2>{materialProfile?.canonical_name ?? materialId}</h2>
			{#if materialProfile?.aliases.length}
				<p>{$t('research.materials.aliases')}: {materialProfile.aliases.join(', ')}</p>
			{:else}
				<p>{$t('research.materialProfile.body')}</p>
			{/if}
		</div>
		<div class="material-profile-header__actions">
			{#if materialProfile}
				<span
					class={`status-badge status-badge--${getResearchViewStateTone(materialProfile.state)}`}
				>
					{$t(`research.state.${materialProfile.state}`)}
				</span>
			{/if}
			<button class="btn btn--ghost" type="button" on:click={loadMaterialProfile}>
				<span class="refresh-icon" aria-hidden="true"></span>
				{$t('research.materialProfile.refresh')}
			</button>
		</div>
	</header>

	{#if loading}
		<section class="material-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.materialProfile.loading')}</div>
		</section>
	{:else if error}
		<section class="material-state-card material-state-card--error" role="alert">
			<h3>{$t('research.materialProfile.errorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if !materialProfile}
		<section class="material-state-card">
			<h3>{$t('research.materialProfile.emptyTitle')}</h3>
			<p>{$t('research.materialProfile.emptyBody')}</p>
		</section>
	{:else}
		<section
			class="material-profile-summary"
			aria-label={$t('research.materialProfile.summaryTitle')}
		>
			<article>
				<span>{$t('research.materials.papers')}</span>
				<strong>{materialProfile.overview.paper_count || materialPapers().length}</strong>
			</article>
			<article>
				<span>{$t('research.overview.samples')}</span>
				<strong>{materialProfile.overview.sample_count || sampleRows.length}</strong>
			</article>
			<article>
				<span>{$t('research.materials.comparisons')}</span>
				<strong
					>{materialProfile.overview.comparison_count || materialComparisonGroups().length}</strong
				>
			</article>
			<article>
				<span>{$t('research.overview.evidence')}</span>
				<strong>{materialProfile.overview.evidence_count}</strong>
			</article>
		</section>

		{#if materialProfile.warnings.length}
			<section class="material-warning-card">
				<strong>{$t('research.warnings')}</strong>
				<ul>
					{#each materialProfile.warnings as warning (warning.warning_id)}
						<li>{warning.message}</li>
					{/each}
				</ul>
			</section>
		{/if}

		<section class="material-section">
			<div class="material-section__header">
				<h3>{$t('research.materialProfile.overview')}</h3>
			</div>
			<div class="material-overview-grid">
				<div>
					<span>{$t('research.overview.processes')}</span>
					<strong>{listLabel(materialProfile.overview.process_families)}</strong>
				</div>
				<div>
					<span>{$t('research.overview.properties')}</span>
					<strong>{listLabel(materialProfile.overview.measured_properties)}</strong>
				</div>
				<div>
					<span>{$t('research.overview.variables')}</span>
					<strong>{listLabel(materialProfile.overview.variable_axes)}</strong>
				</div>
			</div>
		</section>

		{#if materialPapers().length}
			<section class="material-section">
				<div class="material-section__header">
					<h3>{$t('research.materialProfile.papers')}</h3>
					<span>{$t('research.materials.paperCount', { count: materialPapers().length })}</span>
				</div>
				<div class="material-table-wrapper">
					<table class="material-table">
						<thead>
							<tr>
								<th>{$t('research.documents.document')}</th>
								<th>{$t('research.documents.state')}</th>
								<th>{$t('research.overview.samples')}</th>
								<th>{$t('research.overview.processes')}</th>
								<th>{$t('research.overview.properties')}</th>
								<th>{$t('research.documents.evidence')}</th>
								<th>{$t('research.documents.next')}</th>
							</tr>
						</thead>
						<tbody>
							{#each materialPapers() as paper (paper.document_id)}
								<tr>
									<td>
										<strong>{paper.title}</strong>
										<span title={paper.document_id}>{formatShortIdentifier(paper.document_id)}</span>
									</td>
									<td>
										<span
											class={`status-badge status-badge--${getResearchViewStateTone(paper.state)}`}
										>
											{$t(`research.state.${paper.state}`)}
										</span>
									</td>
									<td>{paper.sample_count}</td>
									<td>{listLabel(paper.process_families)}</td>
									<td>{listLabel(paper.measured_properties)}</td>
									<td>{paper.evidence_count}</td>
									<td>
										<a
											class="btn btn--ghost btn--small"
											href={resolve('/collections/[id]/documents/[document_id]', {
												id: collectionId,
												document_id: paper.document_id
											})}
										>
											{$t('research.documents.openPaper')}
										</a>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}

		{#if sampleRows.length}
			<section class="material-section">
				<div class="material-section__header">
					<h3>{$t('research.sampleMatrix.title')}</h3>
					<span>{$t('research.materials.sampleCount', { count: sampleRows.length })}</span>
				</div>
				<div class="material-table-wrapper">
					<table class="material-table">
						<thead>
							<tr>
								<th>{$t('research.sampleMatrix.sample')}</th>
								<th>{$t('research.documents.document')}</th>
								<th>{$t('research.comparison.process')}</th>
								{#each sampleColumns as column (column.column_id)}
									<th>{column.label}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each sampleRows as row (row.row_id)}
								<tr>
									<td>{row.sample_label}</td>
									<td>{rowDocumentLabel(row)}</td>
									<td>{recordSummary(row.process_context)}</td>
									{#each sampleColumns as column (column.column_id)}
										{@const value = row.values[column.key]}
										<td>
											{#if value}
												<button
													type="button"
													class={`material-value-button material-value-button--${value.status}`}
													on:click={() => openEvidenceDrawer(value)}
												>
													{formatEvidenceBackedValue(value)}
												</button>
											{:else}
												<span class="material-empty-value">--</span>
											{/if}
										</td>
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}

		{#if processRanges().length || propertySummaries().length}
			<section class="material-two-column">
				<div class="material-section">
					<div class="material-section__header">
						<h3>{$t('research.materialProfile.processRanges')}</h3>
					</div>
					{#if processRanges().length}
						<div class="range-list">
							{#each processRanges() as range (range.parameter)}
								<article>
									<strong>{range.parameter}</strong>
									<span>{rangeLabel(range)}</span>
									<small
										>{$t('research.materialProfile.rangeCoverage', {
											samples: range.sample_count,
											papers: range.document_count
										})}</small
									>
								</article>
							{/each}
						</div>
					{:else}
						<p class="material-empty-copy">{$t('research.materialProfile.noProcessRanges')}</p>
					{/if}
				</div>

				<div class="material-section">
					<div class="material-section__header">
						<h3>{$t('research.materialProfile.propertySummaries')}</h3>
					</div>
					{#if propertySummaries().length}
						<div class="range-list">
							{#each propertySummaries() as property (property.property)}
								<article>
									<strong>{property.property}</strong>
									<span>{rangeLabel(property)}</span>
									<small
										>{$t('research.materialProfile.rangeCoverage', {
											samples: property.sample_count,
											papers: property.document_count
										})}</small
									>
								</article>
							{/each}
						</div>
					{:else}
						<p class="material-empty-copy">{$t('research.materialProfile.noPropertySummaries')}</p>
					{/if}
				</div>
			</section>
		{/if}

		{#if materialComparisonGroups().length}
			<section class="material-section">
				<div class="material-section__header">
					<h3>{$t('research.materialProfile.comparisons')}</h3>
					<span
						>{$t('research.comparison.groupCount', {
							count: materialComparisonGroups().length
						})}</span
					>
				</div>
				<div class="material-comparison-list">
					{#each materialComparisonGroups() as group (group.group_id)}
						<article class="material-comparison-card">
							<div class="material-comparison-card__header">
								<div>
									<h4>{group.title}</h4>
									<p>
										{$t('research.comparison.variableAxis')}: {group.variable_axis ??
											$t('research.emptyValue')}
									</p>
								</div>
								<span class={`comparison-badge comparison-badge--${groupStatusTone(group)}`}>
									{$t(`research.comparison.status.${group.comparability_status}`)}
								</span>
							</div>
							<div class="material-chip-row">
								<span>{$t('research.comparison.process')}: {group.process_family}</span>
								<span
									>{$t('research.comparison.properties')}:
									{group.properties.join(', ') || $t('research.emptyValue')}</span
								>
								<span
									>{$t('research.comparison.fixedConditions')}:
									{recordSummary(group.fixed_conditions)}</span
								>
							</div>
							{#if matrixRows(group).length}
								<div class="material-table-wrapper">
									<table class="material-table material-table--compact">
										<thead>
											<tr>
												<th>{$t('research.documents.document')}</th>
												<th>{$t('research.sampleMatrix.sample')}</th>
												<th>{$t('research.comparison.variableValue')}</th>
												<th>{$t('research.comparison.testCondition')}</th>
												<th>{$t('research.comparison.result')}</th>
											</tr>
										</thead>
										<tbody>
											{#each matrixRows(group) as row (row.row_id)}
												<tr>
													<td>{row.document_id || '--'}</td>
													<td>{row.sample_label ?? row.sample_id ?? '--'}</td>
													<td>{row.variable_value ?? '--'}</td>
													<td>{row.test_condition ?? '--'}</td>
													<td>
														<button
															type="button"
															class={`material-value-button material-value-button--${row.result.status}`}
															on:click={() => openEvidenceDrawer(row.result)}
														>
															{formatEvidenceBackedValue(row.result)}
														</button>
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}
						</article>
					{/each}
				</div>
			</section>
		{/if}

		{#if materialConditionSeries().length}
			<section class="material-section">
				<div class="material-section__header">
					<h3>{$t('research.conditionSeries.title')}</h3>
					<span
						>{$t('research.materialProfile.seriesCount', {
							count: materialConditionSeries().length
						})}</span
					>
				</div>
				<div class="condition-series-list">
					{#each materialConditionSeries() as series (series.series_id)}
						<article class="condition-series-card">
							<strong>{series.property} / {series.condition_axis}</strong>
							<div>
								{#each series.points as point (point.point_id)}
									<button type="button" on:click={() => openEvidenceDrawer(point.result)}>
										{point.condition_value ?? '--'}{point.condition_unit
											? ` ${point.condition_unit}`
											: ''}
										-&gt; {formatEvidenceBackedValue(point.result)}
									</button>
								{/each}
							</div>
						</article>
					{/each}
				</div>
			</section>
		{/if}

		{#if selectedEvidenceValue}
			<aside class="material-evidence-drawer" aria-label={$t('research.evidence.title')}>
				<div class="material-evidence-drawer__header">
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
					<ul>
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
	{/if}
</section>

<style>
	.material-profile-page {
		width: 100%;
		max-width: 1320px;
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}

	.material-profile-header,
	.material-state-card,
	.material-section,
	.material-profile-summary article,
	.material-warning-card,
	.material-evidence-drawer {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.material-profile-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		padding: 24px;
	}

	.material-profile-header h2,
	.material-state-card h3,
	.material-section h3,
	.material-comparison-card h4,
	.material-evidence-drawer h3 {
		margin: 0;
		color: var(--text-primary);
	}

	.material-profile-header h2 {
		margin-top: 6px;
		font-size: 30px;
		line-height: 38px;
	}

	.material-profile-header p,
	.material-state-card p,
	.material-comparison-card p,
	.material-empty-copy {
		max-width: 780px;
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 23px;
	}

	.material-back-link {
		color: var(--accent-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
	}

	.material-profile-header__actions {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.material-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.material-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.material-profile-summary,
	.material-overview-grid,
	.material-two-column {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
	}

	.material-two-column {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}

	.material-profile-summary article,
	.material-overview-grid > div {
		display: grid;
		gap: 6px;
		min-width: 0;
		padding: 16px;
	}

	.material-overview-grid > div {
		border-radius: var(--radius-md);
		background: var(--surface-muted);
	}

	.material-profile-summary span,
	.material-overview-grid span,
	.material-section__header span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.material-profile-summary strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 30px;
	}

	.material-overview-grid strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
	}

	.material-section {
		display: grid;
		gap: 16px;
		padding: 18px;
		overflow: hidden;
	}

	.material-section__header,
	.material-comparison-card__header,
	.material-evidence-drawer__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.material-warning-card {
		display: grid;
		gap: 8px;
		padding: 16px;
		border-color: var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.material-warning-card ul {
		margin: 0;
		padding-left: 18px;
		font-size: 13px;
		line-height: 20px;
	}

	.material-table-wrapper {
		overflow-x: auto;
	}

	.material-table {
		width: 100%;
		min-width: 760px;
		border-collapse: collapse;
	}

	.material-table--compact {
		min-width: 620px;
	}

	.material-table th,
	.material-table td {
		padding: 12px;
		border-top: 1px solid var(--border-muted);
		text-align: left;
		vertical-align: top;
		font-size: 13px;
		line-height: 20px;
	}

	.material-table th {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 800;
		text-transform: uppercase;
	}

	.material-table td > span {
		display: block;
		margin-top: 4px;
		color: var(--text-tertiary);
	}

	.material-value-button,
	.condition-series-card button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 30px;
		padding: 5px 9px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.material-value-button--missing {
		color: var(--text-tertiary);
	}

	.material-value-button--conflicted {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.material-value-button--observed,
	.material-value-button--normalized {
		border-color: var(--success-border);
		background: var(--success-bg);
		color: var(--success-text);
	}

	.material-empty-value {
		color: var(--text-tertiary);
	}

	.range-list,
	.material-comparison-list,
	.condition-series-list {
		display: grid;
		gap: 12px;
	}

	.range-list article,
	.material-comparison-card,
	.condition-series-card {
		display: grid;
		gap: 8px;
		padding: 14px;
		border: 1px solid var(--border-muted);
		border-radius: var(--radius-md);
		background: var(--surface-muted);
	}

	.range-list span,
	.range-list small {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.material-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.material-chip-row span,
	.comparison-badge {
		display: inline-flex;
		align-items: center;
		min-height: 26px;
		padding: 4px 8px;
		border-radius: var(--radius-sm);
		background: var(--surface-card);
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

	.condition-series-card div {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.material-evidence-drawer {
		display: grid;
		gap: 14px;
		padding: 18px;
	}

	.material-evidence-drawer dl {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 10px;
		margin: 0;
	}

	.material-evidence-drawer dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.material-evidence-drawer dd {
		margin: 4px 0 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
	}

	.material-evidence-drawer ul {
		margin: 0;
		padding-left: 18px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	@media (max-width: 900px) {
		.material-profile-header,
		.material-section__header,
		.material-comparison-card__header {
			display: grid;
		}

		.material-profile-summary,
		.material-overview-grid,
		.material-two-column,
		.material-evidence-drawer dl {
			grid-template-columns: 1fr;
		}
	}
</style>
