<script lang="ts">
	import { resolve } from '$app/paths';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { t } from '../../../_shared/i18n';
	import type {
		ObjectiveEvidenceMap,
		ObjectiveEvidenceMapEdge,
		ObjectiveEvidenceMapNode
	} from '../../../_shared/researchView';

	export let map: ObjectiveEvidenceMap;
	export let collectionId: string;

	$: objective = map.nodes.find((node) => node.type === 'objective');
	$: findings = map.nodes.filter((node) => node.type === 'finding');
	$: evidence = map.nodes.filter((node) => node.type === 'evidence');
	$: sources = map.nodes.filter((node) => node.type === 'source');
	$: documents = map.nodes.filter((node) => node.type === 'document');

	function incomingFindingEdge(evidenceId: string) {
		return map.edges.find(
			(edge) =>
				edge.target === evidenceId &&
				['supports', 'contradicts', 'contextualizes'].includes(edge.relation)
		);
	}

	function relationLabel(edge: ObjectiveEvidenceMapEdge | undefined) {
		if (edge?.relation === 'supports') return $t('research.evidenceMap.supports');
		if (edge?.relation === 'contradicts') return $t('research.evidenceMap.contradicts');
		return $t('research.evidenceMap.contextualizes');
	}

	function relationTone(edge: ObjectiveEvidenceMapEdge | undefined) {
		if (edge?.relation === 'supports') return 'support';
		if (edge?.relation === 'contradicts') return 'contradiction';
		return 'context';
	}

	function evidenceStatusLabel(status: ObjectiveEvidenceMapNode['evidence_status']) {
		if (status === 'comparable') return $t('research.evidenceMap.statusComparable');
		if (status === 'association_only') return $t('research.evidenceMap.statusAssociationOnly');
		if (status === 'descriptive') return $t('research.evidenceMap.statusDescriptive');
		if (status === 'needs_context') return $t('research.evidenceMap.statusNeedsContext');
		if (status === 'non_comparable') return $t('research.evidenceMap.statusNonComparable');
		if (status === 'extraction_failed') return $t('research.evidenceMap.statusExtractionFailed');
		return $t('research.evidenceMap.statusUnknown');
	}

	function evidenceStatusTone(status: ObjectiveEvidenceMapNode['evidence_status']) {
		if (status === 'extraction_failed' || status === 'non_comparable') return 'status-warning';
		if (status === 'needs_context' || status === 'association_only') return 'status-context';
		if (status === 'descriptive') return 'status-descriptive';
		return 'status-neutral';
	}

	function sourceHref(
		node: ObjectiveEvidenceMapNode
	): `/collections/${string}/documents/${string}` {
		const base: `/collections/${string}/documents/${string}` = `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(node.document_id ?? '')}`;
		const returnTo = resolve('/collections/[id]/graph', { id: collectionId });
		const params = new SvelteURLSearchParams({
			view: 'parsed-paper',
			source_ref: node.source_ref ?? '',
			quote: node.source_excerpt ?? '',
			return_to: returnTo
		});
		if (node.page_numbers?.length) params.set('page', String(node.page_numbers[0]));
		return `${base}?${params.toString()}`;
	}

	function documentStatus(node: ObjectiveEvidenceMapNode) {
		if (node.analysis_status === 'failed') return $t('research.evidenceMap.paperFailed');
		if (node.analysis_status === 'excluded') return $t('research.evidenceMap.paperExcluded');
		return $t('research.evidenceMap.paperAnalyzed');
	}

	function percent(value: number | undefined) {
		return `${Math.round((value ?? 0) * 100)}%`;
	}

	function joined(values: string[] | undefined) {
		return values?.filter(Boolean).join(', ') || $t('research.emptyValue');
	}
</script>

