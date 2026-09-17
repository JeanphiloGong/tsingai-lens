<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { resolve } from '$app/paths';
	import {
		GitBranch,
		X,
		RefreshCw,
		ArrowLeft,
		ArrowRight,
		Pencil,
		Check,
		Clock3,
		Plus,
		Minus,
		Scan,
		LocateFixed
	} from '@lucide/svelte';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { t } from '../../../_shared/i18n';
	import type { ChatTree, ChatTreeNode } from '../../../_shared/chatSessions';
	import MessageContent from './MessageContent.svelte';

	export let tree: ChatTree | null = null;
	export let loading = false;
	export let error = '';
	export let disabled = false;
	export let onClose: () => void;
	export let onRefresh: () => void;
	export let onSelect: (node: ChatTreeNode) => void;
	export let onRevise: (node: ChatTreeNode, content: string) => Promise<boolean>;
	let dialog: HTMLDialogElement;
	let selectedId = '';
	let mobilePreview = false;
	let editing = false;
	let draft = '';
	let editError = false;
	let viewport: HTMLDivElement;
	let graphWidth = 0;
	let graphHeight = 0;
	let zoom = 1;
	let pan: { x: number; y: number; left: number; top: number } | null = null;
	$: nodes = tree?.nodes ?? [];
	$: if (!selectedId && tree)
		selectedId = tree.active_path.at(-1) ?? nodes[0]?.message.message_id ?? '';
	$: if (selectedId && tree && !nodes.some((node) => node.message.message_id === selectedId)) {
		selectedId = tree.active_path.at(-1) ?? nodes[0]?.message.message_id ?? '';
		editing = false;
		editError = false;
	}
	$: selected = nodes.find((node) => node.message.message_id === selectedId);
	$: children = groupChildren(nodes);

	function groupChildren(items: ChatTreeNode[]) {
		const children = new Map<string | null, ChatTreeNode[]>();
		for (const node of items) {
			const siblings = children.get(node.parent_message_id) ?? [];
			siblings.push(node);
			children.set(node.parent_message_id, siblings);
		}
		return children;
	}
	onMount(() => {
		const opener = document.activeElement as HTMLElement | null;
		dialog.showModal();
		const handleResize = () => {
			if (window.matchMedia('(max-width: 640px)').matches)
				requestAnimationFrame(() => void fitTree(0.65));
		};
		window.addEventListener('resize', handleResize);
		return () => {
			window.removeEventListener('resize', handleResize);
			dialog.close();
			opener?.focus();
		};
	});
	function select(node: ChatTreeNode) {
		selectedId = node.message.message_id;
		mobilePreview = true;
		editing = false;
		editError = false;
	}
	function measureGraph(element: HTMLElement) {
		let initialized = false;
		let frame = 0;
		const observer = new ResizeObserver(() => {
			if (!element.offsetWidth || !element.offsetHeight) return;
			graphWidth = element.offsetWidth;
			graphHeight = element.offsetHeight;
			if (!initialized) {
				initialized = true;
				frame = requestAnimationFrame(() => {
					if (window.matchMedia('(max-width: 640px)').matches) void fitTree(0.65);
					else void centerSelected();
				});
			}
		});
		observer.observe(element);
		return {
			destroy() {
				observer.disconnect();
				cancelAnimationFrame(frame);
			}
		};
	}
	async function centerSelected() {
		await tick();
		const node = viewport?.querySelector(`[data-node-id="${CSS.escape(selectedId)}"]`);
		if (!node || !viewport.clientWidth) return;
		const bounds = node.getBoundingClientRect();
		const frame = viewport.getBoundingClientRect();
		viewport.scrollTo({
			left:
				viewport.scrollLeft + bounds.left - frame.left + (bounds.width - viewport.clientWidth) / 2,
			top: viewport.scrollTop + bounds.top - frame.top + (bounds.height - viewport.clientHeight) / 2
		});
	}
	async function changeZoom(value: number) {
		zoom = Math.min(1.5, Math.max(0.25, value));
		await centerSelected();
	}
	async function fitTree(minZoom = 0.25) {
		if (!graphWidth || !graphHeight || !viewport?.clientWidth || !viewport.clientHeight) return;
		zoom = Math.max(
			minZoom,
			Math.min(1, viewport.clientWidth / graphWidth, viewport.clientHeight / graphHeight)
		);
		await tick();
		viewport.scrollTo({ left: 0, top: 0 });
	}
	function startPan(event: PointerEvent) {
		if (
			event.pointerType !== 'mouse' ||
			event.button !== 0 ||
			(event.target as HTMLElement).closest('button')
		)
			return;
		pan = {
			x: event.clientX,
			y: event.clientY,
			left: viewport.scrollLeft,
			top: viewport.scrollTop
		};
		viewport.setPointerCapture(event.pointerId);
	}
	function movePan(event: PointerEvent) {
		if (!pan) return;
		viewport.scrollLeft = pan.left + pan.x - event.clientX;
		viewport.scrollTop = pan.top + pan.y - event.clientY;
	}
	function editKey(event: KeyboardEvent) {
		if (event.isComposing || event.keyCode === 229) return;
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			void submitRevision();
		}
	}
	function focusEditor(node: HTMLTextAreaElement) {
		node.focus();
	}
	async function submitRevision() {
		if (disabled || !draft.trim() || !selected?.can_branch) return;
		editError = false;
		editError = !(await onRevise(selected, draft.trim()));
	}
