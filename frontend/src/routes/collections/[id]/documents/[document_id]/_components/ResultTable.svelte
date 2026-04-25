<script lang="ts">
	import { t } from '../../../../../_shared/i18n';
	import type { WorkbenchResultRow } from '../../../../../_shared/documents';

	export let rows: WorkbenchResultRow[] = [];
	export let selectedId = '';
	export let onSelect: (id: string) => void = () => {};
	export let onJumpToSource: (sourceSpanId: string) => void = () => {};

	$: selectedRow = rows.find((row) => row.id === selectedId) ?? rows[0] ?? null;

	function handleRowKeydown(event: KeyboardEvent, id: string) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			onSelect(id);
		}
	}
</script>

<section class="result-table-wrap">
	<table>
		<thead>
			<tr>
				<th>{$t('workbench.materialSystem')}</th>
				<th>{$t('workbench.process')}</th>
				<th>{$t('workbench.property')}</th>
				<th>{$t('workbench.baseline')}</th>
				<th>{$t('workbench.testCondition')}</th>
				<th>{$t('workbench.comparability')}</th>
				<th>{$t('workbench.warnings')}</th>
			</tr>
		</thead>
		<tbody>
			{#each rows as row}
				<tr
					tabindex="0"
					role="button"
					class:selected={row.id === selectedId}
					on:click={() => onSelect(row.id)}
					on:keydown={(event) => handleRowKeydown(event, row.id)}
				>
					<td>{row.material_system}</td>
					<td>{row.process}</td>
					<td>{row.property}</td>
					<td>{row.baseline}</td>
					<td>{row.test_condition}</td>
					<td>{row.comparability_status}</td>
					<td>{row.warnings_count}</td>
				</tr>
			{/each}
		</tbody>
	</table>

	{#if selectedRow}
		<aside class="result-detail" aria-label={$t('workbench.resultDetailLabel')}>
			<div>
				<h3>{selectedRow.property}</h3>
				<p>{selectedRow.comparability_status}</p>
			</div>
			{#if selectedRow.warnings.length}
				<ul>
					{#each selectedRow.warnings as warning}
						<li>{warning}</li>
					{/each}
				</ul>
			{:else}
				<p class="quiet">{$t('workbench.noResultWarnings')}</p>
			{/if}
			<div class="detail-actions">
				<button type="button" on:click={() => onJumpToSource(selectedRow.source_span_id)}>
					{$t('workbench.jumpToSource')}
				</button>
				<a href={selectedRow.detail_href}>{$t('workbench.openResult')}</a>
			</div>
		</aside>
	{/if}
</section>

<style>
	.result-table-wrap {
		display: grid;
		gap: 12px;
	}

	table {
		width: 100%;
		overflow: hidden;
		border: 1px solid #e2e8f0;
		border-collapse: separate;
		border-spacing: 0;
		border-radius: 10px;
		font-size: 13px;
		line-height: 20px;
	}

	th,
	td {
		height: 42px;
		padding: 10px 12px;
		border-bottom: 1px solid #e2e8f0;
		text-align: left;
		vertical-align: top;
	}

	th:first-child,
	td:first-child {
		width: 110px;
		background: #f8fafc;
		color: #334155;
		font-weight: 600;
	}

	th {
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
	}

	td {
		color: #334155;
	}

	tbody tr {
		cursor: pointer;
	}

	tbody tr:hover {
		background: #f8fafc;
	}

	tr.selected td {
		background: #f8fbff;
	}

	tr:last-child td {
		border-bottom: 0;
	}

	.result-detail {
		display: grid;
		gap: 10px;
		padding: 16px;
		border: 1.5px solid #2563eb;
		border-radius: 14px;
		background: #f8fbff;
		box-shadow: 0 8px 24px rgba(37, 99, 235, 0.12);
	}

	.result-detail h3 {
		margin: 0;
		color: #0f172a;
		font-size: 15px;
		font-weight: 700;
		line-height: 22px;
	}

	.result-detail p,
	.result-detail li {
		margin: 0;
		color: #334155;
		font-size: 14px;
		line-height: 22px;
	}

	.result-detail ul {
		margin: 0;
		padding-left: 18px;
	}

	.quiet {
		color: #64748b;
	}

	.detail-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.detail-actions button,
	.detail-actions a {
		display: inline-flex;
		height: 32px;
		align-items: center;
		padding: 0 10px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
	}
</style>
