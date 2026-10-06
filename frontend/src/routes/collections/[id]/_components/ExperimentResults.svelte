<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChartNoAxesCombined, Table2, ExternalLink, ChevronLeft, ChevronRight } from '@lucide/svelte';
	import { t } from '../../../_shared/i18n';
	import { experimentResultRows, experimentValue, numericExperimentPair, type ExperimentResultRow } from '../../../_shared/experimentResults';
	import type { ExperimentAnalysisProjection, ExperimentMeasurement, ExperimentSource } from '../../../_shared/researchView';

	export let projection: ExperimentAnalysisProjection;
	export let collectionId: string;
	export let objectiveId: string;
	export let documentTitles: Record<string, string> = {};
	export let findingId = '';
	export let selectionIds: string[] | undefined = undefined;
	let outcome = '';
	let mode: 'table' | 'chart' = 'table';
	let pageIndex = 0;
	let previousFilter = '';
	$: rows = experimentResultRows(projection, selectionIds);
	$: outcomes = [...new Set(rows.map(row => row.outcome))];
	$: if (!outcomes.includes(outcome)) outcome = outcomes[0] ?? '';
	$: filtered = rows.filter(row => row.outcome === outcome);
	$: filterKey = `${findingId}:${outcome}`;
	$: if (filterKey !== previousFilter) { previousFilter = filterKey; pageIndex = 0; }
	$: pages = Math.max(1, Math.ceil(filtered.length / 8));
	$: if (pageIndex >= pages) pageIndex = pages - 1;
	$: visible = filtered.slice(pageIndex * 8, (pageIndex + 1) * 8);
	$: chartRows = visible.flatMap(row => { const pair = numericExperimentPair(row); return pair ? [{ row, pair }] : []; });
	$: missingSelections = projection.selections.filter(selection => (!selectionIds || selectionIds.includes(selection.selection_id)) && !projection.experiments.some(experiment => experiment.experiment_id === selection.experiment_id && experiment.experiment_version === selection.experiment_version));
	$: groups = projection.comparison_groups.filter(group => group.outcome === outcome && (!selectionIds || group.members.some(member => selectionIds.includes(member.selection_id))));

	function label(row: ExperimentResultRow, side: 'before' | 'after') {
		const key = side === 'before' ? row.comparison?.baseline_variant_key : row.comparison?.target_variant_key ?? row.after[0]?.variant_key;
		return row.experiment.variants.find(variant => variant.variant_key === key)?.variant_label ?? $t('objectiveWorkspace.notReported');
	}
	function measurement(item: ExperimentMeasurement) {
		const value = experimentValue(item.value);
		return value ? `${value}${item.unit ? ` ${item.unit}` : ''}` : item.result_text || $t('objectiveWorkspace.notReported');
	}
	function sourceHref(source: ExperimentSource) {
		const returnTo = resolve('/collections/[id]/objectives/[objective_id]', { id: collectionId, objective_id: objectiveId }) + (findingId ? `?${new URLSearchParams({ finding_id: findingId })}` : '');
		const query = new URLSearchParams({ view: 'parsed-paper', source_ref: source.source_ref, quote: source.quote, return_to: returnTo });
		return resolve('/collections/[id]/documents/[document_id]', { id: collectionId, document_id: source.document_id }) + `?${query}`;
	}
	function tests(row: ExperimentResultRow) {
		const keys = new Set([...row.before, ...row.after].map(item => item.test_key));
		return row.experiment.test_conditions.filter(test => keys.has(test.test_key));
	}
	function point(value: number, before: number, after: number) {
		const low = Math.min(before, after), spread = Math.abs(after - before) || Math.abs(before) * .1 || 1;
		return 50 + (value - low + spread * .2) / (spread * 1.4) * 440;
	}
	function number(value: number) { return Number(value.toPrecision(5)).toLocaleString(); }
</script>

