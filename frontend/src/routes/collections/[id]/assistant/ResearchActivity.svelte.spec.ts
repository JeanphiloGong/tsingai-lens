import { page } from 'vitest/browser';
import { beforeEach, describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { language } from '../../../_shared/i18n';
import type { ChatMessage } from '../../../_shared/chatSessions';
import type { ChatPresentationItem } from './conversationPresentation';
import ResearchActivity from './ResearchActivity.svelte';

function activity(papers: Record<string, unknown>[], extra: Record<string, unknown> = {}) {
	const resultMessage: ChatMessage = {
		message_id: 'result',
		session_id: 'session',
		role: 'tool',
		content: '',
		created_at: '2026-10-09T10:00:00Z',
		tool_call_id: 'browse',
		tool_calls: [],
		source_contexts: [],
		tool_result: {
			tool_call_id: 'browse',
			status: 'succeeded',
			error_code: null,
			error_message: null,
			data: {
				papers,
				returned_paper_count: papers.length,
				paper_total: papers.length,
				next_offset: null,
				...extra
			},
			warnings: papers.some((paper) =>
				['preparation_failed', 'unavailable', 'read_failed'].includes(String(paper.source_status))
			)
				? ['Prepared Source content is unavailable.']
				: [],
			resource_refs: papers.map((paper) => ({
				resource_type: 'document',
				resource_id: String(paper.document_id),
				href: `/collections/col_123/documents/${paper.document_id}`
			}))
		}
	};
	return {
		kind: 'activity',
		id: 'activity',
		status: 'completed',
		artifacts: [],
		operations: [
			{
				toolCallId: 'browse',
				toolName: 'browse_collection_papers',
				requestMessage: null,
				resultMessage
			}
		]
	} satisfies ChatPresentationItem;
}

beforeEach(() => language.set('zh'));

it('shows unavailable counts without inventing an empty search result', async () => {
	const item = activity([], { returned_paper_count: undefined, query: 'LPBF' });
	render(ResearchActivity, { item });
	await expect.element(page.getByText(/--/)).toBeInTheDocument();
	await expect.element(page.getByText(/未找到|No papers matched/)).not.toBeInTheDocument();
});

describe('paper browsing activity', () => {
	it('keeps optional metadata and normal pagination out of warning UI', async () => {
		render(ResearchActivity, {
			item: activity(
				[
					{
						document_id: 'paper-1',
						filename: 'LPBF.pdf',
						source_status: 'available',
						map_status: 'not_available',
						abstract_status: 'not_found'
					}
				],
				{ paper_total: 100, next_offset: 1 }
			)
		});
		expect(
			document.querySelector<HTMLDetailsElement>('[data-testid="research-activity"]')?.open
		).toBe(false);
		document
			.querySelector<HTMLDetailsElement>('[data-testid="research-activity"] summary')
			?.click();
		await expect.element(page.getByText('本页列出 1 篇论文，后续还有 99 篇')).toBeVisible();
		expect(document.querySelector('.warnings')).toBeNull();
	});

	it('groups real failures by paper name and provides the existing document entry', async () => {
		render(ResearchActivity, {
			item: activity([
				{
					document_id: 'doc_private_1',
					title: 'LPBF preparation study',
					source_status: 'preparation_failed'
				},
				{
					document_id: 'doc_private_2',
					filename: 'Heat treatment.pdf',
					source_status: 'read_failed'
				},
				{
					document_id: 'doc_private_3',
					filename: 'Missing result.pdf',
					source_status: 'unavailable'
				}
			])
		});
		expect(
			document.querySelector<HTMLDetailsElement>('[data-testid="research-activity"]')?.open
		).toBe(true);
		await page.getByText('3 篇论文暂时无法读取原文', { exact: true }).click();
		await expect.element(page.getByText('文献准备失败', { exact: true })).toBeVisible();
		await expect.element(page.getByText('原文读取失败', { exact: true })).toBeVisible();
		await expect.element(page.getByText('解析结果不可用', { exact: true })).toBeVisible();
		await expect
			.element(page.getByRole('list').getByText('Heat treatment.pdf', { exact: true }))
			.toBeVisible();
		expect(document.querySelector('.paper-source-issues a')?.getAttribute('href')).toBe(
			'/collections/col_123/documents/doc_private_1'
		);
		expect(document.querySelector('[data-testid="research-activity"]')?.textContent).not.toContain(
			'doc_private_'
		);
		expect(document.querySelector('[data-testid="research-activity"]')?.textContent).not.toContain(
			'Prepared Source content'
		);
	});

	it('shows preparing and stored papers as ordinary pending states', async () => {
		render(ResearchActivity, {
			item: activity([
				{ document_id: 'paper-1', filename: 'Processing.pdf', source_status: 'preparing' },
				{ document_id: 'paper-2', filename: 'Stored.pdf', source_status: 'not_prepared' }
			])
		});
		expect(
			document.querySelector<HTMLDetailsElement>('[data-testid="research-activity"]')?.open
		).toBe(false);
		document
			.querySelector<HTMLDetailsElement>('[data-testid="research-activity"] summary')
			?.click();
		await page.getByText('2 篇论文原文尚未就绪', { exact: true }).click();
		await expect.element(page.getByText('文献准备中', { exact: true })).toBeVisible();
		await expect.element(page.getByText('尚未准备原文', { exact: true })).toBeVisible();
		expect(document.querySelector('.paper-source-issues.failed')).toBeNull();
	});
});
