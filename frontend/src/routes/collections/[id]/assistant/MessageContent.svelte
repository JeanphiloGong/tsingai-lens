<script lang="ts">
	import { t } from '../../../_shared/i18n';
	export let content = '';
	export let streaming = false;
	type InlineSegment = {
		text: string;
		strong: boolean;
	};
	type RenderBlock =
		| { kind: 'paragraph'; segments: InlineSegment[] }
		| { kind: 'list'; items: InlineSegment[][] };
	function renderInlineMarkdown(text: string): InlineSegment[] {
		const segments: InlineSegment[] = [];
		const pattern = /\*\*([^*]+)\*\*/g;
		let lastIndex = 0;
		let match: RegExpExecArray | null;
		while ((match = pattern.exec(text)) !== null) {
			if (match.index > lastIndex) {
				segments.push({ text: text.slice(lastIndex, match.index), strong: false });
			}
			segments.push({ text: match[1], strong: true });
			lastIndex = match.index + match[0].length;
		}
		if (lastIndex < text.length) {
			segments.push({ text: text.slice(lastIndex), strong: false });
		}
		return segments.length ? segments : [{ text, strong: false }];
	}

	function renderMessageBlocks(text: string): RenderBlock[] {
		return text
			.split(/\n{2,}/)
			.map((block) => block.trim())
			.filter(Boolean)
			.map((block) => {
				const lines = block
					.split('\n')
					.map((line) => line.trim())
					.filter(Boolean);
				const items = lines
					.map((line) => line.match(/^(?:[-*]\s+|\d+\.\s+)(.+)$/))
					.filter((match): match is RegExpMatchArray => Boolean(match));
				if (items.length === lines.length) {
					return {
						kind: 'list' as const,
						items: items.map((item) => renderInlineMarkdown(item[1].trim()))
					};
				}
				return {
					kind: 'paragraph' as const,
					segments: renderInlineMarkdown(lines.join(' '))
				};
			});
	}
</script>

{#if content}
	<div class="assistant-copy">
		{#each renderMessageBlocks(content) as block, blockIndex (blockIndex)}
			{#if block.kind === 'list'}
				<ul>
					{#each block.items as item, itemIndex (itemIndex)}
						<li>
							{#each item as segment, segmentIndex (segmentIndex)}
								{#if segment.strong}<strong>{segment.text}</strong>{:else}{segment.text}{/if}
							{/each}
						</li>
					{/each}
				</ul>
			{:else}
				<p>
					{#each block.segments as segment, segmentIndex (segmentIndex)}
						{#if segment.strong}<strong>{segment.text}</strong>{:else}{segment.text}{/if}
					{/each}
				</p>
			{/if}
		{/each}
		{#if streaming}
			<span class="stream-cursor" aria-hidden="true"></span>
		{/if}
	</div>
{:else if streaming}
	<div class="assistant-copy streaming-copy" role="status" aria-label={$t('researchAgent.sending')}>
		<span class="stream-cursor" aria-hidden="true"></span>
	</div>
{/if}

<style>
	.assistant-copy {
		padding: 2px 0 0;
		font-size: 14px;
		line-height: 23px;
		overflow-wrap: anywhere;
	}

	.assistant-copy p,
	.assistant-copy ul {
		margin: 0 0 9px;
	}

	.assistant-copy p:last-child,
	.assistant-copy ul:last-child {
		margin-bottom: 0;
	}

	.streaming-copy {
		min-width: 48px;
		min-height: 51px;
	}

	.stream-cursor {
		display: inline-block;
		width: 2px;
		height: 1em;
		margin-left: 2px;
		background: currentColor;
		vertical-align: text-bottom;
		animation: stream-cursor 0.9s steps(1) infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.stream-cursor {
			animation: none;
		}
	}

	@keyframes stream-cursor {
		50% {
			opacity: 0;
		}
	}
</style>
