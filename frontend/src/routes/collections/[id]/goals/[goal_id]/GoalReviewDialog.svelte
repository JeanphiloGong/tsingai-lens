<script lang="ts">
	import { t } from '../../../../_shared/i18n';
	import {
		createResearchUnderstandingCuration,
		createResearchUnderstandingFeedback,
		type ResearchUnderstandingCuration,
		type ResearchUnderstandingFeedback,
		type ResearchUnderstandingFeedbackIssueType,
		type ResearchUnderstandingPresentationFinding
	} from '../../../../_shared/researchView';

	type ReviewMode = 'accept' | 'reject' | 'correct';
	type EvidenceOption = {
		evidenceRefId: string;
		label: string;
		detail: string;
	};

	export let open = false;
	export let collectionId = '';
	export let scopeType = 'goal';
	export let scopeId = '';
	export let finding: ResearchUnderstandingPresentationFinding | null = null;
	export let evidenceOptions: EvidenceOption[] = [];
	export let reviewer = '';
	export let acceptBlocked = false;
	export let acceptanceChecks: string[] = [];
	export let onClose: () => void = () => undefined;
	export let onSubmitted: (
		record: ResearchUnderstandingFeedback | ResearchUnderstandingCuration
	) => void = () => undefined;

	const issueOptions: ResearchUnderstandingFeedbackIssueType[] = [
		'evidence_not_grounded',
		'missing_evidence',
		'insufficient_evidence',
		'wrong_variable',
		'wrong_outcome',
		'wrong_direction',
		'wrong_context',
		'wrong_relation',
		'overclaim',
		'unclear_statement',
		'other'
	];
	const supportGrades = ['strong', 'partial', 'weak', 'conflict', 'insufficient'];

	let dialogElement: HTMLDialogElement;
	let mode: ReviewMode = 'accept';
	let note = '';
	let issue: ResearchUnderstandingFeedbackIssueType = 'evidence_not_grounded';
	let statement = '';
	let variables = '';
	let mediators = '';
	let outcomes = '';
	let direction = '';
	let scopeSummary = '';
	let supportGrade = 'partial';
	let selectedEvidenceRefIds: string[] = [];
	let submitting = false;
	let error = '';
	let resetKey = '';

	$: if (dialogElement) {
		if (open && !dialogElement.open) dialogElement.showModal();
		if (!open && dialogElement.open) dialogElement.close();
	}
	$: if (open && finding && finding.finding_id !== resetKey) {
		resetKey = finding.finding_id;
		resetForm(finding);
	}
	$: canSubmit = Boolean(
		finding &&
		!submitting &&
		(mode === 'accept'
			? !acceptBlocked
			: mode === 'reject'
				? issue !== 'none' && note.trim()
				: statement.trim() &&
					variables.trim() &&
					outcomes.trim() &&
					scopeSummary.trim() &&
					selectedEvidenceRefIds.length > 0)
	);

	function resetForm(currentFinding: ResearchUnderstandingPresentationFinding) {
		mode = acceptBlocked ? 'correct' : 'accept';
		note = '';
		issue = 'evidence_not_grounded';
		statement = currentFinding.statement;
		variables = currentFinding.variables.join(', ');
		mediators = currentFinding.mediators.join(', ');
		outcomes = currentFinding.outcomes.join(', ');
		direction = currentFinding.direction;
		scopeSummary = currentFinding.scope_summary;
		supportGrade = currentFinding.support_grade || 'partial';
		selectedEvidenceRefIds = [...currentFinding.evidence_ref_ids];
		error = '';
	}

	function selectMode(nextMode: ReviewMode) {
		mode = nextMode;
		error = '';
	}

	function listItems(value: string) {
		return [
			...new Set(
				value
					.split(',')
					.map((item) => item.trim())
					.filter(Boolean)
			)
		];
	}

	function toggleEvidence(evidenceRefId: string) {
		selectedEvidenceRefIds = selectedEvidenceRefIds.includes(evidenceRefId)
			? selectedEvidenceRefIds.filter((item) => item !== evidenceRefId)
			: [...selectedEvidenceRefIds, evidenceRefId];
	}

	async function submitReview() {
		if (!canSubmit || !finding) return;
		submitting = true;
		error = '';
		try {
			if (mode === 'correct') {
				const record = await createResearchUnderstandingCuration(collectionId, {
					scope_type: scopeType,
					scope_id: scopeId,
					finding_id: finding.finding_id,
					claim_id: finding.claim_id || null,
					curated_claim_type: 'finding',
					curated_status: 'supported',
					curated_statement: statement.trim(),
					curated_support_grade: supportGrade,
					curated_review_status: 'curated',
					curated_variables: listItems(variables),
					curated_mediators: listItems(mediators),
					curated_outcomes: listItems(outcomes),
					curated_direction: direction.trim() || null,
					curated_scope_summary: scopeSummary.trim(),
					curated_evidence_ref_ids: selectedEvidenceRefIds,
					curated_context_ids: finding.context_ids,
					note: note.trim() || null,
					reviewer: reviewer || null
				});
				onSubmitted(record);
			} else {
				const record = await createResearchUnderstandingFeedback(collectionId, {
					scope_type: scopeType,
					scope_id: scopeId,
					finding_id: finding.finding_id,
					claim_id: finding.claim_id || null,
					review_status: mode === 'accept' ? 'correct' : 'incorrect',
					issue_type: mode === 'accept' ? 'none' : issue,
					note: note.trim() || null,
					reviewer: reviewer || null
				});
				onSubmitted(record);
			}
			onClose();
		} catch (reviewError) {
			error =
				reviewError instanceof Error
					? reviewError.message
					: $t('research.goalWorkspace.reviewUnexpectedError');
		} finally {
			submitting = false;
		}
	}
