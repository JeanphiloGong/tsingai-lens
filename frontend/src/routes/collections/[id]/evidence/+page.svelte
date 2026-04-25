<script lang="ts">
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import {
		fetchEvidenceCards,
		type EvidenceCard,
		type EvidenceCardsResponse
	} from '../../../_shared/evidence';
	import { t } from '../../../_shared/i18n';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview
	} from '../../../_shared/workspace';

	$: collectionId = $page.params.id ?? '';

	let response: EvidenceCardsResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let loadedCollectionId = '';
	let notFound = false;
	let claimType = '';
	let traceability = '';
	let sourceType = '';

	$: items = (response?.items ?? []).filter((item) => {
		if (claimType && item.claim_type !== claimType) return false;
		if (traceability && item.traceability_status !== traceability) return false;
		if (sourceType && item.evidence_source_type !== sourceType) return false;
		return true;
	});
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'evidence');
	$: showFallbackState =
		Boolean(workspace) &&
		!loading &&
		!items.length &&
		(surfaceState !== 'ready' || notFound);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadEvidence();
	}

	async function loadEvidence() {
		loading = true;
		error = '';
		notFound = false;

		const [evidenceResult, workspaceResult] = await Promise.allSettled([
			fetchEvidenceCards(collectionId),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		if (evidenceResult.status === 'fulfilled') {
			response = evidenceResult.value;
			loading = false;
			return;
		}

		response = null;
		notFound = isHttpStatusError(evidenceResult.reason, 404);
		error = errorMessage(evidenceResult.reason);
		loading = false;
	}

	function uniqueSorted(values: string[]) {
		return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort();
	}

	function formatConfidence(value?: number | null) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
		return value.toFixed(2);
	}

	function stateCardTitle() {
		return $t(`overview.surfaceStateCards.${surfaceState}.title`);
	}

	function stateCardBody() {
		return $t(`overview.surfaceStateCards.${surfaceState}.body`);
	}

	function documentHref(card: EvidenceCard) {
		return `/collections/${collectionId}/documents/${encodeURIComponent(card.document_id)}?evidence_id=${encodeURIComponent(card.evidence_id)}`;
	}

	$: claimTypes = uniqueSorted([claimType, ...items.map((item) => item.claim_type)]);
	$: sourceTypes = uniqueSorted([sourceType, ...items.map((item) => item.evidence_source_type)]);
</script>

<svelte:head>
	<title>{$t('evidence.title')}</title>
</svelte:head>

<section class="card fade-up">
	<div class="card-header-inline">
		<div>
			<h2>{$t('evidence.title')}</h2>
			<p class="lead">{$t('evidence.lead')}</p>
		</div>
		<button class="btn btn--ghost btn--small" type="button" on:click={loadEvidence}>
			{$t('overview.refresh')}
		</button>
	</div>

	<div class="form-grid">
		<div class="field">
			<label for="claimType">{$t('evidence.filterClaimType')}</label>
			<select id="claimType" class="select" bind:value={claimType}>
				<option value="">{$t('evidence.allOption')}</option>
				{#each claimTypes as item}
					<option value={item}>{item}</option>
				{/each}
			</select>
		</div>
		<div class="field">
			<label for="traceability">{$t('evidence.filterTraceability')}</label>
			<select id="traceability" class="select" bind:value={traceability}>
				<option value="">{$t('evidence.allOption')}</option>
				<option value="direct">{$t('evidence.traceabilityDirect')}</option>
				<option value="partial">{$t('evidence.traceabilityPartial')}</option>
				<option value="missing">{$t('evidence.traceabilityMissing')}</option>
			</select>
		</div>
		<div class="field">
			<label for="sourceType">{$t('evidence.filterSourceType')}</label>
			<select id="sourceType" class="select" bind:value={sourceType}>
				<option value="">{$t('evidence.allOption')}</option>
				{#each sourceTypes as item}
					<option value={item}>{item}</option>
				{/each}
			</select>
		</div>
	</div>

	{#if workspace && (surfaceState === 'limited' || surfaceState === 'processing') && items.length}
		<div class="status" role="status">{stateCardBody()}</div>
	{/if}

	{#if error && !showFallbackState}
		<div class="status status--error" role="alert">{error}</div>
	{:else if loading}
		<div class="status" role="status">{$t('evidence.loading')}</div>
	{:else if showFallbackState}
		<article class="result-card">
			<h3>{stateCardTitle()}</h3>
			<p class="result-text">{stateCardBody()}</p>
			<div class="table-actions">
				<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
					{$t('overview.goToWorkspace')}
				</a>
			</div>
		</article>
	{:else if !items.length}
		<p class="note">{$t('evidence.empty')}</p>
	{:else}
		<div class="result-grid">
			{#each items as item}
				<article class="result-card evidence-list-card">
					<div class="table-main">
						<div class="table-title">{item.claim_text || item.evidence_id}</div>
						<div class="table-sub">{item.material_system}</div>
					</div>
					<dl class="detail-list">
						<div class="detail-row">
							<dt>{$t('evidence.fieldClaimType')}</dt>
							<dd>{item.claim_type}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('evidence.fieldSource')}</dt>
							<dd>{item.evidence_source_type}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('evidence.fieldTraceability')}</dt>
							<dd>{item.traceability_status}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('evidence.fieldConfidence')}</dt>
							<dd>{formatConfidence(item.confidence)}</dd>
						</div>
					</dl>
					{#if item.evidence_anchors.length}
						<div class="detail-section">
							<div class="detail-section__title">{$t('evidence.anchorsTitle')}</div>
							<ul class="result-list">
								{#each item.evidence_anchors.slice(0, 3) as anchor}
									<li>{anchor.label}</li>
								{/each}
							</ul>
						</div>
					{/if}
					<div class="table-actions">
						<a class="btn btn--ghost btn--small" href={documentHref(item)}>
							{$t('traceback.openDocument')}
						</a>
					</div>
				</article>
			{/each}
		</div>
	{/if}
</section>
