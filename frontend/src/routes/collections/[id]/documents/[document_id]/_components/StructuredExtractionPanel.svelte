<script lang="ts">
	import { t } from '../../../../../_shared/i18n';
	import type {
		DocumentWorkbenchModel,
		WorkbenchKeyResultCard,
		WorkbenchMethodRow,
		WorkbenchSummaryCard,
		WorkbenchTab
	} from '../../../../../_shared/documents';
	import EvidenceCard from './EvidenceCard.svelte';
	import ExtractionTabs from './ExtractionTabs.svelte';
	import ResultTable from './ResultTable.svelte';

	export let model: DocumentWorkbenchModel;
	export let activeTab: WorkbenchTab = 'overview';
	export let selectedItemId = '';
	export let onSelectItem: (id: string, tab?: WorkbenchTab) => void = () => {};
	export let onJumpToSource: (sourceSpanId: string) => void = () => {};
	export let onOpenTab: (tab: WorkbenchTab) => void = () => {};

	type OverviewMethodRow = {
		row: WorkbenchMethodRow;
		index: number;
	};

	type OverviewGroup = {
		id: string;
		titleKey: string;
		cards: WorkbenchSummaryCard[];
		rows: OverviewMethodRow[];
		results: WorkbenchKeyResultCard[];
	};

	$: overviewGroups = buildOverviewGroups(model);

	function methodRowsAt(currentModel: DocumentWorkbenchModel, ...indexes: number[]): OverviewMethodRow[] {
		return indexes
			.map((index) => ({ row: currentModel.method_rows[index], index }))
			.filter((item): item is OverviewMethodRow => Boolean(item.row));
	}

	function buildOverviewGroups(currentModel: DocumentWorkbenchModel): OverviewGroup[] {
		return [
			{
				id: 'paper-scope',
				titleKey: 'workbench.paperScope',
				cards: currentModel.summary_cards.slice(0, 2),
				rows: [],
				results: []
			},
			{
				id: 'experimental-objects',
				titleKey: 'workbench.experimentalObjects',
				cards: currentModel.summary_cards.slice(2, 3),
				rows: methodRowsAt(currentModel, 1),
				results: []
			},
			{
				id: 'processing-conditions',
				titleKey: 'workbench.processingConditions',
				cards: currentModel.summary_cards.slice(3, 4),
				rows: methodRowsAt(currentModel, 0, 2),
				results: []
			},
			{
				id: 'test-methods',
				titleKey: 'workbench.testMethods',
				cards: [],
				rows: methodRowsAt(currentModel, 3, 4),
				results: []
			},
			{
				id: 'measured-results',
				titleKey: 'workbench.measuredResults',
				cards: currentModel.summary_cards.slice(4, 5),
				rows: [],
				results: currentModel.key_results
			}
		];
	}

	function selectMethod(index: number) {
		onSelectItem(`method-${index}`, 'overview');
	}

	function handleMethodKeydown(event: KeyboardEvent, index: number) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			selectMethod(index);
		}
	}
</script>