</script>

<dialog
	bind:this={dialogElement}
	class="review-dialog"
	aria-labelledby="goal-review-title"
	on:cancel|preventDefault={onClose}
>
	{#if finding}
		<form class="review-form" on:submit|preventDefault={submitReview}>
			<header class="review-header">
				<div>
					<p class="eyebrow">{$t('research.goalWorkspace.expertReview')}</p>
					<h2 id="goal-review-title">{$t('research.goalWorkspace.reviewFinding')}</h2>
				</div>
				<button
					class="close-button"
					type="button"
					aria-label={$t('research.goalWorkspace.closeReview')}
					title={$t('research.goalWorkspace.closeReview')}
					on:click={onClose}
				>
					<span aria-hidden="true">&times;</span>
				</button>
			</header>

			<p class="finding-statement">{finding.statement}</p>

			<div
				class="review-modes"
				role="group"
				aria-label={$t('research.goalWorkspace.reviewDecision')}
			>
				<button
					type="button"
					class:active={mode === 'accept'}
					aria-pressed={mode === 'accept'}
					disabled={acceptBlocked}
					on:click={() => selectMode('accept')}
				>
					{$t('research.goalWorkspace.accept')}
				</button>
				<button
					type="button"
					class:active={mode === 'reject'}
					aria-pressed={mode === 'reject'}
					on:click={() => selectMode('reject')}
				>
					{$t('research.goalWorkspace.reject')}
				</button>
				<button
					type="button"
					class:active={mode === 'correct'}
					aria-pressed={mode === 'correct'}
					on:click={() => selectMode('correct')}
				>
					{$t('research.goalWorkspace.correct')}
				</button>
			</div>

			{#if mode === 'accept'}
				<section class="decision-section">
					<h3>{$t('research.goalWorkspace.acceptTitle')}</h3>
					{#if acceptanceChecks.length}
						<ul class="checks">
							{#each acceptanceChecks as check}
								<li>{check}</li>
							{/each}
						</ul>
					{/if}
					<label>
						<span>{$t('research.goalWorkspace.reviewNoteOptional')}</span>
						<textarea name="review_note" bind:value={note} rows="3"></textarea>
					</label>
				</section>
			{:else if mode === 'reject'}
				<section class="decision-section">
					<label>
						<span>{$t('research.goalWorkspace.issueType')}</span>
						<select name="issue_type" bind:value={issue}>
							{#each issueOptions as option}
								<option value={option}>
									{$t(`research.understanding.feedbackIssues.${option}`)}
								</option>
							{/each}
						</select>
					</label>
					<label>
						<span>{$t('research.goalWorkspace.reviewNoteRequired')}</span>
						<textarea name="rejection_note" bind:value={note} rows="4" required></textarea>
					</label>
				</section>
			{:else}
				<section class="decision-section correction-fields">
					<label class="wide-field">
						<span>{$t('research.goalWorkspace.correctedFinding')}</span>
						<textarea name="curated_statement" bind:value={statement} rows="4" required></textarea>
					</label>
					<label>
						<span>{$t('research.goalWorkspace.variables')}</span>
						<input name="curated_variables" bind:value={variables} required />
					</label>
					<label>
						<span>{$t('research.goalWorkspace.mediators')}</span>
						<input name="curated_mediators" bind:value={mediators} />
					</label>
					<label>
						<span>{$t('research.goalWorkspace.outcomes')}</span>
						<input name="curated_outcomes" bind:value={outcomes} required />
					</label>
					<label>
						<span>{$t('research.goalWorkspace.direction')}</span>
						<input name="curated_direction" bind:value={direction} />
					</label>
					<label>
						<span>{$t('research.goalWorkspace.evidenceGrade')}</span>
						<select name="curated_support_grade" bind:value={supportGrade}>
							{#each supportGrades as grade}
								<option value={grade}>
									{$t(`research.understanding.supportGrades.${grade}`)}
								</option>
							{/each}
						</select>
					</label>
					<label class="wide-field">
						<span>{$t('research.goalWorkspace.applicability')}</span>
						<textarea name="curated_scope_summary" bind:value={scopeSummary} rows="3" required
						></textarea>
					</label>
					<fieldset class="wide-field evidence-selection">
						<legend>{$t('research.goalWorkspace.supportingEvidence')}</legend>
						{#each evidenceOptions as option}
							<label>
								<input
									type="checkbox"
									name="curated_evidence_ref_ids"
									checked={selectedEvidenceRefIds.includes(option.evidenceRefId)}
									on:change={() => toggleEvidence(option.evidenceRefId)}
								/>
								<span>
									<strong>{option.label}</strong>
									{#if option.detail}<small>{option.detail}</small>{/if}
								</span>
							</label>
						{/each}
					</fieldset>
					<label class="wide-field">
						<span>{$t('research.goalWorkspace.correctionNote')}</span>
						<textarea name="curation_note" bind:value={note} rows="3"></textarea>
					</label>
				</section>
			{/if}

			{#if acceptBlocked}
				<p class="review-warning" role="status">
					{$t('research.goalWorkspace.acceptBlocked')}
				</p>
			{/if}
			{#if error}<p class="review-error" role="alert">{error}</p>{/if}

			<footer class="review-footer">
				<button class="btn btn--ghost" type="button" on:click={onClose}>
					{$t('research.goalWorkspace.cancel')}
				</button>
				<button class="btn btn--primary" type="submit" disabled={!canSubmit}>
					{submitting
						? $t('research.goalWorkspace.savingReview')
						: $t('research.goalWorkspace.saveReview')}
				</button>
			</footer>
		</form>
	{/if}
</dialog>

<style>
	.review-dialog {
		position: fixed;
		inset: 0;
		width: min(760px, calc(100vw - 32px));
		max-height: calc(100vh - 40px);
		margin: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		color: var(--text-primary);
		padding: 0;
		box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2);
	}

	.review-dialog::backdrop {
		background: rgba(15, 23, 42, 0.48);
		backdrop-filter: blur(2px);
	}

	.review-form {
		display: grid;
		gap: 18px;
		padding: 22px;
	}

	.review-header,
	.review-footer {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}

	.review-header h2,
	.decision-section h3 {
		margin: 0;
		letter-spacing: 0;
	}

	.review-header h2 {
		font-size: 20px;
		line-height: 28px;
	}

	.eyebrow {
		margin: 0 0 4px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.close-button {
		display: inline-grid;
		width: 36px;
		height: 36px;
		flex: 0 0 36px;
		place-items: center;
		border: 1px solid var(--border-default);
		border-radius: 50%;
		background: transparent;
		color: var(--text-secondary);
		font-size: 24px;
		line-height: 1;
		cursor: pointer;
	}

	.close-button:hover {
		border-color: var(--text-secondary);
		color: var(--text-primary);
	}

	.finding-statement {
		margin: 0;
		border-left: 3px solid var(--accent);
		padding: 4px 0 4px 14px;
		font-size: 15px;
		font-weight: 600;
		line-height: 24px;
	}

	.review-modes {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 3px;
		background: var(--bg-subtle);
	}

	.review-modes button {
		min-height: 38px;
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--text-secondary);
		font: inherit;
		font-weight: 600;
		cursor: pointer;
	}

	.review-modes button.active {
		background: var(--surface-card);
		color: var(--text-primary);
		box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
	}

	.review-modes button:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.decision-section {
		display: grid;
		gap: 14px;
	}

	.decision-section h3 {
		font-size: 15px;
		line-height: 22px;
	}

	.decision-section label {
		display: grid;
		gap: 6px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.decision-section input,
	.decision-section select,
	.decision-section textarea {
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		line-height: 22px;
		padding: 9px 11px;
	}

	.decision-section textarea {
		resize: vertical;
	}

	.correction-fields {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}

	.wide-field {
		grid-column: 1 / -1;
	}

	.checks {
		margin: 0;
		padding-left: 20px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 21px;
	}

	.evidence-selection {
		display: grid;
		gap: 8px;
		min-width: 0;
		margin: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
	}

	.evidence-selection legend {
		padding: 0 5px;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.evidence-selection label {
		display: flex;
		align-items: flex-start;
		gap: 9px;
		border-bottom: 1px solid var(--border-default);
		padding: 8px 0;
	}

	.evidence-selection label:last-child {
		border-bottom: 0;
	}

	.evidence-selection input {
		width: 16px;
		height: 16px;
		flex: 0 0 16px;
		margin-top: 2px;
	}

	.evidence-selection strong,
	.evidence-selection small {
		display: block;
		overflow-wrap: anywhere;
	}

	.evidence-selection strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.evidence-selection small {
		margin-top: 2px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.review-warning,
	.review-error {
		margin: 0;
		border-radius: var(--radius-md);
		padding: 10px 12px;
		font-size: 13px;
		line-height: 20px;
	}

	.review-warning {
		border: 1px solid rgba(217, 119, 6, 0.34);
		background: rgba(255, 251, 235, 0.9);
	}

	.review-error {
		border: 1px solid rgba(185, 28, 28, 0.32);
		background: rgba(254, 242, 242, 0.9);
		color: var(--danger);
	}

	.review-footer {
		align-items: center;
		justify-content: flex-end;
		border-top: 1px solid var(--border-default);
		padding-top: 16px;
	}

	@media (max-width: 640px) {
		.review-dialog {
			width: calc(100vw - 20px);
			max-height: calc(100vh - 20px);
		}

		.review-form {
			padding: 18px;
		}

		.correction-fields {
			grid-template-columns: 1fr;
		}

		.wide-field {
			grid-column: auto;
		}
	}
</style>
