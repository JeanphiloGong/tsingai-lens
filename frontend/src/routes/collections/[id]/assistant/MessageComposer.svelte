<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';
	import { authState } from '../../../_shared/auth';
	import IconButton from '../../../_shared/IconButton.svelte';
	import type { ChatSourceContext } from '../../../_shared/chatSessions';
	import type { PaperUploadItem } from './messageComposer';

	export let collectionId = '';
	export let input = '';
	export let sending = false;
	export let disabled = false;
	export let pendingSourceContexts: ChatSourceContext[] = [];
	export let hasExtraContext = false;
	export let onInput: (value: string) => void = () => {};
	export let onSend: (nextText?: string) => void = () => {};
	export let onRemovePendingSourceContexts: (index: number) => void = () => {};

	let uploadInput: HTMLInputElement | null = null;

	function handleComposerKeydown(event: KeyboardEvent) {
		if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229)
			return;
		event.preventDefault();
		onSend();
	}

	function fitInput(node: HTMLTextAreaElement, value: string) {
		const resize = () => {
			node.style.height = 'auto';
			node.style.height = `${Math.min(180, node.scrollHeight)}px`;
		};
		let width = 0;
		const observer = new ResizeObserver(([entry]) => {
			if (entry.contentRect.width !== width) {
				width = entry.contentRect.width;
				resize();
			}
		});
		observer.observe(node);
		node.value = value;
		resize();
		return {
			update(nextValue: string) {
				node.value = nextValue;
				resize();
			},
			destroy() {
				observer.disconnect();
			}
		};
	}
	import {
		isDuplicateCollectionDocumentError,
		uploadCollectionDocument
	} from '../../../_shared/collectionDocuments';
	import { prepareCollectionDocument } from '../../../_shared/pipelineRuns';
	import { errorMessage } from '../../../_shared/api';
	import { onDestroy } from 'svelte';
	let uploadItems: PaperUploadItem[] = [];
	let uploadLoading = false;
	let uploadError = '';
	let uploadNotice = '';
	let uploadSequence = 0;
	let uploadGeneration = 0;
	let destroyed = false;
	let uploadCollectionId = '';
	onDestroy(() => {
		destroyed = true;
	});
	$: uploadCandidates = uploadItems.filter((item) =>
		['selected', 'upload_failed', 'preparation_failed'].includes(item.status)
	);
	$: uploadBusy =
		uploadLoading || uploadItems.some((item) => ['uploading', 'preparing'].includes(item.status));
	$: uploadActionText = getUploadActionText(uploadBusy, uploadCandidates);

	$: if (collectionId !== uploadCollectionId) {
		uploadCollectionId = collectionId;
		uploadGeneration += 1;
		uploadItems = [];
		uploadLoading = false;
		uploadError = '';
		uploadNotice = '';
		uploadSequence = 0;
	}
	function isPdf(file: File) {
		return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
	}

	function selectUploadFiles(event: Event) {
		const target = event.currentTarget as HTMLInputElement;
		const files = Array.from(target.files ?? []);
		const validFiles = files.filter(isPdf);
		uploadError =
			validFiles.length === files.length ? '' : $t('researchAgent.upload.unsupportedFile');
		uploadNotice = '';

		const existing = new Set(
			uploadItems.map((item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`)
		);
		const selected = validFiles
			.filter((file) => !existing.has(`${file.name}:${file.size}:${file.lastModified}`))
			.map((file) => ({
				key: `upload-${uploadSequence++}`,
				file,
				status: 'selected' as const,
				documentId: null,
				error: ''
			}));
		uploadItems = [...uploadItems, ...selected];
		target.value = '';
	}

	function updateUploadItem(key: string, patch: Partial<PaperUploadItem>) {
		uploadItems = uploadItems.map((item) => (item.key === key ? { ...item, ...patch } : item));
	}

	async function uploadAndPrepareItem(
		item: PaperUploadItem,
		ownerCollectionId: string,
		generation: number
	) {
		const ownerUserId = $authState.user?.user_id;
		const update = (patch: Partial<PaperUploadItem>) => {
			if (!destroyed && generation === uploadGeneration && ownerCollectionId === collectionId) {
				updateUploadItem(item.key, patch);
			}
		};
		let documentId = item.documentId;
		if (!documentId) {
			update({ status: 'uploading', error: '' });
			try {
				const uploaded = await uploadCollectionDocument(
					ownerCollectionId,
					item.file,
					item.status === 'upload_failed'
				);
				documentId = uploaded.document_id;
			} catch (err) {
				if (isDuplicateCollectionDocumentError(err) && item.status !== 'upload_failed') {
					update({ status: 'already_uploaded', error: '' });
					return 'already_uploaded';
				}
				update({ status: 'upload_failed', error: errorMessage(err) });
				return 'failed';
			}
		}
		update({ status: 'preparing', documentId, error: '' });

		if (!ownerUserId || $authState.user?.user_id !== ownerUserId) return 'failed';
		try {
			await prepareCollectionDocument(ownerCollectionId, documentId);
			update({ status: 'queued', documentId, error: '' });
			return 'queued';
		} catch (err) {
			update({
				status: 'preparation_failed',
				documentId,
				error: errorMessage(err)
			});
			return 'failed';
		}
	}

	async function uploadPapers() {
		if (!uploadCandidates.length || uploadLoading) return;
		const ownerCollectionId = collectionId;
		const generation = uploadGeneration;
		const candidates = [...uploadCandidates];
		uploadLoading = true;
		uploadError = '';
		uploadNotice = '';
		let queuedCount = 0;
		let alreadyUploadedCount = 0;
		let failedCount = 0;
		for (const item of candidates) {
			if (destroyed || generation !== uploadGeneration || ownerCollectionId !== collectionId)
				return;
			const result = await uploadAndPrepareItem(item, ownerCollectionId, generation);
			if (result === 'queued') queuedCount += 1;
			if (result === 'already_uploaded') alreadyUploadedCount += 1;
			if (result === 'failed') failedCount += 1;
		}
		if (destroyed || generation !== uploadGeneration || ownerCollectionId !== collectionId) return;
		const notices = [];
		if (queuedCount) notices.push($t('researchAgent.upload.queuedSummary', { count: queuedCount }));
		if (alreadyUploadedCount)
			notices.push(
				$t('researchAgent.upload.alreadyUploadedSummary', { count: alreadyUploadedCount })
			);
		uploadNotice = notices.join(' ');
		if (failedCount) {
			uploadError = $t('researchAgent.upload.failedSummary', { count: failedCount });
		}
		uploadLoading = false;
	}

	function clearUploadItems() {
		if (uploadLoading) return;
		uploadItems = [];
		uploadError = '';
		uploadNotice = '';
	}

	function uploadStatus(item: PaperUploadItem) {
		return $t(`researchAgent.upload.status.${item.status}`);
	}

	function getUploadActionText(busy: boolean, candidates: PaperUploadItem[]) {
		if (busy) return $t('researchAgent.upload.uploading');
		const retry =
			candidates.length > 0 && candidates.every((item) => item.status.endsWith('_failed'));
		if (retry) {
			return $t(
				candidates.length === 1
					? 'researchAgent.upload.retryOne'
					: 'researchAgent.upload.retryMany',
				{ count: candidates.length }
			);
		}
		return $t(
			candidates.length === 1
				? 'researchAgent.upload.uploadOne'
				: 'researchAgent.upload.uploadMany',
			{ count: candidates.length }
		);
	}
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
		on:change={selectUploadFiles}
	/>
	{#if uploadItems.length || uploadError || pendingSourceContexts.length || hasExtraContext}
		<div class="composer-context">
			<slot />
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
							on:click={clearUploadItems}
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
								on:click={uploadPapers}
							>
								{uploadActionText}
							</button>
						{/if}
					</footer>
				</section>
			{:else if uploadError}
				<p class="upload-error upload-error--standalone" role="alert">{uploadError}</p>
			{/if}
			{#each pendingSourceContexts as source, index (`${source.document_id}:${source.source_kind}:${source.source_ref}`)}
				<div class="source-context-preview" data-testid="pending-source-context">
					<div>
						<strong>{source.document_title}</strong>
						<small>
							{source.heading_path ?? source.source_kind}
							{#if source.page}
								· {$t('workbench.pageLabel', { page: source.page })}{/if}
						</small>
						{#if source.quote_truncated}
							<small>{$t('researchAgent.sourceContext.truncated')}</small>
						{/if}
						<p>{source.quote}</p>
					</div>
					<button
						type="button"
						class="remove-source-context"
						aria-label={$t('researchAgent.sourceContext.remove')}
						title={$t('researchAgent.sourceContext.remove')}
						{disabled}
						on:click={() => onRemovePendingSourceContexts(index)}>×</button
					>
				</div>
			{/each}
		</div>
	{/if}
	<div class="composer-row">
		<div class="composer-shell">
			<IconButton
				className="add-papers"
				label={$t('researchAgent.upload.add')}
				tooltipAlign="start"
				disabled={uploadBusy}
				onClick={() => uploadInput?.click()}>+</IconButton
			>
			<label class="sr-only" for="research-agent-message">{$t('researchAgent.messageLabel')}</label>
			<textarea
				id="research-agent-message"
				rows="1"
				value={input}
				use:fitInput={input}
				placeholder={$t('researchAgent.messagePlaceholder')}
				{disabled}
				on:input={(event) => onInput((event.currentTarget as HTMLTextAreaElement).value)}
				on:keydown={handleComposerKeydown}
			></textarea>
			<IconButton
				className="send-message"
				type="submit"
				variant="primary"
				tooltipAlign="end"
				label={sending ? $t('researchAgent.sending') : $t('researchAgent.send')}
				disabled={disabled || !input.trim()}>&uarr;</IconButton
			>
		</div>
	</div>
</form>

<style>
	.composer {
		display: flex;
		flex-direction: column;
		flex: 0 1 auto;
		min-height: 0;
		max-height: 70%;
		gap: 10px;
		padding: 12px 32px max(14px, env(safe-area-inset-bottom));
		border-top: 1px solid var(--border-default);
		background: color-mix(in srgb, var(--bg-page) 94%, var(--surface-card));
	}

	.composer-context {
		display: grid;
		grid-auto-rows: max-content;
		gap: 10px;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
	}

	.composer-row {
		flex: 0 0 auto;
		width: min(100%, 900px);
		margin: 0 auto;
	}

	.composer-shell {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: end;
		gap: 8px;
		min-height: 56px;
		padding: 8px 10px 8px 10px;
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

	textarea {
		width: 100%;
		min-height: 38px;
		max-height: min(180px, 16dvh);
		padding: 9px 0;
		border: 0;
		background: transparent;
		color: var(--text-primary);
		font: inherit;
		line-height: 22px;
		resize: none;
	}

	textarea:focus {
		outline: none;
	}

	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}

	.upload-panel {
		display: grid;
		gap: 10px;
		width: min(100%, 900px);
		margin: 0 auto;
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

	.upload-panel > header > div,
	.upload-panel li > div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}

	.upload-panel > header strong,
	.upload-panel li strong {
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

	.upload-panel li strong {
		overflow: hidden;
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
		width: min(100%, 900px);
		margin: 0 auto;
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
	.upload-primary {
		min-height: 30px;
		padding: 0 10px;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 12px;
		cursor: pointer;
	}

	.upload-primary {
		min-height: 36px;
		border-color: var(--brand-primary);
		background: var(--brand-primary);
		color: #fff;
		font-weight: 700;
	}

	.upload-primary:hover:not(:disabled) {
		border-color: var(--brand-primary-hover);
		background: var(--brand-primary-hover);
	}

	.source-context-preview {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 12px;
		width: min(100%, 900px);
		margin: 0 auto;
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

	.remove-source-context {
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

		.composer-shell {
			min-height: 52px;
			padding-left: 8px;
			padding-right: 8px;
		}

		.upload-panel > header,
		.upload-panel > footer {
			align-items: flex-start;
		}
	}
</style>
