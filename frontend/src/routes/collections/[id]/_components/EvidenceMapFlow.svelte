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
	type FindingRelation = 'supports' | 'contradicts' | 'contextualizes';

	$: objective = map.nodes.find((node) => node.type === 'objective');
	$: findings = map.nodes.filter((node) => node.type === 'finding');
	$: evidence = map.nodes.filter((node) => node.type === 'evidence');
	$: sources = map.nodes.filter((node) => node.type === 'source');
	$: documents = map.nodes.filter((node) => node.type === 'document');
	$: unlinkedEvidence = evidence.filter(
		(item) =>
			!map.edges.some(
				(edge) =>
					edge.target === item.id &&
					['supports', 'contradicts', 'contextualizes'].includes(edge.relation)
			)
	);

	function evidenceGroups(findingId: string) {
		const relations: FindingRelation[] = ['supports', 'contradicts', 'contextualizes'];
		return relations
			.map((relation) => ({
				relation,
				items: map.edges
					.filter((edge) => edge.source === findingId && edge.relation === relation)
					.map((edge) => ({
						edge,
						evidence: evidence.find((item) => item.id === edge.target)
					}))
					.filter(
						(
							item
						): item is {
							edge: ObjectiveEvidenceMapEdge;
							evidence: ObjectiveEvidenceMapNode;
						} => Boolean(item.evidence)
					)
			}))
			.filter((group) => group.items.length > 0);
	}

	function evidenceSources(evidenceId: string) {
		const sourceIds = map.edges
			.filter((edge) => edge.source === evidenceId && edge.relation === 'extracted_from')
			.map((edge) => edge.target);
		return sourceIds
			.map((sourceId) => sources.find((source) => source.id === sourceId))
			.filter((source): source is ObjectiveEvidenceMapNode => Boolean(source));
	}

	function linkedEvidenceCount(findingId: string) {
		return evidenceGroups(findingId).reduce((count, group) => count + group.items.length, 0);
	}

	function relationLabel(relation: FindingRelation) {
		if (relation === 'supports') return $t('research.evidenceMap.supports');
		if (relation === 'contradicts') return $t('research.evidenceMap.contradicts');
		return $t('research.evidenceMap.contextualizes');
	}

	function relationTone(relation: FindingRelation) {
		if (relation === 'supports') return 'support';
		if (relation === 'contradicts') return 'contradiction';
		return 'context';
	}

	function synthesisLabel(status: ObjectiveEvidenceMapNode['synthesis_status']) {
		if (!status) return '';
		return $t(`research.comparison.synthesis.${status}`);
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

	function directionLabel(direction: ObjectiveEvidenceMapNode['direction']) {
		return direction ? $t(`research.evidenceMap.direction.${direction}`) : '';
	}

	function attributionLabel(attribution: ObjectiveEvidenceMapNode['attribution_scope']) {
		return attribution ? $t(`research.evidenceMap.attribution.${attribution}`) : '';
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

	function findingHref(finding: ObjectiveEvidenceMapNode) {
		const base = resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: map.objective_id
		});
		const params = new SvelteURLSearchParams({ finding_id: finding.finding_id ?? '' });
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
	<div class="summary-grid">
		<section class="objective-context" aria-labelledby="objective-context-title">
			<div class="section-kicker">01 / {$t('research.evidenceMap.objectiveColumn')}</div>
			{#if objective}
				<h3 id="objective-context-title">{objective.question ?? objective.label}</h3>
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
			{/if}
		</section>

		<aside class="coverage-panel" aria-label={$t('research.evidenceMap.coverageLabel')}>
			<div class="coverage">
				<div>
					<strong
						>{map.coverage.direct_evidence_document_count}/{map.coverage
							.total_document_count}</strong
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
			</div>
			{#if map.coverage.evidence_status_counts && Object.keys(map.coverage.evidence_status_counts).length}
				<div class="status-summary" aria-label={$t('research.evidenceMap.evidenceStatusLabel')}>
					{#each Object.entries(map.coverage.evidence_status_counts) as [status, count] (status)}
						<span
							class="status-pill status-pill--{evidenceStatusTone(
								status as ObjectiveEvidenceMapNode['evidence_status']
							)}"
						>
							{$t('research.evidenceMap.statusCount', {
								status: evidenceStatusLabel(status as ObjectiveEvidenceMapNode['evidence_status']),
								count: count ?? 0
							})}
						</span>
					{/each}
				</div>
			{/if}
		</aside>
	</div>

	{#if map.coverage.failed_document_count > 0 || map.coverage.unlinked_evidence_count > 0}
		<div class="coverage-note" role="status">
			<span class="coverage-note__mark" aria-hidden="true">!</span>
			<p>
				{#if map.coverage.failed_document_count > 0}
					<strong>
						{map.coverage.failed_document_count === 1
							? $t('research.evidenceMap.failedPaperOne', {
									count: map.coverage.failed_document_count
								})
							: $t('research.evidenceMap.failedPaperMany', {
									count: map.coverage.failed_document_count
								})}
					</strong>
				{/if}
				{$t('research.evidenceMap.partialCoverage')}
				{#if map.coverage.unlinked_evidence_count > 0}
					{$t('research.evidenceMap.unlinkedEvidence', {
						count: map.coverage.unlinked_evidence_count
					})}
				{/if}
			</p>
		</div>
	{/if}

	<section class="findings-panel" aria-label={$t('research.evidenceMap.flowLabel')}>
		<header class="section-heading">
			<div>
				<div class="section-kicker">02 / {$t('research.evidenceMap.findingsColumn')}</div>
				<h3>{$t('research.evidenceMap.traceTitle')}</h3>
				<p>{$t('research.evidenceMap.traceLead')}</p>
			</div>
			<span class="section-count">{map.coverage.finding_count}</span>
		</header>

		{#each findings as finding, findingIndex (finding.id)}
			<article
				class="finding-block"
				class:finding-block--conflict={finding.synthesis_status === 'conflict'}
				class:finding-block--conditional={finding.synthesis_status === 'condition_dependent'}
				class:finding-block--limited={finding.synthesis_status === 'insufficient_confirmation'}
			>
				<header class="finding-header">
					<span class="finding-number">
						{$t('research.evidenceMap.findingNumber', { number: findingIndex + 1 })}
					</span>
					<div class="finding-copy">
						<div class="finding-status">
							<span>{synthesisLabel(finding.synthesis_status)}</span>
							<span
								>{$t('research.evidenceMap.certainty', {
									value: percent(finding.certainty)
								})}</span
							>
							<span
								>{$t('research.evidenceMap.linkedEvidenceCount', {
									count: linkedEvidenceCount(finding.id)
								})}</span
							>
						</div>
						<h4>{finding.statement ?? finding.label}</h4>
						<p class="finding-axis">
							<span>{joined(finding.factors)}</span>
							<span aria-hidden="true">→</span>
							<strong>{finding.outcome}</strong>
						</p>
					</div>
					<a class="finding-link" href={findingHref(finding)}>
						{$t('research.comparison.reviewEvidence')}
					</a>
				</header>

				{#if finding.limitations?.length}
					<div class="finding-limitations">
						<strong>{$t('research.comparison.limitations')}</strong>
						<p>{finding.limitations.join(' ')}</p>
					</div>
				{/if}

				<div class="evidence-groups">
					{#each evidenceGroups(finding.id) as group (group.relation)}
						<section class="evidence-group evidence-group--{relationTone(group.relation)}">
							<header>
								<span class="relation-mark" aria-hidden="true"></span>
								<h5>{relationLabel(group.relation)}</h5>
								<span>{group.items.length}</span>
							</header>

							<div class="evidence-list">
								{#each group.items as linked (linked.evidence.id)}
									<article class="evidence-row">
										<div class="evidence-copy">
											<strong>{linked.evidence.label}</strong>
											<div class="evidence-meta">
												<span>{evidenceStatusLabel(linked.evidence.evidence_status)}</span>
												{#if linked.evidence.direction}
													<span>{directionLabel(linked.evidence.direction)}</span>
												{/if}
												{#if linked.evidence.attribution_scope}
													<span>{attributionLabel(linked.evidence.attribution_scope)}</span>
												{/if}
												<span>{percent(linked.evidence.confidence)}</span>
												{#if linked.edge.condition_boundary}
													<span class="condition-boundary"
														>{$t('research.evidenceMap.conditionBoundary')}</span
													>
												{/if}
											</div>
											{#if linked.evidence.source_excerpt && linked.evidence.source_excerpt !== linked.evidence.label}
												<blockquote>{linked.evidence.source_excerpt}</blockquote>
											{/if}
										</div>

										<div class="source-links">
											{#each evidenceSources(linked.evidence.id) as source (source.id)}
												<a
													class="source-link"
													href={resolve(sourceHref(source))}
													aria-label={source.label}
												>
													<span>{$t('research.evidenceMap.sourcesColumn')}</span>
													<strong>{source.label}</strong>
													<small>
														{source.page_numbers?.length
															? $t('research.evidenceMap.pages', {
																	pages: source.page_numbers.join(', ')
																})
															: $t('research.evidenceMap.openSource')}
													</small>
												</a>
											{/each}
										</div>
									</article>
								{/each}
							</div>
						</section>
					{:else}
						<p class="empty-evidence">{$t('research.evidenceMap.noLinkedEvidence')}</p>
					{/each}
				</div>
			</article>
		{:else}
			<p class="empty-findings">{$t('research.evidenceMap.noFindings')}</p>
		{/each}
	</section>

	{#if unlinkedEvidence.length}
		<section class="review-section" aria-labelledby="unlinked-evidence-title">
			<header class="section-heading section-heading--compact">
				<div>
					<div class="section-kicker">03 / {$t('research.evidenceMap.evidenceColumn')}</div>
					<h3 id="unlinked-evidence-title">{$t('research.evidenceMap.unlinkedTitle')}</h3>
					<p>{$t('research.evidenceMap.unlinkedLead')}</p>
				</div>
				<span class="section-count section-count--warning">{unlinkedEvidence.length}</span>
			</header>
			<div class="review-list">
				{#each unlinkedEvidence as item (item.id)}
					<article class="review-row">
						<div>
							<span class="status-pill status-pill--{evidenceStatusTone(item.evidence_status)}">
								{evidenceStatusLabel(item.evidence_status)}
							</span>
							<strong>{item.label}</strong>
							{#if item.evidence_status_reason}
								<p>{item.evidence_status_reason}</p>
							{/if}
						</div>
						<div class="source-links">
							{#each evidenceSources(item.id) as source (source.id)}
								<a class="source-link" href={resolve(sourceHref(source))} aria-label={source.label}>
									<strong>{source.label}</strong>
									<small>
										{source.page_numbers?.length
											? $t('research.evidenceMap.pages', {
													pages: source.page_numbers.join(', ')
												})
											: $t('research.evidenceMap.openSource')}
									</small>
								</a>
							{/each}
						</div>
					</article>
				{/each}
			</div>
		</section>
	{/if}

	<section class="papers-section" aria-labelledby="paper-coverage-title">
		<header class="section-heading section-heading--compact">
			<div>
				<div class="section-kicker">04 / {$t('research.evidenceMap.papersColumn')}</div>
				<h3 id="paper-coverage-title">{$t('research.evidenceMap.paperCoverageTitle')}</h3>
				<p>{$t('research.evidenceMap.partialCoverage')}</p>
			</div>
			{#if map.coverage.failed_document_count > 0}
				<span class="section-count section-count--warning">
					{map.coverage.failed_document_count}
				</span>
			{/if}
		</header>
		<div class="paper-list">
			{#each documents as document (document.id)}
				<a
					class="paper-row"
					class:paper-row--failed={document.analysis_status === 'failed'}
					class:paper-row--excluded={document.analysis_status === 'excluded'}
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
		</div>
	</section>
</section>

<style>
	.map {
		display: grid;
		gap: 18px;
		min-width: 0;
	}

	.summary-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.05fr) minmax(480px, 0.95fr);
		gap: 14px;
		min-width: 0;
	}

	.objective-context,
	.coverage-panel {
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
		box-shadow: var(--shadow-xs);
	}

	.objective-context {
		padding: 18px 20px;
		border-left: 4px solid var(--brand-primary);
	}

	.section-kicker {
		color: var(--text-tertiary);
		font-size: 11px;
		font-weight: 750;
		line-height: 1.3;
		text-transform: uppercase;
	}

	.objective-context h3,
	.section-heading h3 {
		margin: 5px 0 0;
		color: var(--text-primary);
		letter-spacing: 0;
	}

	.objective-context h3 {
		max-width: 70ch;
		font-size: 20px;
		line-height: 1.4;
	}

	.objective-context dl {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin: 18px 0 0;
		padding-top: 14px;
		border-top: 1px solid var(--border-default);
	}

	.objective-context dl div {
		min-width: 0;
	}

	.objective-context dt {
		color: var(--text-tertiary);
		font-size: 10px;
		font-weight: 750;
		line-height: 1.3;
		text-transform: uppercase;
	}

	.objective-context dd {
		margin: 4px 0 0;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}

	.coverage-panel {
		display: grid;
		align-content: start;
		overflow: hidden;
	}

	.coverage {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		background: var(--bg-subtle);
	}

	.coverage > div {
		min-width: 0;
		display: grid;
		align-content: center;
		gap: 4px;
		min-height: 82px;
		padding: 14px 16px;
		border-left: 1px solid var(--border-default);
	}

	.coverage > div:first-child {
		border-left: 0;
	}

	.coverage strong {
		color: var(--text-primary);
		font-size: 22px;
		line-height: 1.2;
	}

	.coverage span {
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 1.4;
	}

	.status-summary {
		display: flex;
		flex-wrap: wrap;
		gap: 7px;
		padding: 12px 14px;
		border-top: 1px solid var(--border-default);
		background: var(--surface-card);
	}

	.status-pill {
		display: inline-flex;
		align-items: center;
		width: fit-content;
		min-height: 24px;
		padding: 3px 8px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 650;
		line-height: 1.3;
	}

	.status-pill--status-warning {
		border-color: var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.status-pill--status-context {
		border-color: var(--info-border);
		background: var(--info-bg);
		color: var(--info-text);
	}

	.status-pill--status-descriptive {
		border-color: var(--brand-border);
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.coverage-note {
		display: grid;
		grid-template-columns: 26px minmax(0, 1fr);
		align-items: center;
		gap: 10px;
		padding: 10px 14px;
		border: 1px solid var(--warning-border);
		border-radius: 6px;
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 13px;
	}

	.coverage-note__mark {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border: 1px solid var(--warning-border);
		border-radius: 50%;
		background: var(--surface-card);
		font-weight: 800;
	}

	.coverage-note p {
		margin: 0;
		line-height: 1.5;
	}

	.findings-panel,
	.review-section,
	.papers-section {
		display: grid;
		gap: 12px;
		min-width: 0;
	}

	.section-heading {
		display: flex;
		align-items: end;
		justify-content: space-between;
		gap: 18px;
		padding: 2px 2px 4px;
	}

	.section-heading > div {
		min-width: 0;
	}

	.section-heading h3 {
		font-size: 18px;
		line-height: 1.35;
	}

	.section-heading p {
		max-width: 78ch;
		margin: 4px 0 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 1.5;
	}

	.section-heading--compact {
		align-items: center;
	}

	.section-count {
		display: grid;
		flex: 0 0 auto;
		place-items: center;
		width: 34px;
		height: 34px;
		border: 1px solid var(--brand-border);
		border-radius: 50%;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 13px;
		font-weight: 800;
	}

	.section-count--warning {
		border-color: var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.finding-block {
		min-width: 0;
		display: grid;
		gap: 0;
		border: 1px solid var(--border-default);
		border-left: 4px solid var(--success-text);
		border-radius: 8px;
		background: var(--surface-card);
		box-shadow: var(--shadow-xs);
		overflow: hidden;
	}

	.finding-block--conflict {
		border-left-color: var(--danger-text);
	}

	.finding-block--conditional {
		border-left-color: var(--info-text);
	}

	.finding-block--limited {
		border-left-color: var(--warning-text);
	}

	.finding-header {
		display: grid;
		grid-template-columns: 64px minmax(0, 1fr) auto;
		align-items: start;
		gap: 16px;
		padding: 18px 18px 16px;
		background: var(--surface-card);
	}

	.finding-number {
		padding-top: 3px;
		color: var(--text-tertiary);
		font-size: 10px;
		font-weight: 750;
		line-height: 1.35;
		text-transform: uppercase;
	}

	.finding-copy {
		min-width: 0;
	}

	.finding-status,
	.evidence-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 1.4;
		text-transform: capitalize;
	}

	.finding-copy h4 {
		max-width: 80ch;
		margin: 7px 0 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 720;
		letter-spacing: 0;
		line-height: 1.45;
		overflow-wrap: anywhere;
	}

	.finding-axis {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 6px;
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 1.5;
	}

	.finding-axis strong {
		color: var(--text-primary);
	}

	.finding-link {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 34px;
		padding: 6px 10px;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--brand-primary);
		font-size: 12px;
		font-weight: 700;
		white-space: nowrap;
		transition:
			border-color 120ms ease,
			background-color 120ms ease;
	}

	.finding-link:hover,
	.finding-link:focus-visible {
		border-color: var(--brand-primary);
		background: var(--brand-soft);
		outline: none;
	}

	.finding-limitations {
		display: grid;
		grid-template-columns: 120px minmax(0, 1fr);
		gap: 12px;
		padding: 10px 18px;
		border-top: 1px solid var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 12px;
	}

	.finding-limitations p {
		margin: 0;
		line-height: 1.5;
	}

	.evidence-groups {
		display: grid;
		border-top: 1px solid var(--border-default);
	}

	.evidence-group {
		display: grid;
		grid-template-columns: 152px minmax(0, 1fr);
		min-width: 0;
		border-top: 1px solid var(--border-default);
	}

	.evidence-group:first-child {
		border-top: 0;
	}

	.evidence-group > header {
		display: grid;
		grid-template-columns: 8px minmax(0, 1fr) auto;
		align-content: start;
		gap: 8px;
		padding: 16px 14px;
		border-right: 1px solid var(--border-default);
		background: var(--bg-subtle);
	}

	.evidence-group > header h5 {
		margin: 0;
		font-size: 12px;
		line-height: 1.4;
	}

	.evidence-group > header > span:last-child {
		color: var(--text-tertiary);
		font-size: 11px;
		font-weight: 700;
	}

	.relation-mark {
		width: 7px;
		height: 7px;
		margin-top: 5px;
		border-radius: 50%;
		background: currentColor;
	}

	.evidence-group--support > header {
		color: var(--success-text);
	}

	.evidence-group--contradiction > header {
		color: var(--danger-text);
	}

	.evidence-group--context > header {
		color: var(--info-text);
	}

	.evidence-list {
		min-width: 0;
	}

	.evidence-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(210px, 0.42fr);
		gap: 16px;
		min-width: 0;
		padding: 15px 16px;
		border-top: 1px solid var(--border-default);
	}

	.evidence-row:first-child {
		border-top: 0;
	}

	.evidence-copy {
		min-width: 0;
	}

	.evidence-copy > strong,
	.review-row strong,
	.paper-row strong {
		display: block;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}

	.evidence-meta {
		margin-top: 5px;
	}

	.condition-boundary {
		color: var(--warning-text);
		font-weight: 700;
	}

	.evidence-copy blockquote {
		margin: 10px 0 0;
		padding-left: 11px;
		border-left: 2px solid var(--border-strong);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 1.45;
	}

	.source-links {
		display: grid;
		align-content: start;
		gap: 7px;
		min-width: 0;
	}

	.source-link {
		display: grid;
		gap: 2px;
		min-width: 0;
		padding: 9px 10px;
		border-left: 2px solid var(--brand-primary);
		background: var(--brand-soft);
		color: var(--brand-primary);
		transition: background-color 120ms ease;
	}

	.source-link:hover,
	.source-link:focus-visible {
		background: var(--info-bg);
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}

	.source-link > span {
		font-size: 9px;
		font-weight: 750;
		line-height: 1.3;
		text-transform: uppercase;
	}

	.source-link strong {
		font-size: 12px;
		line-height: 1.4;
		overflow-wrap: anywhere;
	}

	.source-link small {
		color: var(--text-secondary);
		font-size: 10px;
		line-height: 1.4;
	}

	.empty-evidence,
	.empty-findings {
		margin: 0;
		padding: 18px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 1.5;
	}

	.review-list {
		display: grid;
		border: 1px solid var(--warning-border);
		border-radius: 8px;
		background: var(--surface-card);
		overflow: hidden;
	}

	.review-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(210px, 0.42fr);
		gap: 16px;
		padding: 14px 16px;
		border-top: 1px solid var(--border-default);
	}

	.review-row:first-child {
		border-top: 0;
	}

	.review-row > div:first-child {
		min-width: 0;
	}

	.review-row .status-pill {
		margin-bottom: 7px;
	}

	.review-row p {
		margin: 5px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 1.5;
	}

	.paper-list {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
	}

	.paper-row {
		display: grid;
		align-content: start;
		gap: 5px;
		min-width: 0;
		min-height: 92px;
		padding: 12px 14px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		transition:
			border-color 120ms ease,
			background-color 120ms ease;
	}

	.paper-row:hover,
	.paper-row:focus-visible {
		border-color: var(--brand-primary);
		background: var(--brand-soft);
		outline: none;
	}

	.paper-row--failed {
		border-color: var(--warning-border);
	}

	.paper-row--excluded {
		opacity: 0.78;
	}

	.paper-status {
		width: fit-content;
		color: var(--success-text);
		font-size: 10px;
		font-weight: 750;
		line-height: 1.3;
		text-transform: uppercase;
	}

	.paper-row--failed .paper-status,
	.paper-reason {
		color: var(--warning-text);
	}

	.paper-reason {
		font-size: 11px;
		line-height: 1.4;
	}

	@media (max-width: 1099px) {
		.summary-grid {
			grid-template-columns: 1fr;
		}

		.paper-list {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	@media (max-width: 760px) {
		.map {
			gap: 15px;
		}

		.objective-context {
			padding: 15px;
		}

		.objective-context h3 {
			font-size: 17px;
		}

		.objective-context dl {
			grid-template-columns: 1fr;
			gap: 10px;
		}

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

		.finding-header {
			grid-template-columns: 1fr;
			gap: 8px;
			padding: 15px;
		}

		.finding-link {
			width: fit-content;
		}

		.finding-limitations,
		.evidence-group,
		.evidence-row,
		.review-row {
			grid-template-columns: 1fr;
		}

		.evidence-group > header {
			border-right: 0;
			border-bottom: 1px solid var(--border-default);
		}

		.source-links {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.paper-list {
			grid-template-columns: 1fr;
		}

		.section-heading {
			align-items: center;
		}

		.section-heading p {
			display: none;
		}
	}

	@media (max-width: 460px) {
		.source-links {
			grid-template-columns: 1fr;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.finding-link,
		.source-link,
		.paper-row {
			transition: none;
		}
	}
</style>
