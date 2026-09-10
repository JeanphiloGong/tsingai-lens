<script lang="ts">
	import { tick } from 'svelte';
	import { Pencil, ChevronLeft, ChevronRight, ChevronDown, RotateCcw, Quote } from '@lucide/svelte';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { t } from '../../../_shared/i18n';
	import { resolve } from '$app/paths';
	import type {
		ChatMessage,
		ChatSourceContext,
		ChatBranchOptions
	} from '../../../_shared/chatSessions';
	import { formatTime } from './conversationPresentation';
	import MessageContent from './MessageContent.svelte';
	export let message: ChatMessage;
	export let disabled = false;
	export let retryAvailable = false;
	export let versions: ChatBranchOptions | undefined = undefined;
	export let onRevise: (message: ChatMessage, content?: string) => Promise<boolean> = async () =>
		false;
	export let onSwitchVersion: (sessionId: string) => void = () => {};
	let editing = false;
	let draft = '';
	let saving = false;
	let editError = '';
	let editor: HTMLTextAreaElement;
	let actions: HTMLDivElement;
	$: versionIndex = versions?.session_ids.indexOf(versions.active_session_id) ?? 0;

	async function openEditor() {
		draft = message.content;
		editError = '';
		editing = true;
		await tick();
		editor?.focus();
	}

	async function cancelEditor() {
		editing = false;
		await tick();
		actions?.querySelector<HTMLButtonElement>('button')?.focus();
	}

	async function saveEdit() {
		if (disabled || saving || !draft.trim()) return;
		saving = true;
		editError = '';
		try {
			if (await onRevise(message, draft.trim())) editing = false;
			else editError = $t('researchAgent.revision.failed');
		} finally {
			saving = false;
		}
	}

	function editorKeydown(event: KeyboardEvent) {
		if (event.isComposing || event.keyCode === 229) return;
		if (event.key === 'Escape' && !saving) void cancelEditor();
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			void saveEdit();
		}
	}
	function sourceContextHref(source: ChatSourceContext): `/collections/${string}` {
		const documentPath = `/collections/${source.collection_id}/documents/${source.document_id}`;
		const href = source.resource_ref.href;
		return href?.startsWith(documentPath)
			? (href as `/collections/${string}`)
			: (documentPath as `/collections/${string}`);
	}
</script>

<article class="user-message" data-testid="user-message">
	<div class:editing>
		<time>{formatTime(message.created_at)}</time>
		{#if message.source_contexts.length}
			<details class="message-sources">
				<summary
					><Quote size={14} /><span
						>{$t(
							message.source_contexts.length === 1
								? 'researchAgent.sourceContext.citedSingle'
								: 'researchAgent.sourceContext.cited',
							{
								count: message.source_contexts.length
							}
						)}</span
					><ChevronDown size={14} /></summary
				>
				<div class="message-source-list">
					{#each message.source_contexts as source (`${source.document_id}:${source.source_kind}:${source.source_ref}`)}
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
				</div>
			</details>
		{/if}
		{#if editing}
			<form on:submit|preventDefault={saveEdit} aria-busy={saving}>
				<textarea
					bind:this={editor}
					bind:value={draft}
					aria-label={$t('researchAgent.revision.edit')}
					rows="4"
					maxlength="12000"
					disabled={disabled || saving}
					on:keydown={editorKeydown}
				></textarea>
				{#if editError}<small class="edit-error" role="alert">{editError}</small>{/if}
				<div class="edit-actions">
					<button type="button" disabled={saving} on:click={cancelEditor}
						>{$t('researchAgent.revision.cancel')}</button
					>
					<button type="submit" class="save" disabled={disabled || saving || !draft.trim()}
						>{$t('researchAgent.revision.save')}</button
					>
				</div>
			</form>
		{:else}
			<div class="user-content"><MessageContent content={message.content} /></div>
			{#if !message.message_id.startsWith('local-')}
				<div class="message-actions" bind:this={actions}>
					<IconButton label={$t('researchAgent.revision.edit')} {disabled} onClick={openEditor}
						><Pencil size={16} /></IconButton
					>
					{#if retryAvailable}
						<IconButton
							label={$t('researchAgent.revision.regenerate')}
							{disabled}
							onClick={() => void onRevise(message)}><RotateCcw size={16} /></IconButton
						>
					{/if}
					{#if versions && versions.session_ids.length > 1}
						<IconButton
							label={$t('researchAgent.revision.previous')}
							disabled={disabled || versionIndex <= 0}
							onClick={() => onSwitchVersion(versions!.session_ids[versionIndex - 1])}
							><ChevronLeft size={16} /></IconButton
						>
						<span
							class="version"
							aria-label={$t('researchAgent.revision.version', {
								current: versionIndex + 1,
								total: versions.session_ids.length
							})}
						>
							{versionIndex + 1} / {versions.session_ids.length}
						</span>
						<IconButton
							label={$t('researchAgent.revision.next')}
							disabled={disabled || versionIndex >= versions.session_ids.length - 1}
							onClick={() => onSwitchVersion(versions!.session_ids[versionIndex + 1])}
							><ChevronRight size={16} /></IconButton
						>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</article>

<style>
	.message-actions,
	.edit-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 4px;
		margin-top: 4px;
	}
	.version {
		min-width: 40px;
		text-align: center;
		color: var(--text-tertiary);
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.user-message > div.editing {
		width: 620px;
		max-width: 100%;
	}
	textarea {
		box-sizing: border-box;
		width: 100%;
		min-height: 110px;
		max-height: 360px;
		resize: vertical;
		padding: 12px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 14px;
		line-height: 22px;
	}
	textarea:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	.edit-actions button {
		padding: 8px 12px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 13px;
		cursor: pointer;
	}
	.edit-actions button.save {
		background: var(--brand-primary);
		border-color: var(--brand-primary);
		color: #fff;
	}
	.edit-actions button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.edit-error {
		display: block;
		color: var(--text-secondary);
	}
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

	.user-content {
		margin: 0;
		padding: 12px 15px;
		border-radius: 8px 8px 2px 8px;
		background: var(--brand-soft);
		font-size: 14px;
		line-height: 22px;
		white-space: normal;
		overflow-wrap: anywhere;
	}

	.message-sources {
		margin-bottom: 6px;
	}
	.message-sources summary {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 6px;
		min-height: 32px;
		padding: 4px 0;
		list-style: none;
		color: var(--text-secondary);
		font-size: 12px;
		cursor: pointer;
	}
	.message-sources summary::-webkit-details-marker {
		display: none;
	}
	.message-sources summary:hover {
		color: var(--text-primary);
	}
	.message-sources summary:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	.message-sources summary :global(svg) {
		flex-shrink: 0;
	}
	.message-sources[open] summary > :global(svg:last-child) {
		transform: rotate(180deg);
	}
	.message-source-list {
		max-height: 300px;
		overflow-y: auto;
	}
	.message-source {
		display: grid;
		gap: 3px;
		margin-bottom: 7px;
		padding: 10px 12px;
		border-left: 2px solid var(--border-strong);
		color: var(--text-primary);
		text-align: left;
		text-decoration: none;
		overflow-wrap: anywhere;
	}
	.message-source:hover {
		background: var(--bg-subtle);
	}

	.message-source small {
		color: var(--text-tertiary);
	}

	.message-source span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
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
