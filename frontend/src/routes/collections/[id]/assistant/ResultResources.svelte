<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import { resolve } from '$app/paths';
	import type { ChatMessage, ChatResourceRef } from '../../../_shared/chatSessions';
	export let message: ChatMessage;
	function visibleResources(message: ChatMessage) {
		return (message.tool_result?.resource_refs ?? []).filter(
			(ref): ref is ChatResourceRef & { href: `/collections/${string}` } =>
				typeof ref.href === 'string' && ref.href.startsWith('/collections/')
		);
	}

	function resourceLabel(resourceType: string) {
		switch (resourceType) {
			case 'collection':
				return $t('researchAgent.resource.collection');
			case 'research_objective':
				return $t('researchAgent.resource.objective');
			case 'finding':
				return $t('researchAgent.resource.finding');
			case 'evidence':
				return $t('researchAgent.resource.evidence');
			case 'source':
				return $t('researchAgent.resource.source');
			case 'document':
				return $t('researchAgent.resource.document');
			case 'research_plan':
				return $t('researchAgent.resource.researchPlan');
			case 'objective_analysis':
				return $t('researchAgent.resource.analysis');
			case 'pipeline_run':
				return $t('researchAgent.resource.researchProcess');
			default:
				return $t('researchAgent.resource.other');
		}
	}
</script>

{#if visibleResources(message).length}<nav
		class="resource-links"
		aria-label={$t('researchAgent.resources')}
	>
		{#each visibleResources(message) as resource (resource.resource_type + ':' + resource.resource_id)}<a
				href={resolve(resource.href)}>{resourceLabel(resource.resource_type)}</a
			>{/each}
	</nav>{/if}

<style>
	.resource-links a {
		color: var(--brand-primary);
		font-weight: 700;
		text-decoration: none;
		transition: color 140ms ease;
	}

	.resource-links a:hover {
		text-decoration: underline;
	}

	.resource-links {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 14px;
		margin-top: 12px;
		font-size: 12px;
	}
</style>
