<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import { resolve } from '$app/paths';
	import type { ChatMessage, ChatSourceContext } from '../../../_shared/chatSessions';
	import { formatTime } from './conversationPresentation';
	export let message: ChatMessage;
	function sourceContextHref(source: ChatSourceContext): `/collections/${string}` {
		const documentPath = `/collections/${source.collection_id}/documents/${source.document_id}`;
		const href = source.resource_ref.href;
		return href?.startsWith(documentPath)
			? (href as `/collections/${string}`)
			: (documentPath as `/collections/${string}`);
	}
</script>

<article class="user-message" data-testid="user-message">
	<div>
		<time>{formatTime(message.created_at)}</time>
		{#if message.source_contexts.length}
			{#each message.source_contexts as source (`${source.document_id}:${source.source_ref}`)}
				<a class="message-source" href={resolve(sourceContextHref(source))}>
					<strong>{source.document_title}</strong>
					<small>
						{source.heading_path ?? source.source_kind}
						{#if source.page}
							· {$t('workbench.pageLabel', { page: source.page })}{/if}
					</small>
					{#if source.quote_truncated}
						<small>{$t('researchAgent.sourceContext.truncated')}</small>
					{/if}
					<span>{source.quote}</span>
				</a>
			{/each}
		{/if}
		<p>{message.content}</p>
	</div>
</article>

<style>
	.user-message {
		display: flex;
		justify-content: flex-end;
		margin-bottom: 24px;
		animation: message-enter 180ms ease both;
	}

	.user-message > div {
		max-width: min(72%, 620px);
	}

	.user-message time {
		display: block;
		margin-bottom: 5px;
		color: var(--text-tertiary);
		font-size: 11px;
	}

	.user-message time {
		text-align: right;
	}

	.user-message p {
		margin: 0;
		padding: 12px 15px;
		border-radius: 8px 8px 2px 8px;
		background: var(--brand-soft);
		font-size: 14px;
		line-height: 22px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.message-source {
		display: grid;
		gap: 3px;
		margin-bottom: 7px;
		padding: 10px 12px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		text-align: left;
		text-decoration: none;
	}

	.message-source small {
		color: var(--text-tertiary);
	}

	.message-source span {
		display: -webkit-box;
		overflow: hidden;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 3;
		line-clamp: 3;
	}

	@media (max-width: 560px) {
		.user-message > div {
			max-width: 90%;
		}
	}

	@keyframes message-enter {
		from {
			opacity: 0;
			transform: translateY(6px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