<section class="map" aria-label={$t('research.evidenceMap.mapLabel')}>
	<div class="coverage" aria-label={$t('research.evidenceMap.coverageLabel')}>
		<div>
			<strong
				>{map.coverage.direct_evidence_document_count}/{map.coverage.total_document_count}</strong
			>
			<span>{$t('research.evidenceMap.directEvidencePapers')}</span>
		</div>
		<div>
			<strong>{map.coverage.finding_count}</strong>
			<span>{$t('research.evidenceMap.findingCount')}</span>
		</div>
		<div>
			<strong>{map.coverage.evidence_count}</strong>
			<span>{$t('research.evidenceMap.evidenceCount')}</span>
		</div>
		<div>
			<strong>{map.coverage.source_count}</strong>
			<span>{$t('research.evidenceMap.sourceCount')}</span>
		</div>
		<div class:coverage-warning={map.coverage.failed_document_count > 0}>
			<strong>{map.coverage.failed_document_count}</strong>
			<span>
				{map.coverage.failed_document_count === 1
					? $t('research.evidenceMap.failedPaperOne', {
							count: map.coverage.failed_document_count
						})
					: $t('research.evidenceMap.failedPaperMany', {
							count: map.coverage.failed_document_count
						})}
			</span>
		</div>
	</div>
	{#if map.coverage.evidence_status_counts && Object.keys(map.coverage.evidence_status_counts).length}
		<div class="status-summary" aria-label={$t('research.evidenceMap.evidenceStatusLabel')}>
			{#each Object.entries(map.coverage.evidence_status_counts) as [status, count] (status)}
				<span
					>{$t('research.evidenceMap.statusCount', {
						status: evidenceStatusLabel(status as ObjectiveEvidenceMapNode['evidence_status']),
						count: count ?? 0
					})}</span
				>
			{/each}
		</div>
	{/if}

	{#if map.coverage.failed_document_count > 0 || map.coverage.unlinked_evidence_count > 0}
		<p class="coverage-note">
			{$t('research.evidenceMap.partialCoverage')}
			{#if map.coverage.unlinked_evidence_count > 0}
				{$t('research.evidenceMap.unlinkedEvidence', {
					count: map.coverage.unlinked_evidence_count
				})}
			{/if}
		</p>
	{/if}

	<div class="flow" aria-label={$t('research.evidenceMap.flowLabel')}>
		<section class="column column--objective">
			<header>
				<span>01</span>
				<h3>{$t('research.evidenceMap.objectiveColumn')}</h3>
			</header>
			{#if objective}
				<article class="node node--objective">
					<strong>{objective.question ?? objective.label}</strong>
					<dl>
						<div>
							<dt>{$t('research.evidenceMap.material')}</dt>
							<dd>{joined(objective.material_scope)}</dd>
						</div>
						<div>
							<dt>{$t('research.evidenceMap.variables')}</dt>
							<dd>{joined(objective.variables)}</dd>
						</div>
						<div>
							<dt>{$t('research.evidenceMap.outcomes')}</dt>
							<dd>{joined(objective.outcomes)}</dd>
						</div>
					</dl>
				</article>
			{/if}
		</section>

		<section class="column">
			<header>
				<span>02</span>
				<h3>{$t('research.evidenceMap.findingsColumn')}</h3>
			</header>
			{#each findings as finding (finding.id)}
				<article class="node node--finding">
					<div class="node-meta">
						<span>{finding.synthesis_status?.replaceAll('_', ' ')}</span>
						<span
							>{$t('research.evidenceMap.certainty', { value: percent(finding.certainty) })}</span
						>
					</div>
					<strong>{finding.statement ?? finding.label}</strong>
					<p>{joined(finding.factors)} → {finding.outcome}</p>
					{#if finding.limitations?.length}
						<p class="limitation">{finding.limitations.join(' ')}</p>
					{/if}
				</article>
			{:else}
				<p class="column-empty">{$t('research.evidenceMap.noFindings')}</p>
			{/each}
		</section>

		<section class="column">
			<header>
				<span>03</span>
				<h3>{$t('research.evidenceMap.evidenceColumn')}</h3>
			</header>
			{#each evidence as item (item.id)}
				{@const edge = incomingFindingEdge(item.id)}
				<article class="node node--evidence" class:node--unlinked={!edge}>
					<div
						class="relation relation--{edge
							? relationTone(edge)
							: evidenceStatusTone(item.evidence_status)}"
					>
						{#if edge}{relationLabel(edge)}{:else}{evidenceStatusLabel(item.evidence_status)}{/if}
						{#if edge?.condition_boundary}
							<span>{$t('research.evidenceMap.conditionBoundary')}</span>
						{/if}
					</div>
					<strong>{item.label}</strong>
					<div class="node-meta">
						<span>{item.direction?.replaceAll('_', ' ')}</span>
						<span>{item.attribution_scope?.replaceAll('_', ' ')}</span>
						<span>{percent(item.confidence)}</span>
					</div>
					{#if item.source_excerpt && item.source_excerpt !== item.label}
						<blockquote>{item.source_excerpt}</blockquote>
					{/if}
					{#if !edge && item.evidence_status_reason}
						<p class="limitation">{item.evidence_status_reason}</p>
					{/if}
				</article>
			{/each}
		</section>

		<section class="column">
			<header>
				<span>04</span>
				<h3>{$t('research.evidenceMap.sourcesColumn')}</h3>
			</header>
			{#each sources as source (source.id)}
				<a class="node node--source" href={resolve(sourceHref(source))}>
					<strong>{source.label}</strong>
					<span class="source-meta">
						{source.page_numbers?.length
							? $t('research.evidenceMap.pages', { pages: source.page_numbers.join(', ') })
							: $t('research.evidenceMap.openSource')}
					</span>
					{#if source.source_excerpt}
						<span class="source-excerpt">{source.source_excerpt}</span>
					{/if}
				</a>
			{/each}
		</section>

		<section class="column column--papers">
			<header>
				<span>05</span>
				<h3>{$t('research.evidenceMap.papersColumn')}</h3>
			</header>
			{#each documents as document (document.id)}
				<a
					class="node node--paper"
					class:node--failed={document.analysis_status === 'failed'}
					class:node--excluded={document.analysis_status === 'excluded'}
					href={resolve('/collections/[id]/documents/[document_id]', {
						id: collectionId,
						document_id: document.document_id ?? ''
					})}
				>
					<span class="paper-status">{documentStatus(document)}</span>
					<strong>{document.label}</strong>
					{#if document.evidence_disposition_reason}
						<span class="paper-reason">{document.evidence_disposition_reason}</span>
					{/if}
				</a>
			{/each}
		</section>
	</div>
</section>

<style>
	.map {
		display: grid;
		gap: 12px;
		min-width: 0;
	}

	.coverage {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
		background: var(--surface-soft);
	}

	.coverage > div {
		min-width: 0;
		display: grid;
		gap: 2px;
		padding: 12px 16px;
		border-left: 1px solid var(--border-default);
	}

	.coverage > div:first-child {
		border-left: 0;
	}

	.coverage strong {
		font-size: 18px;
		line-height: 1.2;
	}

	.coverage span {
		color: var(--text-secondary);
		font-size: 12px;
	}

	.status-summary {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
		padding: 8px 12px;
		border-bottom: 1px solid var(--border-default);
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
	}

	.coverage-warning strong,
	.coverage-warning span {
		color: var(--warning-text);
	}

	.coverage-note {
		margin: 0;
		padding: 9px 12px;
		border-left: 3px solid var(--warning-text);
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 13px;
	}

	.flow {
		display: grid;
		grid-template-columns:
			minmax(0, 0.9fr) minmax(0, 1.15fr) minmax(0, 1.2fr) minmax(0, 1fr)
			minmax(0, 0.9fr);
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
	}

	.column {
		position: relative;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px;
		border-left: 1px solid var(--border-default);
	}

	.column:first-child {
		border-left: 0;
	}

	.column:not(:last-child)::after {
		content: '›';
		position: absolute;
		top: 18px;
		right: -8px;
		z-index: 1;
		width: 16px;
		height: 16px;
		display: grid;
		place-items: center;
		border: 1px solid var(--border-strong);
		border-radius: 50%;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 1;
	}

	.column > header {
		display: flex;
		align-items: baseline;
		gap: 7px;
		min-height: 30px;
	}

	.column > header span {
		color: var(--text-tertiary);
		font-size: 10px;
		font-weight: 700;
	}

	.column h3 {
		margin: 0;
		font-size: 13px;
		line-height: 1.3;
	}

	.node {
		min-width: 0;
		display: grid;
		gap: 8px;
		padding: 11px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--bg-subtle);
		color: var(--text-primary);
		font-size: 12px;
		overflow-wrap: anywhere;
	}

	.node strong {
		font-size: 13px;
		line-height: 1.45;
	}

	.node p,
	.node blockquote {
		margin: 0;
		color: var(--text-secondary);
		line-height: 1.45;
	}

	.node blockquote {
		padding-left: 8px;
		border-left: 2px solid var(--border-strong);
	}

	.node--objective {
		border-color: var(--brand-border);
		background: var(--brand-soft);
	}

	.node--finding {
		border-left: 3px solid var(--info-text);
	}

	.node--source,
	.node--paper {
		transition:
			border-color 120ms ease,
			background-color 120ms ease;
	}

	.node--source:hover,
	.node--paper:hover {
		border-color: var(--brand-primary);
		background: var(--brand-soft);
	}

	.node--failed {
		border-color: var(--warning-border);
		background: var(--warning-bg);
	}

	.node--unlinked {
		border-left: 3px solid var(--warning-text);
	}

	.node--excluded {
		opacity: 0.78;
	}

	dl {
		display: grid;
		gap: 7px;
		margin: 0;
	}

	dl div {
		display: grid;
		gap: 1px;
	}

	dt {
		color: var(--text-tertiary);
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
	}

	dd {
		margin: 0;
		color: var(--text-secondary);
	}

	.node-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 8px;
		color: var(--text-tertiary);
		font-size: 10px;
		text-transform: capitalize;
	}

	.relation,
	.paper-status {
		width: fit-content;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
	}

	.relation span {
		margin-left: 5px;
		font-weight: 500;
		text-transform: none;
	}

	.relation--support,
	.paper-status {
		color: var(--success-text);
	}

	.relation--contradiction {
		color: var(--danger-text);
	}

	.relation--context {
		color: var(--info-text);
	}

	.relation--status-warning {
		color: var(--warning-text);
	}

	.relation--status-context {
		color: var(--info-text);
	}

	.relation--status-descriptive,
	.relation--status-neutral {
		color: var(--text-secondary);
	}

	.limitation,
	.paper-reason {
		color: var(--warning-text) !important;
	}

	.source-meta,
	.paper-reason {
		color: var(--text-secondary);
		font-size: 11px;
	}

	.source-excerpt {
		display: -webkit-box;
		overflow: hidden;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		color: var(--text-secondary);
		line-height: 1.45;
	}

	.node--failed .paper-status,
	.node--failed .paper-reason {
		color: var(--warning-text) !important;
	}

	.column-empty {
		margin: 0;
		padding: 12px;
		color: var(--text-secondary);
		font-size: 12px;
	}

	@media (max-width: 1099px) {
		.flow {
			grid-template-columns: 1fr;
		}

		.column,
		.column:first-child {
			border-top: 1px solid var(--border-default);
			border-left: 0;
		}

		.column:first-child {
			border-top: 0;
		}

		.column:not(:last-child)::after {
			content: '⌄';
			top: auto;
			right: 18px;
			bottom: -8px;
		}
	}

	@media (max-width: 700px) {
		.coverage {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.coverage > div {
			border-top: 1px solid var(--border-default);
		}

		.coverage > div:nth-child(-n + 2) {
			border-top: 0;
		}

		.coverage > div:nth-child(odd) {
			border-left: 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.node--source,
		.node--paper {
			transition: none;
		}
	}
</style>
