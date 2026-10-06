<script lang="ts">
	import { ChevronDown, ExternalLink } from '@lucide/svelte';
	import { t } from '../../../_shared/i18n';
	import { resolve } from '$app/paths';
	import type { ChatMessage, ChatResourceRef } from '../../../_shared/chatSessions';

	export let message: ChatMessage;
	$: resources = visibleResources(message);
	type SourceRecord = Record<string, unknown>;
	type VisibleResource = ChatResourceRef & { href: `/collections/${string}`; label: string };

	function text(value: unknown) {
		return typeof value === 'string' && value.trim() ? value.trim() : '';
	}

	function sourceRecords(message: ChatMessage) {
		const data = message.tool_result?.data ?? {};
		const document = data.document;
		const documentTitle =
			text(data.document_title) ||
			text(data.filename) ||
			(document && typeof document === 'object'
				? text((document as SourceRecord).title) || text((document as SourceRecord).filename)
				: '');
		return [data.sources, data.matches].flatMap((value) =>
			Array.isArray(value)
				? value
						.filter((item): item is SourceRecord => Boolean(item) && typeof item === 'object')
						.map((item) => ({
							...item,
							document_title: text(item.document_title) || documentTitle
						}))
				: []
		);
	}

	function resourceSource(resource: ChatResourceRef, records: SourceRecord[]) {
		return records.find(
			(record) =>
				text(record.source_ref) === resource.resource_id ||
				text(record.table_ref) === resource.resource_id ||
				text(record.resource_id) === resource.resource_id
		);
	}

	function resourceLabel(resource: ChatResourceRef, record: SourceRecord | undefined) {
		const document = record?.document;
		const documentTitle =
			text(record?.filename) ||
			text(record?.document_title) ||
			text(record?.title) ||
			(document && typeof document === 'object'
				? text((document as SourceRecord).title) || text((document as SourceRecord).filename)
				: '');
		if (resource.resource_type === 'document') {
			return documentTitle || $t('researchAgent.resource.document');
		}
		if (resource.resource_type !== 'source') {
			const labels: Record<string, string> = {
				collection: $t('researchAgent.resource.collection'),
				research_objective: $t('researchAgent.resource.objective'),
				finding: $t('researchAgent.resource.finding'),
				evidence: $t('researchAgent.resource.evidence'),
				research_plan: $t('researchAgent.resource.researchPlan'),
				objective_analysis: $t('researchAgent.resource.analysis'),
				pipeline_run: $t('researchAgent.resource.researchProcess')
			};
			return labels[resource.resource_type] || $t('researchAgent.resource.other');
		}
		const location = [
			text(record?.heading_path) || text(record?.source_kind),
			record?.page !== undefined && record?.page !== null
				? $t('researchAgent.resource.page', { page: String(record.page) })
				: ''
		]
			.filter(Boolean)
			.join(' · ');
		return (
			[documentTitle, location].filter(Boolean).join(' · ') || $t('researchAgent.resource.source')
		);
	}

	function visibleResources(message: ChatMessage): VisibleResource[] {
		const records = sourceRecords(message);
		const seen = new Set<string>();
		return (message.tool_result?.resource_refs ?? []).flatMap((resource) => {
			if (typeof resource.href !== 'string' || !resource.href.startsWith('/collections/'))
				return [];
			if (seen.has(resource.href)) return [];
			seen.add(resource.href);
			return [
				{
					...resource,
					href: resource.href as `/collections/${string}`,
					label: resourceLabel(resource, resourceSource(resource, records))
				}
			];
		});
	}
</script>

{#if resources.length}
	<nav class="resource-links" aria-label={$t('researchAgent.resources')}>
		{#if resources.length === 1}
			<a href={resolve(resources[0].href)}>
				<span>{resources[0].label}</span><ExternalLink size={13} aria-hidden="true" />
			</a>
		{:else}
			<details class="resource-group">
				<summary>
					<span>{$t('researchAgent.resource.sourceCount', { count: resources.length })}</span>
					<ChevronDown size={14} aria-hidden="true" />
				</summary>
				<div class="resource-list">
					{#each resources as resource (resource.href)}
						<a href={resolve(resource.href)}>
							<span>{resource.label}</span><ExternalLink size={12} aria-hidden="true" />
						</a>
					{/each}
				</div>
			</details>
		{/if}
	</nav>
{/if}

<style>
	.resource-links {
		margin-top: 12px;
		font-size: 12px;
	}
	.resource-links a,
	.resource-group summary {
		color: var(--brand-primary);
		font-weight: 700;
		text-decoration: none;
	}
	.resource-links a {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 100%;
	}
	.resource-links a span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.resource-links a:hover {
		text-decoration: underline;
	}
	.resource-group {
		width: fit-content;
		max-width: 100%;
	}
	.resource-group summary {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		cursor: pointer;
		list-style: none;
	}
	.resource-group summary::-webkit-details-marker {
		display: none;
	}
	.resource-list {
		display: grid;
		gap: 7px;
		margin-top: 8px;
		padding-left: 2px;
	}
</style>