<section class="extraction-panel" aria-label={$t('workbench.extractionLabel')}>
	<ExtractionTabs {activeTab} onChange={onOpenTab} />

	<div class="panel-content">
		{#if activeTab === 'overview'}
			{#each overviewGroups as group}
				<section class="understanding-section" aria-labelledby={`overview-${group.id}`}>
					<div class="section-title-row">
						<h3 id={`overview-${group.id}`}>{$t(group.titleKey)}</h3>
					</div>

					{#each group.cards as card}
						<article class:selected={selectedItemId === card.id} class="info-card">
							<button
								class="card-main"
								type="button"
								on:click={() => onSelectItem(card.id, 'overview')}
							>
								<div class="card-title-row">
									<h3>{card.title}</h3>
									<span>{card.source_label}</span>
								</div>
								<p>{card.body}</p>
							</button>
							<button
								class="source-link"
								type="button"
								on:click={() => onJumpToSource(card.source_span_id)}
							>
								{$t('workbench.jumpToSource')}
							</button>
						</article>
					{/each}

					{#if group.rows.length}
						<section class="info-card method-card">
							<table class="method-table">
								<tbody>
									{#each group.rows as item}
										<tr
											tabindex="0"
											role="button"
											class:selected={selectedItemId === `method-${item.index}`}
											on:click={() => selectMethod(item.index)}
											on:keydown={(event) => handleMethodKeydown(event, item.index)}
										>
											<th>{item.row.label}</th>
											<td>{item.row.value}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</section>
					{/if}

					{#if group.results.length}
						<section class="key-results" aria-labelledby="key-results-title">
							<div class="section-title-row">
								<h3 id="key-results-title">{$t('workbench.keyResults')}</h3>
								<span class="badge">{$t('workbench.keyFinding')}</span>
							</div>
							<div class="key-result-grid">
								{#each group.results as result}
									<button
										type="button"
										class="key-result-card"
										on:click={() => onJumpToSource(result.source_span_id)}
									>
										<span>{result.label}</span>
										<strong>{result.value}</strong>
										<small>{result.trend}</small>
									</button>
								{/each}
							</div>
						</section>
					{/if}
				</section>
			{/each}
		{:else if activeTab === 'results'}
			<ResultTable
				rows={model.result_rows}
				selectedId={selectedItemId}
				onSelect={(id) => onSelectItem(id, 'results')}
				{onJumpToSource}
			/>
		{:else if activeTab === 'evidence'}
			{#each model.evidence_cards as card}
				<EvidenceCard
					{card}
					selected={selectedItemId === card.id}
					onSelect={(id) => onSelectItem(id, 'evidence')}
					{onJumpToSource}
				/>
			{/each}
		{/if}
	</div>
</section>

<style>
	.extraction-panel {
		display: flex;
		min-width: 0;
		height: 100%;
		overflow: hidden;
		flex-direction: column;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		background: #ffffff;
	}

	.panel-content {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		background: #ffffff;
	}

	.info-card,
	.key-results {
		position: relative;
		margin-bottom: 12px;
		padding: 16px;
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		background: #ffffff;
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
		transition:
			border-color 0.16s ease,
			box-shadow 0.16s ease,
			background 0.16s ease;
	}

	.understanding-section {
		display: grid;
		gap: 10px;
		margin-bottom: 14px;
		padding-bottom: 14px;
		border-bottom: 1px solid #e2e8f0;
	}

	.understanding-section:last-child {
		margin-bottom: 0;
		padding-bottom: 0;
		border-bottom: 0;
	}

	.understanding-section > .section-title-row {
		margin-bottom: 0;
	}

	.understanding-section .info-card,
	.understanding-section .key-results {
		margin-bottom: 0;
	}

	.info-card:hover,
	.key-results:hover {
		border-color: #bfdbfe;
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
	}

	.info-card.selected {
		border: 1.5px solid #2563eb;
		background: #f8fbff;
		box-shadow: 0 8px 24px rgba(37, 99, 235, 0.12);
	}

	.card-main {
		display: block;
		width: 100%;
		padding: 0;
		border: 0;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}

	.card-title-row,
	.section-title-row {
		display: flex;
		margin-bottom: 8px;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	h3 {
		margin: 0;
		color: #0f172a;
		font-size: 15px;
		font-weight: 700;
		line-height: 22px;
	}

	.card-title-row span {
		color: #64748b;
		font-size: 12px;
		font-weight: 500;
		white-space: nowrap;
	}

	p {
		margin: 0;
		color: #334155;
		font-size: 14px;
		line-height: 22px;
	}

	.source-link {
		margin-top: 8px;
		padding: 4px 8px;
		border: 0;
		border-radius: 6px;
		background: transparent;
		color: #2563eb;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
	}

	.source-link:hover {
		background: #eff6ff;
	}

	.badge {
		display: inline-flex;
		height: 22px;
		align-items: center;
		padding: 0 8px;
		border-radius: 999px;
		background: #dcfce7;
		color: #15803d;
		font-size: 11px;
		font-weight: 700;
	}

	.key-result-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
	}

	.key-result-card {
		display: grid;
		gap: 8px;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
		background: #ffffff;
		text-align: left;
		cursor: pointer;
	}

	.key-result-card span {
		color: #334155;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.key-result-card strong {
		margin: 0;
		color: #2563eb;
		font-size: 24px;
		font-weight: 800;
		line-height: 1;
	}

	.key-result-card small {
		color: #15803d;
		font-size: 11px;
		font-weight: 700;
	}

	.method-card {
		padding-bottom: 16px;
	}

	.method-table {
		width: 100%;
		overflow: hidden;
		border: 1px solid #e2e8f0;
		border-collapse: separate;
		border-spacing: 0;
		border-radius: 10px;
		font-size: 13px;
	}

	.method-table tr {
		height: 42px;
		cursor: pointer;
	}

	.method-table tr.selected th,
	.method-table tr.selected td {
		background: #f8fbff;
	}

	.method-table th,
	.method-table td {
		padding: 10px 12px;
		border-bottom: 1px solid #e2e8f0;
		text-align: left;
		vertical-align: top;
	}

	.method-table tr:last-child th,
	.method-table tr:last-child td {
		border-bottom: 0;
	}

	.method-table th {
		width: 110px;
		background: #f8fafc;
		color: #334155;
		font-weight: 600;
	}

	.method-table td {
		color: #334155;
	}

	@media (max-width: 520px) {
		.key-result-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
