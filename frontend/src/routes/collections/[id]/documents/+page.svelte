<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		fetchDocumentProfiles,
		type DocumentProfile,
		type DocumentProfilesResponse,
		type DocumentType
	} from '../../../_shared/documents';
	import { t } from '../../../_shared/i18n';
	import { onDestroy } from 'svelte';
	import { Search } from '@lucide/svelte';
	let profiles: DocumentProfilesResponse | null = null;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';
	let searchInput = '';
	let appliedQuery = '';
	let documentTypeInput: DocumentType | '' = '';
	let appliedDocumentType: DocumentType | '' = '';
	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	let offset = 0;
	let requestSequence = 0;
	const PAGE_SIZE = 25;

	$: collectionId = $page.params.id ?? '';
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		clearTimeout(searchTimer);
		searchInput = '';
		documentTypeInput = '';
		void loadProfiles(0, '', '');
	}

	$: filtersActive = Boolean(searchInput.trim() || documentTypeInput);

	async function loadProfiles(
		nextOffset = offset,
		nextQuery = searchInput.trim(),
		nextDocumentType = documentTypeInput
	) {
		clearTimeout(searchTimer);
		const requestId = ++requestSequence;
		offset = nextOffset;
		loading = true;
		error = '';
		try {
			const result = await fetchDocumentProfiles(collectionId, {
				offset: nextOffset,
				limit: PAGE_SIZE,
				query: nextQuery,
				docType: nextDocumentType || undefined
			});
			if (requestId !== requestSequence) return;
			profiles = result;
			appliedQuery = nextQuery;
			appliedDocumentType = nextDocumentType;
		} catch (err) {
			if (requestId !== requestSequence) return;
			profiles = null;
			error = errorMessage(err);
		} finally {
			if (requestId === requestSequence) loading = false;
		}
	}

	onDestroy(() => {
		clearTimeout(searchTimer);
		requestSequence += 1;
	});
	function searchChanged() {
		clearTimeout(searchTimer);
		requestSequence += 1;
		loading = true;
		error = '';
		searchTimer = setTimeout(() => void loadProfiles(0), 250);
	}
	function previousPage() {
		void loadProfiles(Math.max(0, offset - PAGE_SIZE), appliedQuery, appliedDocumentType);
	}

	function nextPage() {
		if (!profiles || offset + profiles.count >= profiles.total) return;
		void loadProfiles(offset + PAGE_SIZE, appliedQuery, appliedDocumentType);
	}

	function displayTitle(profile: DocumentProfile, index: number) {
		return profile.title?.trim() || $t('research.documents.untitledPaper', { number: index + 1 });
	}

	function documentTypeLabel(profile: DocumentProfile) {
		const suffix = profile.doc_type.charAt(0).toUpperCase() + profile.doc_type.slice(1);
		const key = `overview.docType${suffix}`;
		const translated = $t(key);
		return translated === key ? profile.doc_type : translated;
	}

	function pageRange() {
		if (!profiles?.count) return '';
		return $t('research.documents.pageRange', {
			start: offset + 1,
			end: offset + profiles.count,
			total: profiles.total
		});
	}
</script>

<svelte:head><title>{$t('collection.tabs.papers')}</title></svelte:head>

