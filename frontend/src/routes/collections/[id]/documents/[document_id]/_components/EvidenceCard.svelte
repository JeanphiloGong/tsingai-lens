<script lang="ts">
	import { t } from '../../../../../_shared/i18n';
	import type { WorkbenchEvidenceCard } from '../../../../../_shared/documents';

	export let card: WorkbenchEvidenceCard;
	export let selected = false;
	export let onSelect: (id: string) => void = () => {};
	export let onJumpToSource: (sourceSpanId: string) => void = () => {};
</script>

<article class:selected class="evidence-card">
	<button class="card-hit-area" type="button" on:click={() => onSelect(card.id)}>
		<div class="card-title-row">
			<h3>{card.claim}</h3>
			<span class="source-label">{card.source_section}</span>
		</div>
		<p>{card.supporting_evidence}</p>
		<div class="meta-grid">
			<span class={`status-pill status-pill--${card.status}`}>{card.sufficiency}</span>
			<span>{$t('workbench.confidenceLabel')}: {card.confidence}</span>
		</div>
	</button>
	<button class="jump-button" type="button" on:click={() => onJumpToSource(card.source_span_id)}>
		{$t('workbench.jumpToSource')}
	</button>
</article>

<style>
	.evidence-card {
		position: relative;
		margin-bottom: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		background: #ffffff;
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
		transition:
			border-color 0.16s ease,
			box-shadow 0.16s ease,
			background 0.16s ease;
	}

	.evidence-card:hover {
		border-color: #bfdbfe;
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
	}

	.evidence-card.selected {
		border: 1.5px solid #2563eb;
		background: #f8fbff;
		box-shadow: 0 8px 24px rgba(37, 99, 235, 0.12);
	}

	.card-hit-area {
		display: block;
		width: 100%;
		padding: 16px 16px 48px;
		border: 0;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}

	.card-title-row {
		display: flex;
		margin-bottom: 8px;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	h3 {
		margin: 0;
		color: #0f172a;
		font-size: 15px;
		font-weight: 700;
		line-height: 22px;
	}

	p {
		margin: 0;
		color: #334155;
		font-size: 14px;
		line-height: 22px;
	}

	.source-label,
	.meta-grid {
		color: #64748b;
		font-size: 12px;
		font-weight: 500;
	}

	.meta-grid {
		display: flex;
		margin-top: 12px;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}

	.status-pill {
		display: inline-flex;
		height: 26px;
		align-items: center;
		padding: 0 10px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 700;
	}

	.status-pill--strong {
		background: #dcfce7;
		color: #15803d;
	}

	.status-pill--limited {
		background: #fff7ed;
		color: #c2410c;
	}

	.status-pill--missing {
		background: #f1f5f9;
		color: #475569;
	}

	.jump-button {
		position: absolute;
		right: 12px;
		bottom: 12px;
		padding: 4px 8px;
		border: 0;
		border-radius: 6px;
		background: transparent;
		color: #2563eb;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
	}

	.jump-button:hover {
		background: #eff6ff;
	}
</style>
