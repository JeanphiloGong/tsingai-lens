<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';
	import type { ChatSession, ChatSourceContext, ChatToolCall } from '../../../_shared/chatSessions';
	import type { PaperUploadItem } from './messageComposer';

	export let collectionId = '';
	export let session: ChatSession | null = null;
	export let input = '';
	export let sending = false;
	export let deciding = false;
	export let pendingApproval: ChatToolCall | null = null;
	export let pendingSourceContext: ChatSourceContext | null = null;
	export let uploadItems: PaperUploadItem[] = [];
	export let uploadLoading = false;
	export let uploadError = '';
	export let uploadNotice = '';
	export let uploadCandidates: PaperUploadItem[] = [];
	export let uploadBusy = false;
	export let uploadActionText = '';
	export let onInput: (value: string) => void = () => {};
	export let onSend: (nextText?: string) => void = () => {};
	export let onSelectUploadFiles: (event: Event) => void = () => {};
	export let onClearUploadItems: () => void = () => {};
	export let onUploadPapers: () => void = () => {};
	export let onRemovePendingSourceContext: () => void = () => {};
	export let uploadStatus: (item: PaperUploadItem) => string = () => '';

	let uploadInput: HTMLInputElement | null = null;
</script>

<form class="composer" on:submit|preventDefault={() => onSend()}>
	<input
		class="sr-only"
		bind:this={uploadInput}
		type="file"
		multiple
		accept=".pdf,application/pdf"
		aria-label={$t('researchAgent.upload.choose')}
		disabled={uploadLoading}
		on:change={onSelectUploadFiles}
	/>
	{#if uploadItems.length}
		<section class="upload-panel" aria-label={$t('researchAgent.upload.panelTitle')}>
			<header>
				<div>
					<strong>{$t('researchAgent.upload.panelTitle')}</strong>
					<small>{$t('researchAgent.upload.panelBody')}</small>
				</div>
				<button
					type="button"
					class="clear-uploads"
					disabled={uploadLoading}
					on:click={onClearUploadItems}
				>
					{$t('researchAgent.upload.clear')}
				</button>
			</header>
			<ul aria-live="polite">
				{#each uploadItems as item (item.key)}
					<li>
						<span class="pdf-mark" aria-hidden="true">PDF</span>
						<div>
							<strong>{item.file.name}</strong>
							<small>{uploadStatus(item)}</small>
							{#if item.error}<small class="upload-item-error">{item.error}</small>{/if}
						</div>
					</li>
				{/each}
			</ul>
			{#if uploadError}<p class="upload-error" role="alert">{uploadError}</p>{/if}
			{#if uploadNotice}<p class="upload-notice" role="status">{uploadNotice}</p>{/if}
			<footer>
				<a href={resolve('/collections/[id]', { id: collectionId })}>
					{$t('researchAgent.upload.openProgress')}
				</a>
				{#if uploadCandidates.length || uploadBusy}
					<button
						type="button"
						class="upload-primary"
						aria-label={uploadActionText}
						disabled={uploadBusy}
						on:click={onUploadPapers}
					>
						{uploadActionText}
					</button>
				{/if}
			</footer>
		</section>
	{:else if uploadError}
		<p class="upload-error upload-error--standalone" role="alert">{uploadError}</p>
	{/if}
	{#if pendingSourceContext}
		<div class="source-context-preview" data-testid="pending-source-context">
			<div>
				<strong>{pendingSourceContext.document_title}</strong>
				<small>
					{pendingSourceContext.heading_path ?? pendingSourceContext.source_kind}
					{#if pendingSourceContext.page}
						· {$t('workbench.pageLabel', { page: pendingSourceContext.page })}{/if}
				</small>
				{#if pendingSourceContext.quote_truncated}
					<small>{$t('researchAgent.sourceContext.truncated')}</small>
				{/if}
				<p>{pendingSourceContext.quote}</p>
			</div>
			<button
				type="button"
				class="remove-source-context"
				aria-label={$t('researchAgent.sourceContext.remove')}
				title={$t('researchAgent.sourceContext.remove')}
				on:click={onRemovePendingSourceContext}>×</button
			>
		</div>
	{/if}
	<div class="composer-row">
		<div class="composer-shell">
			<label class="sr-only" for="research-agent-message">{$t('researchAgent.messageLabel')}</label>
			<textarea
				id="research-agent-message"
				rows="1"
				value={input}
				on:input={(event) => onInput((event.currentTarget as HTMLTextAreaElement).value)}
				placeholder={$t('researchAgent.messagePlaceholder')}
				disabled={!session || sending || deciding || Boolean(pendingApproval)}
			></textarea>
			<div class="composer-actions">
				<button
					class="add-papers"
					type="button"
					aria-label={$t('researchAgent.upload.add')}
					title={$t('researchAgent.upload.add')}
					disabled={uploadBusy}
					on:click={() => uploadInput?.click()}
				>
					<span aria-hidden="true">+</span>
				</button>
				<button
					class="send-message"
					type="submit"
					aria-label={sending ? $t('researchAgent.sending') : $t('researchAgent.send')}
					title={sending ? $t('researchAgent.sending') : $t('researchAgent.send')}
					disabled={!session || sending || deciding || Boolean(pendingApproval) || !input.trim()}
				>
					<span aria-hidden="true">↑</span>
				</button>
			</div>
		</div>
	</div>
</form>

<style>
	.composer {
		display: grid;
		gap: 10px;
		width: 100%;
		padding: 16px 32px max(20px, env(safe-area-inset-bottom));
		border-top: 1px solid var(--border-default);
		background: var(--surface-card);
		box-sizing: border-box;
	}

	.composer > * {
		width: min(100%, 900px);
		margin-right: auto;
		margin-left: auto;
	}

	.composer-row {
		display: block;
		width: 100%;
	}

	.composer-shell {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: end;
		gap: 8px;
		min-height: 56px;
		padding: 8px 10px 8px 14px;
		border: 1px solid var(--border-strong);
		border-radius: 24px;
		background: var(--surface-card);
		box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
		transition:
			border-color 140ms ease,
			box-shadow 140ms ease;
	}

	.composer-shell:focus-within {
		border-color: var(--brand-primary);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand-primary) 14%, transparent);
	}

	.composer-row textarea {
		width: 100%;
		min-height: 38px;
		max-height: 180px;
		padding: 9px 0;
		border: 0;
		background: transparent;
		color: var(--text-primary);
		font: inherit;
		line-height: 22px;
		resize: none;
	}

	.upload-panel {
		display: grid;
		gap: 10px;
		padding: 12px 14px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--bg-subtle);
	}

	.upload-panel > header,
	.upload-panel > footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.upload-panel > header > div {
		display: grid;
		gap: 2px;
	}

	.upload-panel > header strong {
		font-size: 13px;
	}

	.upload-panel > header small,
	.upload-panel li small {
		color: var(--text-secondary);
		font-size: 12px;
	}

	.upload-panel ul {
		display: grid;
		gap: 7px;
		max-height: 152px;
		margin: 0;
		padding: 0;
		overflow-y: auto;
		list-style: none;
	}

	.upload-panel li {
		display: grid;
		grid-template-columns: 34px minmax(0, 1fr);
		align-items: center;
		gap: 9px;
	}

	.upload-panel li > div {
		display: grid;
		min-width: 0;
		gap: 1px;
	}

	.upload-panel li strong {
		overflow: hidden;
		font-size: 12px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.pdf-mark {
		display: grid;
		place-items: center;
		width: 34px;
		height: 28px;
		border: 1px solid var(--border-strong);
		border-radius: 4px;
		background: var(--surface-card);
		color: var(--danger-text);
		font-size: 9px;
		font-weight: 800;
	}

	.upload-panel .upload-item-error,
	.upload-error {
		color: var(--danger-text);
	}

	.upload-error,
	.upload-notice {
		margin: 0;
		font-size: 12px;
	}

	.upload-notice {
		color: var(--success-text);
	}

	.upload-error--standalone {
		padding: 8px 10px;
		border: 1px solid var(--danger-border);
		border-radius: 6px;
		background: var(--danger-bg);
	}

	.upload-panel > footer a {
		color: var(--brand-primary);
		font-size: 12px;
		font-weight: 700;
		text-decoration: none;
	}

	.upload-panel > footer a:hover {
		text-decoration: underline;
	}

	.clear-uploads,
	.add-papers {
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		cursor: pointer;
	}

	.clear-uploads {
		min-height: 30px;
		padding: 0 10px;
		font-size: 12px;
	}

	.add-papers {
		display: inline-flex;
		align-items: center;
		align-self: end;
		justify-content: center;
		gap: 6px;
		min-height: 42px;
		padding: 0 12px;
		font-weight: 700;
	}

	.composer-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.add-papers > span:first-child {
		font-size: 22px;
		font-weight: 400;
		line-height: 1;
	}

	.clear-uploads:hover:not(:disabled),
	.add-papers:hover:not(:disabled) {
		border-color: var(--brand-border);
		background: var(--brand-soft);
	}

	.upload-primary {
		min-height: 36px;
		padding: 0 12px;
		border: 1px solid var(--brand-primary);
		border-radius: 6px;
		background: var(--brand-primary);
		color: #fff;
		font-weight: 700;
		cursor: pointer;
	}

	.source-context-preview {
		display: grid;
		grid-column: 1 / -1;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 12px;
		padding: 10px 12px;
		border: 1px solid var(--brand-border);
		border-radius: 6px;
		background: var(--brand-soft);
	}

	.source-context-preview > div {
		min-width: 0;
	}

	.source-context-preview strong,
	.source-context-preview small {
		display: block;
	}

	.source-context-preview small {
		margin-top: 2px;
		color: var(--text-tertiary);
	}

	.source-context-preview p {
		display: -webkit-box;
		margin: 5px 0 0;
		overflow: hidden;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 3;
		line-clamp: 3;
	}

	.composer .remove-source-context {
		width: 30px;
		height: 30px;
		min-width: 30px;
		min-height: 30px;
		align-self: start;
		padding: 0;
		border: 1px solid var(--border-default);
		border-radius: 50%;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 20px;
		font-weight: 400;
		line-height: 1;
	}

	.composer-row textarea:focus {
		outline: none;
	}

	.send-message,
	.add-papers {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		min-width: 36px;
		min-height: 36px;
		padding: 0;
		border-radius: 50%;
		font-weight: 700;
		line-height: 1;
		cursor: pointer;
		transition:
			background-color 140ms ease,
			border-color 140ms ease,
			color 140ms ease,
			transform 140ms ease;
	}

	.add-papers {
		border: 0;
		background: transparent;
		color: var(--text-secondary);
	}

	.add-papers:hover:not(:disabled) {
		border-color: transparent;
		background: var(--bg-subtle);
		color: var(--text-primary);
	}

	.send-message {
		border: 1px solid var(--brand-primary);
		background: var(--brand-primary);
		color: #fff;
	}

	.send-message > span {
		font-size: 20px;
		line-height: 1;
		transform: translateY(-1px);
	}

	.send-message:disabled {
		border-color: var(--border-default);
		background: var(--bg-subtle);
		color: var(--text-tertiary);
	}

	.send-message:hover:not(:disabled) {
		border-color: var(--brand-primary-hover);
		background: var(--brand-primary-hover);
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
	.upload-primary:hover:not(:disabled) {
		border-color: var(--brand-primary-hover);
		background: var(--brand-primary-hover);
		color: #fff;
		transform: translateY(-1px);
	}
	.send-message:active:not(:disabled),
	.upload-primary:active:not(:disabled) {
		transform: translateY(0);
	}
	@media (max-width: 820px) {
		.composer {
			padding-left: 18px;
			padding-right: 18px;
		}
	}
	@media (max-width: 560px) {
		.composer {
			gap: 8px;
			padding: 12px 12px max(12px, env(safe-area-inset-bottom));
		}

		.composer-row {
			display: block;
		}

		.composer-shell {
			min-height: 52px;
			padding-left: 12px;
			padding-right: 8px;
		}

		.composer-row textarea {
			min-height: 36px;
			resize: none;
		}

		.upload-panel > header,
		.upload-panel > footer {
			align-items: flex-start;
		}
	}
</style>
