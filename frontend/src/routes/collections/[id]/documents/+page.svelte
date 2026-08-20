<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		fetchDocumentProfiles,
		type DocumentProfile,
		type DocumentProfilesResponse
	} from '../../../_shared/documents';
	import { t } from '../../../_shared/i18n';

	let profiles: DocumentProfilesResponse | null = null;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadProfiles();
	}

	async function loadProfiles() {
		loading = true;
		error = '';
		try {
			profiles = await fetchDocumentProfiles(collectionId);
		} catch (err) {
			profiles = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function paperHref(profile: DocumentProfile) {
		return resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: profile.document_id
		});
	}

	function shortId(profile: DocumentProfile) {
		return profile.document_id.length > 12
			? profile.document_id.slice(0, 12)
			: profile.document_id;
	}

	function displayTitle(profile: DocumentProfile, index: number) {
		return (
			profile.title?.trim() ||
			profile.source_filename?.trim() ||
			$t('research.documents.untitledPaper', { number: index + 1 })
		);
	}

	function documentTypeLabel(profile: DocumentProfile) {
		const suffix = profile.doc_type.charAt(0).toUpperCase() + profile.doc_type.slice(1);
		const key = `overview.docType${suffix}`;
		const translated = $t(key);
		return translated === key ? profile.doc_type : translated;
	}
</script>

<svelte:head><title>{$t('collection.tabs.papers')}</title></svelte:head>

<section class="papers-page fade-up">
	<header class="papers-header">
		<div>
			<h2>{$t('collection.tabs.papers')}</h2>
			<p>{$t('research.documents.profileLead')}</p>
		</div>
		{#if profiles}
			<span>{$t('research.documents.documentCount', { count: profiles.items.length })}</span>
		{/if}
	</header>

	{#if loading}
		<p class="page-state" aria-busy="true">{$t('research.documents.profileLoading')}</p>
	{:else if error}
		<section class="page-state page-state--error" role="alert">
			<h3>{$t('research.documents.profileErrorTitle')}</h3>
			<p>{error}</p>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadProfiles}>
				{$t('research.comparison.retry')}
			</button>
		</section>
	{:else if !profiles?.items.length}
		<section class="page-state">
			<h3>{$t('research.documents.profileEmptyTitle')}</h3>
			<p>{$t('research.documents.profileEmptyBody')}</p>
		</section>
	{:else}
		<div class="paper-list">
			{#each profiles.items as profile, index (profile.document_id)}
				<article class="paper-row">
					<div class="paper-row__identity">
						<span class="paper-type">{documentTypeLabel(profile)}</span>
						<h3>{displayTitle(profile, index)}</h3>
						{#if profile.source_filename && profile.source_filename !== profile.title}
							<p>{profile.source_filename}</p>
						{/if}
						<small>{$t('research.documents.shortId')}: {shortId(profile)}</small>
					</div>

					<div class="paper-row__metadata">
						{#if profile.page_count}
							<span>{$t('research.documents.pageCount', { count: profile.page_count })}</span>
						{/if}
						{#if profile.confidence !== null}
							<span>{$t('research.documents.profileConfidence', { value: Math.round(profile.confidence * 100) })}</span>
						{/if}
					</div>

					<div class="paper-row__action">
						<a class="btn btn--ghost btn--small" href={paperHref(profile)}>
							{$t('research.documents.openPaper')}
						</a>
					</div>

					{#if profile.parsing_warnings.length}
						<ul class="paper-warnings">
							{#each profile.parsing_warnings as warning (warning)}
								<li>{warning}</li>
							{/each}
						</ul>
					{/if}
				</article>
			{/each}
		</div>
	{/if}
</section>

<style>
	.papers-page {
		width: min(1120px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}

	.papers-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 24px;
		padding-bottom: 18px;
		border-bottom: 1px solid var(--border-default);
	}

	.papers-header h2,
	.papers-header p,
	.paper-row h3,
	.paper-row p,
	.page-state h3,
	.page-state p {
		margin: 0;
	}

	.papers-header h2 {
		font-size: 28px;
		line-height: 36px;
	}

	.papers-header p {
		max-width: 680px;
		margin-top: 6px;
		color: var(--text-secondary);
		line-height: 22px;
	}

	.papers-header > span {
		color: var(--text-secondary);
		font-size: 13px;
	}

	.page-state {
		display: grid;
		justify-items: start;
		gap: 10px;
		padding: 24px 0;
		color: var(--text-secondary);
	}

	.page-state--error {
		color: var(--danger-text);
	}

	.paper-list {
		display: grid;
		gap: 8px;
	}

	.paper-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(160px, auto) auto;
		align-items: center;
		gap: 18px;
		padding: 16px 18px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
	}

	.paper-row__identity {
		min-width: 0;
		display: grid;
		gap: 4px;
	}

	.paper-type {
		width: fit-content;
		padding: 2px 7px;
		border-radius: 999px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 700;
	}

	.paper-row h3 {
		overflow-wrap: anywhere;
		font-size: 16px;
		line-height: 23px;
	}

	.paper-row p,
	.paper-row small,
	.paper-row__metadata {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.paper-row__metadata {
		display: grid;
		gap: 4px;
	}

	.paper-warnings {
		grid-column: 1 / -1;
		margin: 0;
		padding: 10px 12px 0 28px;
		border-top: 1px solid var(--border-default);
		color: var(--warning-text);
		font-size: 12px;
		line-height: 19px;
	}

	@media (max-width: 720px) {
		.papers-header {
			align-items: flex-start;
			flex-direction: column;
		}

		.paper-row {
			grid-template-columns: 1fr;
		}

		.paper-row__action {
			justify-self: start;
		}
	}
</style>