<section class="experiment-results" aria-label={findingId ? $t('objectiveWorkspace.supporting') : $t('objectiveWorkspace.comparison')}>
	<header>
		<div><h2>{findingId ? $t('objectiveWorkspace.supporting') : $t('objectiveWorkspace.comparison')}</h2><span>{$t('objectiveWorkspace.rows', { count: filtered.length })}</span></div>
		<div class="toolbar"><slot name="actions" /><div class="modes" role="group" aria-label={$t('objectiveWorkspace.table') + ' / ' + $t('objectiveWorkspace.chart')}>
			<button type="button" aria-pressed={mode === 'table'} on:click={() => mode = 'table'}><Table2 size={16} />{$t('objectiveWorkspace.table')}</button>
			<button type="button" aria-pressed={mode === 'chart'} on:click={() => mode = 'chart'}><ChartNoAxesCombined size={16} />{$t('objectiveWorkspace.chart')}</button>
		</div></div>
	</header>
	{#if outcomes.length}<label class="outcome">{$t('objectiveWorkspace.outcome')}<select bind:value={outcome}>{#each outcomes as item}<option value={item}>{item}</option>{/each}</select></label>{/if}
	{#if missingSelections.length}<p class="warning" role="alert">{$t('objectiveWorkspace.incomplete')}</p>{/if}
	{#if !rows.length}<p class="empty">{$t(findingId ? 'objectiveWorkspace.noFindingData' : 'objectiveWorkspace.noComparisons')}</p>
	{:else if mode === 'table'}
			<div class="table-scroll" tabindex="-1" role="region" aria-label={$t('objectiveWorkspace.comparison')}>
			<table><thead><tr>
				{#each ['paper', 'factors', 'firstGroup', 'secondGroup', 'difference', 'conditions', 'sources'] as key}<th scope="col">{$t(`objectiveWorkspace.${key}`)}</th>{/each}
			</tr></thead><tbody>
				{#each visible as row (row.key)}
					{@const pair = numericExperimentPair(row)}
					<tr>
						<td><strong>{documentTitles[row.experiment.document_id] || $t('research.findingReview.untitledPaper')}</strong><small>{row.experiment.label}</small></td>
						<td>{#each row.comparison?.changed_variables ?? [] as variable}<div class="variable"><strong>{variable.name}</strong><small>{experimentValue(variable.baseline_value) || $t('objectiveWorkspace.notReported')} → {experimentValue(variable.target_value) || $t('objectiveWorkspace.notReported')} {variable.unit ?? ''}</small></div>{:else}<span class="muted">{$t('objectiveWorkspace.measurement')}</span>{/each}</td>
						{#each ['before', 'after'] as side}
							<td><span>{label(row, side as 'before' | 'after')}</span>{#each row[side as 'before' | 'after'] as item}<strong class="value">{measurement(item)}</strong><small>{item.result_kind !== 'measured' ? item.result_kind : ''}</small>{:else}<small>{$t('objectiveWorkspace.notReported')}</small>{/each}</td>
						{/each}
						<td>{#if pair}<strong class="value">{pair.delta > 0 ? '+' : ''}{number(pair.delta)} {pair.unit}</strong><small>{$t('objectiveWorkspace.calculated')}</small>{:else}{row.comparison?.reported_statement || $t('objectiveWorkspace.notReported')}{/if}</td>
						<td>
							<span class:warning={row.comparison && row.comparison.status !== 'ready'}>{$t(`objectiveWorkspace.${row.comparison?.status === 'ready' ? 'ready' : row.comparison?.status === 'non_comparable' ? 'nonComparable' : row.comparison ? 'insufficient' : 'measurement'}`)}</span>
							<details><summary>{$t('objectiveWorkspace.conditions')}</summary>
								{#each tests(row) as test}<p>{test.test_type}</p>{#each test.parameters as parameter}<small>{parameter.name}: {parameter.value} {parameter.unit ?? ''}</small>{/each}{#each test.missing_parameters as missing}<small>{$t('objectiveWorkspace.missing')}: {missing}</small>{/each}{/each}
								{#each row.comparison?.matched_conditions ?? [] as condition}<small>{condition.name}: {condition.value} {condition.unit ?? ''}</small>{/each}
								{#each [...row.missing, ...(row.comparison?.reasons ?? [])] as reason}<p>{reason}</p>{/each}
								{#each [...row.before, ...row.after] as item}<small>{measurement(item)}</small><small>{Object.keys(item.statistics).length ? JSON.stringify(item.statistics) : $t('objectiveWorkspace.noStatistics')}</small>{/each}
							</details>
						</td>
						<td>{#each row.sources as source, index}<a class="source" href={sourceHref(source)} title={source.quote}><ExternalLink size={14} />{$t('objectiveWorkspace.sources')} {index + 1}</a>{:else}<span class="muted">{$t('objectiveWorkspace.notReported')}</span>{/each}</td>
					</tr>
				{/each}
			</tbody></table>
		</div>
	{:else}
		<div class="charts">
			{#each chartRows as { row, pair } (row.key)}
				<figure><figcaption><strong>{documentTitles[row.experiment.document_id] || $t('research.findingReview.untitledPaper')}</strong><span>{label(row, 'before')} → {label(row, 'after')}</span><small>{row.comparison?.changed_variables.map(item => `${item.name}: ${experimentValue(item.baseline_value)} → ${experimentValue(item.target_value)} ${item.unit ?? ''}`).join(' · ')}</small></figcaption>
					<svg viewBox="0 0 540 108" role="img" aria-label={`${label(row, 'before')}: ${pair.before} ${pair.unit}; ${label(row, 'after')}: ${pair.after} ${pair.unit}`}>
						<line x1="50" x2="490" y1="88" y2="88" class="axis" />
						<line x1={point(pair.before, pair.before, pair.after)} x2={point(pair.after, pair.before, pair.after)} y1="51" y2="51" class="pair" />
						<circle cx={point(pair.before, pair.before, pair.after)} cy="51" r="6" class="before" />
						<circle cx={point(pair.after, pair.before, pair.after)} cy="51" r="6" class="after" />
						<text x={point(pair.before, pair.before, pair.after)} y="25" text-anchor="middle">{number(pair.before)} {pair.unit}</text>
						<text x={point(pair.after, pair.before, pair.after)} y="76" text-anchor="middle">{number(pair.after)} {pair.unit}</text>
					</svg>
					<p>{label(row, 'before')}: {number(pair.before)} {pair.unit} · {label(row, 'after')}: {number(pair.after)} {pair.unit}</p>
					{#each row.sources as source, index}<a href={sourceHref(source)}>{$t('objectiveWorkspace.sources')} {index + 1}<ExternalLink size={14} /></a>{/each}
				</figure>
			{:else}<p class="empty">{$t('objectiveWorkspace.noPairs')}</p>{/each}
			{#if visible.length > chartRows.length}<p class="muted">{$t('objectiveWorkspace.excludedPairs', { count: visible.length - chartRows.length })}</p>{/if}
		</div>
	{/if}
	{#if pages > 1}<nav aria-label={$t('objectiveWorkspace.comparison')}><button type="button" disabled={!pageIndex} on:click={() => pageIndex--} aria-label={$t('objectiveWorkspace.previous')} title={$t('objectiveWorkspace.previous')}><ChevronLeft size={18} /></button><span>{$t('objectiveWorkspace.page', { current: pageIndex + 1, total: pages })}</span><button type="button" disabled={pageIndex + 1 >= pages} on:click={() => pageIndex++} aria-label={$t('objectiveWorkspace.next')} title={$t('objectiveWorkspace.next')}><ChevronRight size={18} /></button></nav>{/if}
	{#if groups.length}<details class="comparability"><summary>{$t('objectiveWorkspace.groupComparability')}</summary>{#each groups as group}<p><strong>{$t(`objectiveWorkspace.${group.status}`)}</strong> · {group.comparison_basis.join(' · ')}</p>{#each group.limitations as limitation}<p>{limitation}</p>{/each}{#each group.members as member}<small>{member.comparability}: {member.reason}</small>{/each}{/each}</details>{/if}
</section>

<style>
	.experiment-results { display: grid; gap: 16px; min-width: 0; }
	header, header > div, .toolbar, .modes, nav { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
	header { justify-content: space-between; } h2 { margin: 0; font-size: 18px; } header span, small, .muted, figcaption span { color: var(--text-secondary); }
	button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; padding: 6px 12px; border: 1px solid var(--border-default); background: var(--surface-panel); border-radius: 4px; cursor: pointer; color: var(--text-primary); font-size: 13px; }
	.modes { gap: 0; } .modes button[aria-pressed='true'] { background: var(--primary-soft); color: var(--primary); } button:disabled { opacity: .5; cursor: default; }
	.outcome { display: flex; align-items: center; gap: 12px; font-size: 13px; } select { max-width: min(400px, 70%); padding: 7px; background: var(--surface-panel); border: 1px solid var(--border-default); border-radius: 4px; }
	.table-scroll { overflow: auto; max-height: 600px; border-block: 1px solid var(--border-default); }
	table { width: 100%; min-width: 1080px; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
	th { position: sticky; top: 0; background: var(--surface-muted); text-align: left; font-size: 12px; z-index: 1; }
	th, td { padding: 14px 12px; vertical-align: top; border-bottom: 1px solid var(--border-default); overflow-wrap: anywhere; } th:first-child { width: 19%; } th:last-child { width: 12%; }
	strong { font-weight: 600; } small { display: block; font-size: 12px; line-height: 1.5; margin-top: 5px; } .value { display: block; margin-top: 8px; font-variant-numeric: tabular-nums; } .variable + .variable { margin-top: 8px; }
	a { color: var(--primary); } .source { display: flex; align-items: center; gap: 5px; margin-bottom: 8px; } summary { cursor: pointer; margin-block: 8px; color: var(--text-secondary); }
	p { margin: 8px 0; } .warning { color: var(--warning); } .empty { padding: 24px 0; color: var(--text-secondary); }
	.charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; } figure { margin: 0; padding-block: 12px; border-bottom: 1px solid var(--border-default); } figcaption { display: grid; gap: 6px; font-size: 13px; overflow-wrap: anywhere; }
	svg { display: block; width: 100%; height: auto; margin-block: 12px; } svg text { font-size: 13px; fill: var(--text-primary); } .axis { stroke: var(--border-default); } .pair { stroke: var(--success); stroke-width: 2; } .before { stroke: var(--success); fill: var(--surface-panel); stroke-width: 2; } .after { fill: var(--success); } figure p { font-size: 12px; color: var(--text-secondary); } figure a { display: inline-flex; gap: 5px; margin-right: 12px; font-size: 12px; }
	nav { justify-content: flex-end; } .comparability { border-top: 1px solid var(--border-default); font-size: 13px; }
	@media (max-width: 700px) { .charts { grid-template-columns: 1fr; } .toolbar { width: 100%; justify-content: space-between; } }
</style>