</script>

<dialog
	bind:this={dialog}
	class="branch-dialog"
	aria-label={$t('researchAgent.tree.title')}
	on:cancel|preventDefault={() => {
		if (editing) editing = false;
		else onClose();
	}}
	on:click={(event) => {
		if (event.target === dialog) onClose();
	}}
>
	<div class="tree-surface">
		<header>
			<div class="title">
				<GitBranch size={19} />
				<h2>{$t('researchAgent.tree.title')}</h2>
				<span>{nodes.length}</span>
			</div>
			<div class="actions">
				<IconButton label={$t('researchAgent.tree.refresh')} disabled={loading} onClick={onRefresh}
					><RefreshCw size={16} /></IconButton
				>
				<IconButton label={$t('researchAgent.tree.close')} onClick={onClose}
					><X size={18} /></IconButton
				>
			</div>
		</header>
		{#if error}<div class="tree-error" role="alert">{error}</div>{/if}
		{#if loading && !tree}
			<div class="empty" role="status">{$t('researchAgent.tree.loading')}</div>
		{:else if !nodes.length}
			<div class="empty">{$t('researchAgent.tree.empty')}</div>
		{:else}
			<div class="tree-body" class:mobile-preview={mobilePreview} aria-busy={loading}>
				<div class="tree-map">
					<div class="map-toolbar">
						<div class="zoom-controls">
							<IconButton
								label={$t('researchAgent.tree.zoomOut')}
								disabled={zoom <= 0.25}
								onClick={() => changeZoom(zoom - 0.15)}><Minus size={16} /></IconButton
							>
							<output aria-label={$t('researchAgent.tree.zoom')}>{Math.round(zoom * 100)}%</output>
							<IconButton
								label={$t('researchAgent.tree.zoomIn')}
								disabled={zoom >= 1.5}
								onClick={() => changeZoom(zoom + 0.15)}><Plus size={16} /></IconButton
							>
						</div>
						<div class="actions">
							<IconButton
								label={$t('researchAgent.tree.fit')}
								disabled={!graphWidth}
								onClick={() => fitTree()}><Scan size={16} /></IconButton
							>
							<IconButton label={$t('researchAgent.tree.locate')} onClick={centerSelected}
								><LocateFixed size={16} /></IconButton
							>
						</div>
					</div>
					<div
						class="tree-viewport"
						class:panning={pan !== null}
						bind:this={viewport}
						on:pointerdown={startPan}
						on:pointermove={movePan}
						on:pointerup={() => (pan = null)}
						on:lostpointercapture={() => (pan = null)}
					>
						<div
							class="graph-stage"
							style:width={`${graphWidth * zoom}px`}
							style:height={`${graphHeight * zoom}px`}
						>
							<nav
								class="graph-content"
								aria-label={$t('researchAgent.tree.title')}
								style:transform={`scale(${zoom})`}
								use:measureGraph
							>
								{#snippet renderBranches(parentId: string | null)}
									<ul class="branch-list" class:root={parentId === null}>
										{#each children.get(parentId) ?? [] as node (node.message.message_id)}
											{@const current = tree?.active_path.includes(node.message.message_id)}
											{@const childCount = children.get(node.message.message_id)?.length ?? 0}
											<li class:active-branch={current}>
												<button
													type="button"
													class="tree-node"
													class:selected={selectedId === node.message.message_id}
													class:current
													aria-pressed={selectedId === node.message.message_id}
													data-node-id={node.message.message_id}
													on:click={() => select(node)}
												>
													<span class="node-heading">
														<span data-state={node.status}
															>{$t(`researchAgent.tree.status.${node.status}`)}</span
														>
														{#if current}<span class="current-label"
																><Check size={11} />{$t('researchAgent.tree.current')}</span
															>{/if}
													</span>
													<span class="node-label">{node.message.content}</span>
													<span class="node-meta">
														{#if parentId === null}<span>{$t('researchAgent.tree.root')}</span>{/if}
														{#if childCount > 1}<span class="fork-count"
																><GitBranch size={12} />{$t('researchAgent.tree.branchCount', {
																	count: childCount
																})}</span
															>{/if}
													</span>
												</button>
												{#if childCount}{@render renderBranches(node.message.message_id)}{/if}
											</li>
										{/each}
									</ul>
								{/snippet}
								{@render renderBranches(null)}
							</nav>
						</div>
					</div>
				</div>
				{#if selected}
					<section class="node-preview" aria-label={$t('researchAgent.tree.question')}>
						<div class="preview-toolbar">
							<button
								class="mobile-back"
								type="button"
								on:click={() => {
									mobilePreview = false;
									editing = false;
								}}><ArrowLeft size={16} />{$t('researchAgent.tree.back')}</button
							>
							<span class="preview-status" data-state={selected.status}
								><Clock3 size={13} />{$t(`researchAgent.tree.status.${selected.status}`)}</span
							>
						</div>
						<div class="preview-scroll">
							{#if editError}<p class="tree-error" role="alert">
									{$t('researchAgent.revision.failed')}
								</p>{/if}
							<h3>{$t('researchAgent.tree.question')}</h3>
							{#if editing}<textarea
									aria-label={$t('researchAgent.revision.edit')}
									bind:value={draft}
									maxlength={12000}
									rows={6}
									on:keydown={editKey}
									use:focusEditor
								></textarea>
							{:else}<p class="question">{selected.message.content}</p>{/if}
							{#if selected.message.source_contexts.length}
								<details class="preview-sources">
									<summary
										>{$t(
											selected.message.source_contexts.length === 1
												? 'researchAgent.sourceContext.citedSingle'
												: 'researchAgent.sourceContext.cited',
											{
												count: selected.message.source_contexts.length
											}
										)}</summary
									>
									{#each selected.message.source_contexts as source}<p>
											<a
												href={`${resolve('/collections/[id]/documents/[document_id]', { id: source.collection_id, document_id: source.document_id })}?source_ref=${encodeURIComponent(source.source_ref)}`}
												on:click={onClose}>{source.document_title}</a
											><br />{source.quote}
										</p>{/each}
								</details>
							{/if}
							<h3>{$t('researchAgent.tree.answer')}</h3>
							{#if selected.answer}<MessageContent content={selected.answer} />{:else}<p
									class="muted"
								>
									{$t('researchAgent.tree.noAnswer')}
								</p>{/if}
						</div>
						<footer>
							{#if editing}
								<button type="button" class="secondary" on:click={() => (editing = false)}
									>{$t('researchAgent.revision.cancel')}</button
								>
								<button
									type="button"
									class="primary"
									disabled={disabled || !draft.trim() || !selected.can_branch}
									on:click={submitRevision}
									><GitBranch size={15} />{$t('researchAgent.tree.submit')}</button
								>
							{:else}
								<button
									type="button"
									class="secondary"
									disabled={disabled || !selected.can_branch}
									on:click={() => {
										draft = selected!.message.content;
										editing = true;
									}}><Pencil size={14} />{$t('researchAgent.tree.edit')}</button
								>
								<button
									type="button"
									class="primary"
									{disabled}
									on:click={() => selected && onSelect(selected)}
									>{$t('researchAgent.tree.select')}<ArrowRight size={15} /></button
								>
							{/if}
						</footer>
					</section>
				{/if}
			</div>
		{/if}
	</div>
</dialog>

<style>
	.branch-dialog {
		margin: auto;
		width: min(1280px, calc(100vw - 48px));
		max-width: none;
		max-height: calc(100dvh - 48px);
		padding: 0;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
		color: var(--text-primary);
		box-shadow: var(--shadow-lg);
	}
	.branch-dialog[open] {
		animation: tree-enter 160ms ease-out;
	}
	@keyframes tree-enter {
		from {
			opacity: 0;
			transform: translateY(6px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
	.branch-dialog::backdrop {
		background: rgb(0 0 0 / 38%);
	}
	.tree-surface {
		height: min(800px, calc(100dvh - 64px));
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px;
		border-bottom: 1px solid var(--border-default);
	}
	.title,
	.actions,
	.preview-status,
	.current-label {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.title h2 {
		font-size: 16px;
		font-weight: 600;
		margin: 0;
	}
	.title > span {
		color: var(--text-tertiary);
		font-size: 12px;
	}
	.tree-body {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(300px, 32%);
	}
	.tree-map {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		background: var(--bg-subtle);
		border-right: 1px solid var(--border-default);
	}
	.map-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 8px 16px;
		border-bottom: 1px solid var(--border-default);
		background: var(--surface-card);
	}
	.zoom-controls {
		display: flex;
		align-items: center;
		gap: 4px;
	}
	output {
		width: 40px;
		text-align: center;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		color: var(--text-secondary);
	}
	.tree-viewport {
		flex: 1;
		min-height: 0;
		overflow: auto;
		overscroll-behavior: contain;
		cursor: grab;
	}
	.tree-viewport.panning {
		cursor: grabbing;
		user-select: none;
	}
	.graph-stage {
		position: relative;
		margin: 0 auto;
		overflow: clip;
	}
	.graph-content {
		position: absolute;
		top: 0;
		left: 0;
		width: max-content;
		padding: 40px 24px;
		transform-origin: top left;
	}
	.tree-node {
		position: relative;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		gap: 8px;
		box-sizing: border-box;
		width: 224px;
		height: 132px;
		flex: 0 0 auto;
		padding: 12px;
		text-align: left;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		cursor: pointer;
		transition:
			border-color 140ms,
			background 140ms,
			box-shadow 140ms;
	}
	.branch-list {
		position: relative;
		display: flex;
		list-style: none;
		margin: 0;
		padding: 36px 0 0;
	}
	.branch-list.root {
		padding: 0;
	}
	.branch-list:not(.root)::before {
		content: '';
		position: absolute;
		left: 50%;
		top: 0;
		height: 36px;
		border-left: 2px solid var(--border-strong);
	}
	.branch-list > li {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 18px 12px 0;
	}
	.branch-list > li::before,
	.branch-list > li::after {
		content: '';
		position: absolute;
		top: 0;
		width: 50%;
		height: 18px;
		box-sizing: border-box;
		border-top: 2px solid var(--border-strong);
	}
	.branch-list > li::before {
		right: 50%;
	}
	.branch-list > li::after {
		left: 50%;
		border-left: 2px solid var(--border-strong);
	}
	.branch-list > li:first-child::before,
	.branch-list > li:last-child::after {
		display: none;
	}
	.branch-list > li:last-child::before {
		border-right: 2px solid var(--border-strong);
		border-radius: 0 6px 0 0;
	}
	.branch-list > li:first-child::after {
		border-radius: 6px 0 0 0;
	}
	.branch-list > li:only-child::after {
		display: block;
		border-top: 0;
		border-radius: 0;
	}
	.branch-list.root > li {
		padding-top: 0;
	}
	.branch-list.root > li::before,
	.branch-list.root > li::after {
		display: none;
	}
	.tree-node.selected {
		border-color: var(--brand-primary);
		background: var(--brand-soft);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--brand-primary) 14%, transparent);
	}
	.tree-node:hover {
		border-color: var(--brand-primary);
	}
	.node-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 4px;
		width: 100%;
		font-size: 10px;
		color: var(--text-secondary);
	}
	.node-label {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		overflow: hidden;
		font-size: 13px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}
	.node-meta {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		width: 100%;
		min-height: 14px;
		color: var(--text-secondary);
		font-size: 10px;
	}
	.active-branch > .tree-node:not(.selected) {
		border-color: color-mix(in srgb, var(--brand-primary) 42%, var(--border-default));
	}
	.branch-list > .active-branch::before,
	.branch-list > .active-branch::after,
	.active-branch > .branch-list::before {
		border-color: var(--brand-primary);
	}
	.fork-count {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		white-space: nowrap;
	}
	.current-label {
		gap: 3px;
		color: var(--brand-primary);
	}
	[data-state='running'],
	[data-state='approval_required'] {
		color: var(--brand-primary);
	}
	[data-state='failed'],
	[data-state='interrupted'] {
		color: var(--status-error-text, #b42318);
	}
	.node-preview {
		display: flex;
		flex-direction: column;
		min-height: 0;
		min-width: 0;
	}
	.preview-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 24px 0;
	}
	.preview-status {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.preview-scroll {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding: 8px 24px 24px;
		overflow-wrap: anywhere;
	}
	h3 {
		font-size: 11px;
		font-weight: 600;
		color: var(--text-tertiary);
		margin: 20px 0 8px;
	}
	.question {
		white-space: pre-wrap;
		font-size: 15px;
		line-height: 24px;
		margin: 0;
	}
	.preview-sources {
		margin-top: 16px;
		color: var(--text-secondary);
		font-size: 12px;
	}
	.preview-sources summary {
		cursor: pointer;
	}
	.preview-sources a {
		color: var(--brand-primary);
		text-decoration: underline;
	}
	.preview-sources p {
		padding-left: 12px;
		border-left: 2px solid var(--border-strong);
	}
	footer {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
		padding: 16px 20px;
		border-top: 1px solid var(--border-default);
	}
	footer button,
	.mobile-back {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		min-height: 36px;
		padding: 8px 12px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		font: inherit;
		font-size: 12px;
		cursor: pointer;
	}
	.primary {
		background: var(--brand-primary);
		border-color: var(--brand-primary);
		color: white;
	}
	.secondary,
	.mobile-back {
		background: transparent;
		color: var(--text-secondary);
	}
	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	button:focus-visible,
	textarea:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	textarea {
		box-sizing: border-box;
		width: 100%;
		resize: vertical;
		min-height: 140px;
		max-height: 260px;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		padding: 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 14px;
		line-height: 22px;
	}
	.empty {
		margin: auto;
		color: var(--text-secondary);
		font-size: 14px;
	}
	.muted {
		color: var(--text-secondary);
		font-size: 13px;
	}
	.tree-error {
		padding: 12px 20px;
		color: var(--status-error-text, #b42318);
		font-size: 13px;
	}
	.mobile-back {
		display: none;
	}
	@media (max-width: 640px) {
		.branch-dialog {
			width: calc(100vw - 16px);
			max-height: calc(100dvh - 16px);
		}
		.tree-surface {
			height: calc(100dvh - 32px);
		}
		.tree-body {
			grid-template-columns: minmax(0, 1fr);
		}
		.tree-map {
			border-right: 0;
		}
		.node-preview {
			display: none;
		}
		.mobile-preview .tree-map {
			display: none;
		}
		.mobile-preview .node-preview {
			display: flex;
		}
		.mobile-back {
			display: inline-flex;
			padding: 4px 0;
			border: 0;
		}
		.preview-toolbar {
			padding: 12px 16px 0;
		}
		.preview-scroll {
			padding: 0 16px 16px;
		}
		footer {
			padding: 12px;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.tree-node {
			transition: none;
		}
		.branch-dialog[open] {
			animation: none;
		}
	}
</style>