<section class="papers-page fade-up">
	<header class="papers-header">
		<div>
			<h2>{$t('collection.tabs.papers')}</h2>
		</div>
		{#if profiles}
			<span
				>{$t('research.documents.documentCount', { count: profiles.summary.total_documents })}</span
			>
		{/if}
	</header>

	<form class="paper-filters" role="search" on:submit|preventDefault={() => loadProfiles(0)}>
		<label class="filter-field" for="paper-search">
			<Search size={18} aria-hidden="true" />
			<input
				id="paper-search"
				type="search"
				aria-label={$t('research.documents.searchLabel')}
				on:input={searchChanged}
				bind:value={searchInput}
				placeholder={$t('research.documents.searchPlaceholder')}
			/>
		</label>
		<label class="filter-field" for="paper-type-filter">
			<select
				id="paper-type-filter"
				aria-label={$t('research.documents.paperType')}
				bind:value={documentTypeInput}
				on:change={(event) => {
					documentTypeInput = event.currentTarget.value as DocumentType | '';
					void loadProfiles(0);
				}}
			>
				<option value="">{$t('research.documents.allPaperTypes')}</option>
				<option value="experimental">{$t('overview.docTypeExperimental')}</option>
				<option value="review">{$t('overview.docTypeReview')}</option>
				<option value="mixed">{$t('overview.docTypeMixed')}</option>
				<option value="uncertain">{$t('overview.docTypeUncertain')}</option>
			</select>
		</label>
	</form>

	{#if loading}
		<p class="page-state" aria-busy="true">{$t('research.documents.profileLoading')}</p>
	{:else if error}
		<section class="page-state page-state--error" role="alert">
			<h3>{$t('research.documents.profileErrorTitle')}</h3>
			<p>{error}</p>
			<button class="btn btn--ghost btn--small" type="button" on:click={() => loadProfiles()}>
				{$t('research.comparison.retry')}
			</button>
		</section>
	{:else if !profiles?.items.length}
		<section class="page-state">
			{#if filtersActive}
				<h3>{$t('research.documents.searchEmptyTitle')}</h3>
				<p>{$t('research.documents.filterEmptyBody')}</p>
			{:else}
				<h3>{$t('research.documents.profileEmptyTitle')}</h3>
				<p>{$t('research.documents.profileEmptyBody')}</p>
			{/if}
		</section>
	{:else}
		<div class="paper-results-status" aria-live="polite">
			<span>
				{filtersActive
					? $t('research.documents.searchCount', { count: profiles.total })
					: pageRange()}
			</span>
		</div>
		<div class="paper-list">
			<div class="paper-list-head">
				<span>{$t('research.documents.columnTitle')}</span>
				<span>{$t('research.documents.columnStatus')}</span>
				<span>{$t('research.documents.columnPages')}</span>
			</div>
			{#each profiles.items as profile, index (profile.document_id)}
				<a
					class="paper-row"
					data-paper-row
					href={resolve('/collections/[id]/documents/[document_id]', {
						id: collectionId,
						document_id: profile.document_id
					})}
				>
					<div class="paper-row__identity">
						<h3>{displayTitle(profile, offset + index)}</h3>
						<span class="paper-type">{documentTypeLabel(profile)}</span>
					</div>

					<div class="paper-row__status">
						<span
							>{$t(
								profile.profile_status === 'completed'
									? 'research.documents.parsingComplete'
									: 'research.documents.parsingFailed'
							)}</span
						>
					</div>
					<div class="paper-row__pages">
						<span
							>{profile.page_count
								? $t('research.documents.pageCount', { count: profile.page_count })
								: '-'}</span
						>
					</div>
				</a>
			{/each}
		</div>
		{#if profiles.total > PAGE_SIZE}
			<nav class="paper-pagination" aria-label={$t('research.documents.paginationLabel')}>
				<button
					class="btn btn--ghost btn--small"
					type="button"
					disabled={offset === 0 || loading}
					on:click={previousPage}
				>
					{$t('research.documents.previousPage')}
				</button>
				<span>{pageRange()}</span>
				<button
					class="btn btn--ghost btn--small"
					type="button"
					disabled={offset + profiles.count >= profiles.total || loading}
					on:click={nextPage}
				>
					{$t('research.documents.nextPage')}
				</button>
			</nav>
		{/if}
	{/if}
</section>

<style>
	.papers-page {
		width: min(1296px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 20px;
		container-type: inline-size;
	}
	.papers-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
	}
	.papers-header h2 {
		margin: 0;
		font-size: 26px;
		line-height: 36px;
	}
	.papers-header > span {
		color: var(--text-secondary);
		font-size: 13px;
	}
	.paper-filters {
		display: flex;
		justify-content: flex-end;
		gap: 12px;
	}
	.filter-field {
		display: flex;
		align-items: center;
		min-width: 0;
	}
	.filter-field:first-child {
		width: min(352px, 100%);
		gap: 10px;
		padding: 0 12px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-secondary);
	}
	.filter-field:first-child:focus-within {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	.filter-field input {
		width: 100%;
		min-width: 0;
		height: 38px;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--text-primary);
		font: inherit;
		font-size: 13px;
	}
	.filter-field select {
		min-height: 38px;
		max-width: 100%;
		padding: 7px 10px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
	}
	.page-state {
		display: grid;
		justify-items: start;
		gap: 10px;
		padding: 24px 0;
		color: var(--text-secondary);
	}
	.page-state h3,
	.page-state p {
		margin: 0;
	}
	.page-state--error {
		color: var(--danger-text);
	}
	.paper-results-status {
		color: var(--text-secondary);
		font-size: 13px;
	}
	.paper-list {
		display: grid;
		border-top: 1px solid var(--border-default);
	}
	.paper-list-head {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(160px, auto) minmax(90px, 120px);
		align-items: center;
		gap: 24px;
		min-height: 42px;
		padding: 0 16px;
		border-bottom: 1px solid var(--border-default);
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 600;
	}
	.paper-list-head span:last-child {
		text-align: right;
	}
	.paper-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(160px, auto) minmax(90px, 120px);
		align-items: center;
		gap: 24px;
		min-height: 92px;
		padding: 16px;
		border-bottom: 1px solid var(--border-default);
		background: var(--surface-card);
		text-decoration: none;
		color: var(--text-primary);
	}
	.paper-row:hover {
		background: var(--surface-hover, var(--surface-card));
	}
	.paper-row:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: -2px;
	}
	.paper-row__identity {
		min-width: 0;
		display: grid;
		gap: 6px;
	}
	.paper-row h3 {
		margin: 0;
		overflow-wrap: anywhere;
		font-size: 16px;
		line-height: 24px;
		color: var(--brand-primary);
	}
	.paper-row:hover h3 {
		text-decoration: underline;
	}
	.paper-type {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.paper-row__status,
	.paper-row__pages {
		color: var(--text-secondary);
		font-size: 13px;
	}
	.paper-row__pages {
		text-align: right;
	}
	.paper-pagination {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		color: var(--text-secondary);
		font-size: 13px;
	}
	@container (max-width: 720px) {
		.paper-filters {
			flex-wrap: wrap;
		}
		.filter-field:first-child {
			width: 100%;
		}
		.paper-list-head {
			display: none;
		}
		.paper-row {
			grid-template-columns: minmax(0, 1fr);
			gap: 12px;
		}
		.paper-row__pages {
			text-align: left;
		}
		.paper-pagination {
			flex-wrap: wrap;
		}
	}
</style>
