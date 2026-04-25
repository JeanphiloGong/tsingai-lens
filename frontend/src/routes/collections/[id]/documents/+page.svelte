<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import {
		buildDocumentTypeStats,
		buildProfileConclusion,
		buildProtocolSuitabilityStats,
		fetchDocumentProfiles,
		formatConfidence,
		getDocumentNextActions,
		getDocumentTypeBadge,
		getSuitabilityBadge,
		type DocumentProfile,
		type DocumentProfileAction,
		type DocumentProfilesResponse,
		type DocumentType,
		type DocumentTypeStat,
		type ProtocolExtractable,
		type ProtocolSuitabilityStat
	} from '../../../_shared/documents';
	import { t } from '../../../_shared/i18n';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview,
		type WorkspaceSurfaceState
	} from '../../../_shared/workspace';

	type FilterOption<T extends string> = {
		value: '' | T;
		labelKey: string;
	};

	const DOC_TYPE_FILTERS: FilterOption<DocumentType>[] = [
		{ value: '', labelKey: 'profiles.filters.all' },
		{ value: 'experimental', labelKey: 'profiles.docTypes.experimental' },
		{ value: 'review', labelKey: 'profiles.docTypes.review' },
		{ value: 'method', labelKey: 'profiles.docTypes.method' },
		{ value: 'computational', labelKey: 'profiles.docTypes.computational' },
		{ value: 'mixed', labelKey: 'profiles.docTypes.mixed' },
		{ value: 'uncertain', labelKey: 'profiles.docTypes.uncertain' }
	];

	const SUITABILITY_FILTERS: FilterOption<ProtocolExtractable>[] = [
		{ value: '', labelKey: 'profiles.filters.all' },
		{ value: 'yes', labelKey: 'profiles.suitability.yes' },
		{ value: 'partial', labelKey: 'profiles.suitability.partial' },
		{ value: 'no', labelKey: 'profiles.suitability.no' },
		{ value: 'uncertain', labelKey: 'profiles.suitability.uncertain' }
	];

	const ACTION_LABEL_KEYS: Record<DocumentProfileAction, string> = {
		upload_more: 'profiles.actions.uploadMore',
		view_evidence: 'profiles.actions.viewEvidence',
		view_document: 'profiles.actions.viewDocument',
		open_comparison: 'profiles.actions.openComparison',
		view_progress: 'profiles.actions.viewProgress',
		refresh: 'profiles.actions.refresh',
		view_error: 'profiles.actions.viewError',
		retry_processing: 'profiles.actions.retryProcessing',
		manual_mark: 'profiles.actions.manualMark'
	};

	$: collectionId = $page.params.id ?? '';

	let response: DocumentProfilesResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let docType: '' | DocumentType = '';
	let suitability: '' | ProtocolExtractable = '';
	let loadedCollectionId = '';
	let notFound = false;

	$: profiles = response?.items ?? [];
	$: totalDocumentCount = Math.max(
		response?.summary.total_documents ?? 0,
		workspace?.document_summary.total_documents ?? 0,
		workspace?.file_count ?? 0,
		profiles.length
	);
	$: filteredProfiles = profiles.filter((item) => {
		if (docType && item.doc_type !== docType) return false;
		if (suitability && item.protocol_extractable !== suitability) return false;
		return true;
	});
	$: documentTypeStats = buildDocumentTypeStats(profiles);
	$: protocolSuitabilityStats = buildProtocolSuitabilityStats(profiles);
	$: profileConclusion = buildProfileConclusion({
		total: profiles.length,
		documentTypeStats,
		protocolSuitabilityStats
	});
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'documents');
	$: hasBlockingError = Boolean(error) && (!notFound || !workspace);
	$: showEmptyState = !loading && !hasBlockingError && totalDocumentCount < 1;
	$: showProfilePending =
		!loading && !hasBlockingError && totalDocumentCount > 0 && profiles.length < 1;
	$: updatedAt = latestUpdatedAt(profiles, workspace);

	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadProfiles();
	}

	async function loadProfiles() {
		loading = true;
		error = '';
		notFound = false;

		const [profilesResult, workspaceResult] = await Promise.allSettled([
			fetchDocumentProfiles(collectionId),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		if (profilesResult.status === 'fulfilled') {
			response = profilesResult.value;
			loading = false;
			return;
		}

		response = null;
		notFound = isHttpStatusError(profilesResult.reason, 404);
		error = errorMessage(profilesResult.reason);
		loading = false;
	}

	function nonEmptyText(value?: string | null) {
		if (typeof value !== 'string') return null;
		const text = value.trim();
		return text ? text : null;
	}

	function shortDocumentId(documentId: string) {
		const trimmed = documentId.trim();
		if (trimmed.length <= 18) return trimmed;
		return `${trimmed.slice(0, 8)}...${trimmed.slice(-8)}`;
	}

	function readableDisplayText(value: string | null | undefined, documentId: string) {
		const text = nonEmptyText(value);
		if (!text || text === documentId) return null;
		return text;
	}

	function displayTitle(profile: DocumentProfile) {
		return (
			readableDisplayText(profile.title, profile.document_id) ??
			readableDisplayText(profile.source_filename, profile.document_id) ??
			shortDocumentId(profile.document_id)
		);
	}

	function actionLabel(action: DocumentProfileAction) {
		return $t(ACTION_LABEL_KEYS[action]);
	}

	function isPrimaryConclusionAction(action: DocumentProfileAction) {
		if (action === 'view_evidence' || action === 'open_comparison') return true;
		return action === 'upload_more' && profileConclusion.actionKeys.length === 1;
	}

	function confidencePercent(value?: number | null) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return 0;
		const percent = value <= 1 ? value * 100 : value;
		return Math.max(0, Math.min(100, Math.round(percent)));
	}

	function formatDate(value?: string | null) {
		if (!value) return '--';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString(undefined, {
			year: 'numeric',
			month: 'numeric',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function latestUpdatedAt(
		profileItems: DocumentProfile[],
		currentWorkspace: WorkspaceOverview | null
	) {
		const profileDates = profileItems
			.map((profile) => profile.updated_at)
			.filter((value): value is string => Boolean(value));
		const newestProfileDate = profileDates
			.map((value) => new Date(value).getTime())
			.filter((value) => Number.isFinite(value))
			.sort((a, b) => b - a)[0];
		if (typeof newestProfileDate === 'number') return new Date(newestProfileDate).toISOString();
		return currentWorkspace?.collection.updated_at ?? currentWorkspace?.artifacts.updated_at ?? '';
	}

	function surfaceStatusTone(state: WorkspaceSurfaceState) {
		if (state === 'ready' || state === 'limited') return 'ready';
		if (state === 'processing' || state === 'ready_to_process') return 'processing';
		if (state === 'failed') return 'failed';
		if (state === 'empty') return 'empty';
		return 'pending';
	}

	function rowStatusKey(profile: DocumentProfile) {
		const profileStatus = profile.processing_status ?? 'unknown';
		if (profileStatus !== 'unknown') return profileStatus;
		if (surfaceState === 'processing' || surfaceState === 'ready_to_process') return 'processing';
		if (surfaceState === 'failed') return 'failed';
		if (surfaceState === 'limited') return 'limited';
		if (surfaceState === 'ready') return 'completed';
		return 'unknown';
	}

	function documentMetaParts(profile: DocumentProfile) {
		const parts = [$t('profiles.file.pdf')];
		if (profile.page_count) {
			parts.push($t('profiles.file.pages', { count: profile.page_count }));
		}
		if (profile.updated_at) {
			parts.push(formatDate(profile.updated_at));
		}
		parts.push($t(`profiles.status.${rowStatusKey(profile)}`));
		return parts;
	}

	function suitabilityReason(profile: DocumentProfile) {
		if (profile.doc_type === 'review' && profile.protocol_extractable === 'no') {
			return $t('profiles.reasons.review');
		}
		if (profile.protocol_extractable === 'yes') return $t('profiles.reasons.extractable');
		if (profile.protocol_extractable === 'partial') return $t('profiles.reasons.partial');
		if (profile.protocol_extractable === 'no') return $t('profiles.reasons.noProtocol');
		return $t('profiles.reasons.insufficient');
	}

	function profileHint(profile: DocumentProfile) {
		if (rowStatusKey(profile) === 'processing') return $t('profiles.hints.processing');
		if (rowStatusKey(profile) === 'failed') return $t('profiles.hints.failed');
		if (profile.protocol_extractable === 'yes') return $t('profiles.hints.extractable');
		if (profile.protocol_extractable === 'partial') return $t('profiles.hints.partial');
		if (profile.doc_type === 'uncertain' || profile.protocol_extractable === 'uncertain') {
			return $t('profiles.hints.insufficient');
		}
		return $t('profiles.hints.noProtocol');
	}

	function protocolReminderKey() {
		const suitableCount = protocolSuitabilityStats.find((item) => item.key === 'yes')?.count ?? 0;
		return suitableCount > 0 ? 'profiles.warning.readyBody' : 'profiles.warning.noSuitableBody';
	}

	function statRowClass(row: DocumentTypeStat | ProtocolSuitabilityStat) {
		return `profile-stat-row profile-stat-row--${row.tone} ${row.dominant ? 'is-dominant' : ''}`;
	}
</script>

<svelte:head>
	<title>{$t('profiles.title')}</title>
</svelte:head>

<section class="profile-page fade-up">
	<header class="profile-header">
		<div class="profile-header__copy">
			<h2>{$t('profiles.title')}</h2>
			<p>{$t('profiles.description')}</p>
			<div class="profile-meta-row">
				<span class="profile-meta">
					<span class="profile-meta__icon profile-meta__icon--document" aria-hidden="true"></span>
					{$t('profiles.meta.documentCount', { count: totalDocumentCount })}
				</span>
				<span class={`status-badge status-badge--${surfaceStatusTone(surfaceState)}`}>
					{$t(`overview.surfaceStates.${surfaceState}`)}
				</span>
				<span class="profile-meta">
					<span class="profile-meta__icon profile-meta__icon--time" aria-hidden="true"></span>
					{$t('profiles.meta.updatedAt', { time: formatDate(updatedAt) })}
				</span>
			</div>
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadProfiles}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('profiles.actions.refresh')}
		</button>
	</header>

	{#if hasBlockingError}
		<div class="status status--error" role="alert">{$t('profiles.error')}: {error}</div>
	{:else if loading}
		<section class="profile-skeleton" aria-busy="true" aria-live="polite">
			<div class="skeleton-card skeleton-card--wide"></div>
			<div class="skeleton-grid">
				<div class="skeleton-card"></div>
				<div class="skeleton-card"></div>
				<div class="skeleton-card"></div>
			</div>
		</section>
	{:else if showEmptyState}
		<article class="profile-empty-card">
			<div class="profile-empty-card__icon" aria-hidden="true">PDF</div>
			<h3>{$t('profiles.emptyState.title')}</h3>
			<p>{$t('profiles.emptyState.body')}</p>
			<a class="btn btn--primary" href={resolve('/collections/[id]', { id: collectionId })}>
				{$t('profiles.actions.uploadDocument')}
			</a>
		</article>
	{:else if showProfilePending}
		<article class="profile-conclusion profile-conclusion--limited">
			<div class="profile-conclusion__icon" aria-hidden="true">!</div>
			<div class="profile-conclusion__body">
				<h3>{$t('profiles.pending.title')}</h3>
				<p>{$t('profiles.pending.body')}</p>
			</div>
			<div class="profile-conclusion__actions">
				<a class="btn btn--ghost" href={resolve('/collections/[id]', { id: collectionId })}>
					{$t('profiles.actions.reanalyze')}
				</a>
				<button class="btn btn--primary" type="button" on:click={loadProfiles}>
					{$t('profiles.actions.refresh')}
				</button>
			</div>
		</article>
	{:else if response}
		<section class="profile-filters" aria-label={$t('profiles.filters.title')}>
			<div class="field">
				<label for="docType">{$t('profiles.filters.type')}</label>
				<select id="docType" class="select" bind:value={docType}>
					{#each DOC_TYPE_FILTERS as option (option.value)}
						<option value={option.value}>{$t(option.labelKey)}</option>
					{/each}
				</select>
			</div>
			<div class="field">
				<label for="suitability">{$t('profiles.filters.suitability')}</label>
				<select id="suitability" class="select" bind:value={suitability}>
					{#each SUITABILITY_FILTERS as option (option.value)}
						<option value={option.value}>{$t(option.labelKey)}</option>
					{/each}
				</select>
			</div>
			<div class="profile-filter-count">
				{$t('profiles.filters.showing', {
					filtered: filteredProfiles.length,
					total: profiles.length
				})}
			</div>
		</section>

		<article class={`profile-conclusion profile-conclusion--${profileConclusion.tone}`}>
			<div class="profile-conclusion__icon" aria-hidden="true">!</div>
			<div class="profile-conclusion__body">
				<h3>{$t('profiles.conclusion.title')}</h3>
				<p>{$t(profileConclusion.messageKey)}</p>
			</div>
			<div class="profile-conclusion__actions">
				{#each profileConclusion.actionKeys as action (action)}
					{#if action === 'refresh'}
						<button
							class={`btn ${isPrimaryConclusionAction(action) ? 'btn--primary' : 'btn--ghost'}`}
							type="button"
							on:click={loadProfiles}
						>
							{actionLabel(action)}
						</button>
					{:else if action === 'view_evidence'}
						<a
							class={`btn ${isPrimaryConclusionAction(action) ? 'btn--primary' : 'btn--ghost'}`}
							href={resolve('/collections/[id]/evidence', { id: collectionId })}
						>
							{actionLabel(action)}
						</a>
					{:else if action === 'open_comparison'}
						<a
							class={`btn ${isPrimaryConclusionAction(action) ? 'btn--primary' : 'btn--ghost'}`}
							href={resolve('/collections/[id]/comparisons', { id: collectionId })}
						>
							{actionLabel(action)}
						</a>
					{:else}
						<a
							class={`btn ${isPrimaryConclusionAction(action) ? 'btn--primary' : 'btn--ghost'}`}
							href={resolve('/collections/[id]', { id: collectionId })}
						>
							{actionLabel(action)}
						</a>
					{/if}
				{/each}
			</div>
		</article>

		<section class="profile-summary-grid">
			<article class="profile-summary-card">
				<h3>
					<span class="summary-icon summary-icon--document" aria-hidden="true"></span>
					{$t('profiles.stats.documentType')}
				</h3>
				<div class="profile-stat-list">
					{#each documentTypeStats as row (row.key)}
						<div class={statRowClass(row)}>
							<span>{$t(row.labelKey)}</span>
							<div class="profile-stat-bar" aria-hidden="true">
								<span style={`width: ${row.percent}%`}></span>
							</div>
							<strong
								>{$t('profiles.stats.countPercent', {
									count: row.count,
									percent: row.percent
								})}</strong
							>
						</div>
					{/each}
				</div>
			</article>

			<article class="profile-summary-card">
				<h3>
					<span class="summary-icon summary-icon--target" aria-hidden="true"></span>
					{$t('profiles.stats.protocolSuitability')}
				</h3>
				<div class="profile-stat-list">
					{#each protocolSuitabilityStats as row (row.key)}
						<div class={statRowClass(row)}>
							<span>{$t(row.labelKey)}</span>
							<div class="profile-stat-bar" aria-hidden="true">
								<span style={`width: ${row.percent}%`}></span>
							</div>
							<strong
								>{$t('profiles.stats.countPercent', {
									count: row.count,
									percent: row.percent
								})}</strong
							>
						</div>
					{/each}
				</div>
			</article>

			<article class="profile-summary-card profile-summary-card--reminder">
				<h3>
					<span class="summary-icon summary-icon--warning" aria-hidden="true"></span>
					{$t('profiles.warning.title')}
				</h3>
				<p>{$t(protocolReminderKey())}</p>
				<a class="profile-guide-link" href={resolve('/docs')}>
					{$t('profiles.actions.viewSuitabilityGuide')}
				</a>
			</article>
		</section>

		<section class="profile-list-section">
			<div class="profile-list-header">
				<h3>{$t('profiles.list.title')}</h3>
				<span>{$t('profiles.list.count', { count: filteredProfiles.length })}</span>
			</div>

			{#if filteredProfiles.length}
				<div class="profile-table-wrapper">
					<table class="profile-table">
						<thead>
							<tr>
								<th>{$t('profiles.table.document')}</th>
								<th>{$t('profiles.table.type')}</th>
								<th>{$t('profiles.table.suitability')}</th>
								<th>{$t('profiles.table.confidence')}</th>
								<th>{$t('profiles.table.hint')}</th>
								<th>{$t('profiles.table.next')}</th>
							</tr>
						</thead>
						<tbody>
							{#each filteredProfiles as item (item.document_id)}
								{@const typeBadge = getDocumentTypeBadge(item.doc_type)}
								{@const suitabilityBadge = getSuitabilityBadge(item.protocol_extractable)}
								<tr>
									<td>
										<div class="document-cell">
											<span class="pdf-icon" aria-hidden="true">PDF</span>
											<div class="document-cell__copy">
												<div class="document-title">{displayTitle(item)}</div>
												<div class="document-meta">{documentMetaParts(item).join(' · ')}</div>
											</div>
										</div>
									</td>
									<td>
										<span class={`profile-badge profile-badge--${typeBadge.tone}`}>
											{$t(typeBadge.labelKey)}
										</span>
									</td>
									<td>
										<div class="suitability-cell">
											<span class={`profile-badge profile-badge--${suitabilityBadge.tone}`}>
												{$t(suitabilityBadge.labelKey)}
											</span>
											<span>{$t('profiles.reasons.label')}: {suitabilityReason(item)}</span>
										</div>
									</td>
									<td>
										<div class="confidence-cell">
											<strong>{formatConfidence(item.confidence)}</strong>
											<span class="confidence-bar" aria-hidden="true">
												<span style={`width: ${confidencePercent(item.confidence)}%`}></span>
											</span>
										</div>
									</td>
									<td>
										<p class="profile-hint">{profileHint(item)}</p>
									</td>
									<td>
										<div class="row-actions">
											{#each getDocumentNextActions(item) as action (action)}
												{#if action === 'refresh'}
													<button
														class="btn btn--ghost btn--small"
														type="button"
														on:click={loadProfiles}
													>
														{actionLabel(action)}
													</button>
												{:else if action === 'view_document' || action === 'manual_mark'}
													<a
														class="btn btn--ghost btn--small"
														href={resolve('/collections/[id]/documents/[document_id]', {
															id: collectionId,
															document_id: item.document_id
														})}
													>
														{actionLabel(action)}
													</a>
												{:else if action === 'view_evidence'}
													<a
														class="btn btn--ghost btn--small profile-action--brand"
														href={resolve('/collections/[id]/evidence', { id: collectionId })}
													>
														{actionLabel(action)}
													</a>
												{:else if action === 'open_comparison'}
													<a
														class="btn btn--ghost btn--small profile-action--brand"
														href={resolve('/collections/[id]/comparisons', { id: collectionId })}
													>
														{actionLabel(action)}
													</a>
												{:else}
													<a
														class="btn btn--ghost btn--small"
														href={resolve('/collections/[id]', { id: collectionId })}
													>
														{actionLabel(action)}
													</a>
												{/if}
											{/each}
											<button
												class="more-button"
												type="button"
												disabled
												aria-label={$t('profiles.actions.more')}
												title={$t('profiles.actions.more')}
											>
												...
											</button>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<div class="profile-document-cards">
					{#each filteredProfiles as item (item.document_id)}
						{@const typeBadge = getDocumentTypeBadge(item.doc_type)}
						{@const suitabilityBadge = getSuitabilityBadge(item.protocol_extractable)}
						<article class="profile-document-card">
							<div class="document-cell">
								<span class="pdf-icon" aria-hidden="true">PDF</span>
								<div class="document-cell__copy">
									<div class="document-title">{displayTitle(item)}</div>
									<div class="document-meta">{documentMetaParts(item).join(' · ')}</div>
								</div>
							</div>
							<div class="mobile-profile-fields">
								<div>
									<span>{$t('profiles.table.type')}</span>
									<strong class={`profile-badge profile-badge--${typeBadge.tone}`}>
										{$t(typeBadge.labelKey)}
									</strong>
								</div>
								<div>
									<span>{$t('profiles.table.suitability')}</span>
									<strong class={`profile-badge profile-badge--${suitabilityBadge.tone}`}>
										{$t(suitabilityBadge.labelKey)}
									</strong>
								</div>
								<div>
									<span>{$t('profiles.table.confidence')}</span>
									<strong>{formatConfidence(item.confidence)}</strong>
								</div>
							</div>
							<p class="profile-hint">{profileHint(item)}</p>
							<div class="row-actions">
								{#each getDocumentNextActions(item) as action (action)}
									{#if action === 'refresh'}
										<button class="btn btn--ghost btn--small" type="button" on:click={loadProfiles}>
											{actionLabel(action)}
										</button>
									{:else if action === 'view_document' || action === 'manual_mark'}
										<a
											class="btn btn--ghost btn--small"
											href={resolve('/collections/[id]/documents/[document_id]', {
												id: collectionId,
												document_id: item.document_id
											})}
										>
											{actionLabel(action)}
										</a>
									{:else if action === 'view_evidence'}
										<a
											class="btn btn--ghost btn--small profile-action--brand"
											href={resolve('/collections/[id]/evidence', { id: collectionId })}
										>
											{actionLabel(action)}
										</a>
									{:else if action === 'open_comparison'}
										<a
											class="btn btn--ghost btn--small profile-action--brand"
											href={resolve('/collections/[id]/comparisons', { id: collectionId })}
										>
											{actionLabel(action)}
										</a>
									{:else}
										<a
											class="btn btn--ghost btn--small"
											href={resolve('/collections/[id]', { id: collectionId })}
										>
											{actionLabel(action)}
										</a>
									{/if}
								{/each}
							</div>
						</article>
					{/each}
				</div>
			{:else}
				<div class="profile-empty-filter" role="status">{$t('profiles.list.emptyFiltered')}</div>
			{/if}
		</section>

		<p class="profile-footer-note">{$t('footer.pdfNote')}</p>
	{/if}
</section>

<style>
	.profile-page {
		display: grid;
		gap: 24px;
	}

	.profile-header,
	.profile-filters,
	.profile-summary-card,
	.profile-list-section,
	.profile-empty-card {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.profile-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
		padding: 24px;
	}

	.profile-header__copy {
		min-width: 0;
		display: grid;
		gap: 10px;
	}

	.profile-header h2 {
		margin: 0;
		color: var(--text-primary);
		font-size: 30px;
		font-weight: 700;
		line-height: 38px;
		letter-spacing: 0;
	}

	.profile-header p {
		max-width: 720px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 22px;
	}

	.profile-meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.profile-meta {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.profile-meta__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		color: var(--text-tertiary);
	}

	.profile-meta__icon--document {
		border: 1.5px solid currentColor;
		border-radius: 3px;
	}

	.profile-meta__icon--document::after {
		content: '';
		position: absolute;
		left: 3px;
		right: 3px;
		top: 5px;
		height: 1.5px;
		background: currentColor;
		box-shadow: 0 4px 0 currentColor;
	}

	.profile-meta__icon--time {
		border: 1.5px solid currentColor;
		border-radius: 999px;
	}

	.profile-meta__icon--time::before,
	.profile-meta__icon--time::after {
		content: '';
		position: absolute;
		left: 6px;
		top: 3px;
		width: 1.5px;
		height: 4px;
		border-radius: 999px;
		background: currentColor;
	}

	.profile-meta__icon--time::after {
		top: 6px;
		width: 4px;
		height: 1.5px;
	}

	.refresh-icon {
		position: relative;
		width: 14px;
		height: 14px;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 999px;
	}

	.refresh-icon::after {
		content: '';
		position: absolute;
		right: -3px;
		top: 0;
		width: 6px;
		height: 6px;
		border-top: 2px solid currentColor;
		border-right: 2px solid currentColor;
		transform: rotate(25deg);
	}

	.profile-filters {
		display: grid;
		grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) auto;
		align-items: end;
		gap: 16px;
		padding: 18px 20px;
	}

	.profile-filter-count {
		min-height: 40px;
		display: inline-flex;
		align-items: center;
		justify-content: flex-end;
		white-space: nowrap;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
	}

	.profile-conclusion {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 16px;
		padding: 22px 24px;
		border: 1px solid var(--brand-border);
		border-radius: var(--radius-lg);
		background: var(--brand-soft);
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
	}

	.profile-conclusion--warning {
		border-color: var(--warning-border);
		background: #fffbeb;
	}

	.profile-conclusion--ready {
		border-color: var(--brand-border);
		background: var(--brand-soft);
	}

	.profile-conclusion--limited {
		border-color: var(--warning-border);
		background: #fffbeb;
	}

	.profile-conclusion__icon {
		width: 34px;
		height: 34px;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: var(--brand-border);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.profile-conclusion--warning .profile-conclusion__icon,
	.profile-conclusion--limited .profile-conclusion__icon {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.profile-conclusion__body {
		display: grid;
		gap: 6px;
	}

	.profile-conclusion h3,
	.profile-summary-card h3,
	.profile-list-header h3,
	.profile-empty-card h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
		letter-spacing: 0;
	}

	.profile-conclusion p,
	.profile-summary-card p,
	.profile-empty-card p {
		margin: 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.profile-conclusion__actions {
		display: flex;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 10px;
	}

	.profile-summary-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 16px;
	}

	.profile-summary-card {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 18px;
		padding: 20px;
	}

	.profile-summary-card h3 {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}

	.summary-icon {
		position: relative;
		width: 20px;
		height: 20px;
		flex: 0 0 auto;
		border-radius: 7px;
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.summary-icon--document::before {
		content: '';
		position: absolute;
		inset: 4px 5px;
		border: 1.5px solid currentColor;
		border-radius: 3px;
	}

	.summary-icon--target {
		border-radius: 999px;
	}

	.summary-icon--target::before,
	.summary-icon--target::after {
		content: '';
		position: absolute;
		border-radius: 999px;
		border: 1.5px solid currentColor;
	}

	.summary-icon--target::before {
		inset: 3px;
	}

	.summary-icon--target::after {
		inset: 7px;
		background: currentColor;
	}

	.summary-icon--warning {
		background: var(--warning-bg);
		color: #f97316;
	}

	.summary-icon--warning::before {
		content: '';
		position: absolute;
		left: 9px;
		top: 4px;
		width: 2px;
		height: 8px;
		border-radius: 999px;
		background: currentColor;
	}

	.summary-icon--warning::after {
		content: '';
		position: absolute;
		left: 9px;
		bottom: 4px;
		width: 2px;
		height: 2px;
		border-radius: 999px;
		background: currentColor;
	}

	.profile-stat-list {
		display: grid;
		gap: 10px;
	}

	.profile-stat-row {
		display: grid;
		grid-template-columns: minmax(70px, 0.45fr) minmax(110px, 1fr) minmax(70px, auto);
		align-items: center;
		gap: 10px;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 20px;
	}

	.profile-stat-row strong {
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 600;
		text-align: right;
	}

	.profile-stat-row.is-dominant > span:first-child,
	.profile-stat-row.is-dominant strong {
		color: var(--text-primary);
		font-weight: 700;
	}

	.profile-stat-bar {
		height: 8px;
		overflow: hidden;
		border-radius: 999px;
		background: #e8edf4;
	}

	.profile-stat-bar span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--brand-primary);
	}

	.profile-stat-row--experimental .profile-stat-bar span,
	.profile-stat-row--ready .profile-stat-bar span {
		background: #16a34a;
	}

	.profile-stat-row--method .profile-stat-bar span {
		background: #7c3aed;
	}

	.profile-stat-row--computational .profile-stat-bar span {
		background: #475569;
	}

	.profile-stat-row--mixed .profile-stat-bar span {
		background: #0f766e;
	}

	.profile-stat-row--uncertain .profile-stat-bar span,
	.profile-stat-row--neutral .profile-stat-bar span {
		background: #94a3b8;
	}

	.profile-stat-row--partial .profile-stat-bar span {
		background: #f59e0b;
	}

	.profile-stat-row--warning .profile-stat-bar span {
		background: #f97316;
	}

	.profile-summary-card--reminder p {
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 24px;
	}

	.profile-guide-link {
		margin-top: auto;
		min-height: 44px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 12px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 14px;
		font-weight: 700;
		line-height: 22px;
	}

	.profile-list-section {
		overflow: hidden;
	}

	.profile-list-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 18px 20px 12px;
	}

	.profile-list-header span {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.profile-table-wrapper {
		overflow-x: auto;
	}

	.profile-table {
		width: 100%;
		border-collapse: collapse;
		min-width: 1080px;
		font-size: 14px;
	}

	.profile-table th {
		padding: 12px 20px;
		border-top: 1px solid var(--border-default);
		border-bottom: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		text-align: left;
		background: #fbfdff;
	}

	.profile-table td {
		min-height: 72px;
		padding: 16px 20px;
		border-bottom: 1px solid var(--border-default);
		color: var(--text-primary);
		vertical-align: middle;
	}

	.document-cell {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.pdf-icon {
		width: 34px;
		height: 40px;
		display: inline-grid;
		place-items: end center;
		flex: 0 0 auto;
		padding-bottom: 5px;
		border-radius: 7px;
		background: #fee2e2;
		color: #dc2626;
		font-size: 10px;
		font-weight: 800;
		line-height: 12px;
	}

	.document-cell__copy {
		min-width: 0;
		display: grid;
		gap: 4px;
	}

	.document-title {
		color: var(--text-primary);
		font-size: 14px;
		font-weight: 700;
		line-height: 20px;
		word-break: break-word;
	}

	.document-meta {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.profile-badge {
		display: inline-flex;
		align-items: center;
		min-height: 28px;
		padding: 4px 10px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		white-space: nowrap;
	}

	.profile-badge--review {
		color: #1d4ed8;
		background: var(--brand-soft);
	}

	.profile-badge--experimental,
	.profile-badge--ready {
		color: var(--success-text);
		background: var(--success-bg);
	}

	.profile-badge--method {
		color: #6d28d9;
		background: #f3e8ff;
	}

	.profile-badge--computational {
		color: #475569;
		background: #e2e8f0;
	}

	.profile-badge--mixed,
	.profile-badge--partial {
		color: var(--warning-text);
		background: var(--warning-bg);
	}

	.profile-badge--uncertain,
	.profile-badge--neutral {
		color: var(--neutral-text, var(--text-secondary));
		background: var(--neutral-bg, #f1f5f9);
	}

	.profile-badge--warning {
		color: #c2410c;
		background: #ffedd5;
	}

	.suitability-cell {
		display: grid;
		gap: 6px;
	}

	.suitability-cell span:last-child {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.confidence-cell {
		display: grid;
		gap: 8px;
		min-width: 96px;
	}

	.confidence-cell strong {
		font-size: 14px;
		line-height: 20px;
	}

	.confidence-bar {
		width: 100%;
		height: 8px;
		overflow: hidden;
		border-radius: 999px;
		background: #e8edf4;
	}

	.confidence-bar span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--brand-primary);
	}

	.profile-hint {
		max-width: 260px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 22px;
	}

	.row-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}

	.profile-action--brand {
		border-color: var(--brand-border);
		color: var(--brand-primary);
	}

	.more-button {
		width: 32px;
		height: 32px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--text-tertiary);
		font-weight: 800;
	}

	.profile-document-cards {
		display: none;
	}

	.mobile-profile-fields {
		display: grid;
		gap: 10px;
	}

	.mobile-profile-fields div {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.mobile-profile-fields strong {
		color: var(--text-primary);
	}

	.profile-empty-card {
		display: grid;
		justify-items: center;
		gap: 12px;
		padding: 34px 24px;
		text-align: center;
	}

	.profile-empty-card p {
		max-width: 560px;
		color: var(--text-secondary);
	}

	.profile-empty-card__icon {
		width: 52px;
		height: 60px;
		display: grid;
		place-items: end center;
		padding-bottom: 8px;
		border-radius: 10px;
		background: #fee2e2;
		color: #dc2626;
		font-size: 12px;
		font-weight: 800;
	}

	.profile-empty-filter {
		padding: 24px;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		text-align: center;
	}

	.profile-skeleton {
		display: grid;
		gap: 16px;
	}

	.skeleton-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 16px;
	}

	.skeleton-card {
		min-height: 180px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background:
			linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.68), transparent), #eef3f8;
		background-size:
			220px 100%,
			100% 100%;
		animation: profile-skeleton 1.4s ease-in-out infinite;
	}

	.skeleton-card--wide {
		min-height: 92px;
	}

	.profile-footer-note {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
		text-align: center;
	}

	:root[data-theme='dark'] .profile-header,
	:root[data-theme='dark'] .profile-filters,
	:root[data-theme='dark'] .profile-summary-card,
	:root[data-theme='dark'] .profile-list-section,
	:root[data-theme='dark'] .profile-empty-card,
	:root[data-theme='dark'] .profile-conclusion {
		background: rgba(16, 26, 44, 0.88);
	}

	:root[data-theme='dark'] .profile-conclusion--warning,
	:root[data-theme='dark'] .profile-conclusion--limited {
		background: rgba(146, 64, 14, 0.26);
	}

	:root[data-theme='dark'] .profile-table th {
		background: rgba(120, 140, 180, 0.12);
	}

	:root[data-theme='dark'] .profile-stat-bar,
	:root[data-theme='dark'] .confidence-bar {
		background: rgba(120, 140, 180, 0.18);
	}

	@keyframes profile-skeleton {
		from {
			background-position:
				-220px 0,
				0 0;
		}
		to {
			background-position:
				calc(100% + 220px) 0,
				0 0;
		}
	}

	@media (max-width: 1024px) {
		.profile-summary-grid,
		.skeleton-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.profile-summary-card--reminder {
			grid-column: 1 / -1;
		}
	}

	@media (max-width: 820px) {
		.profile-header,
		.profile-conclusion {
			grid-template-columns: 1fr;
		}

		.profile-header {
			display: grid;
		}

		.profile-conclusion__actions {
			justify-content: flex-start;
		}

		.profile-filters {
			grid-template-columns: 1fr;
		}

		.profile-filter-count {
			justify-content: flex-start;
		}
	}

	@media (max-width: 720px) {
		.profile-header,
		.profile-summary-card,
		.profile-conclusion,
		.profile-empty-card {
			padding: 18px;
		}

		.profile-header h2 {
			font-size: 28px;
			line-height: 36px;
		}

		.profile-summary-grid,
		.skeleton-grid {
			grid-template-columns: 1fr;
		}

		.profile-table-wrapper {
			display: none;
		}

		.profile-document-cards {
			display: grid;
			gap: 12px;
			padding: 0 14px 14px;
		}

		.profile-document-card {
			display: grid;
			gap: 14px;
			padding: 16px;
			border: 1px solid var(--border-default);
			border-radius: 14px;
			background: var(--surface-card);
		}

		.profile-hint {
			max-width: none;
		}

		.profile-conclusion__actions .btn,
		.profile-header > .btn,
		.profile-empty-card .btn {
			width: 100%;
		}
	}
</style>
