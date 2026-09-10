<script lang="ts">
	import ResearchConversation from './ResearchConversation.svelte';
	import { t } from '../../../_shared/i18n';
</script>

<svelte:head><title>{$t('researchAgent.title')}</title></svelte:head>

<ResearchConversation />
