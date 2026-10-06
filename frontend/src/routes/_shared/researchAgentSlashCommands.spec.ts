import { describe, expect, it } from 'vitest';
import {
	matchingResearchAgentSlashCommands,
	resolveResearchAgentSlashCommand,
	slashCommandQuery,
	slashCommandToken
} from './researchAgentSlashCommands';

describe('Research Agent slash commands', () => {
	it('offers all local commands for a bare slash and filters by prefix', () => {
		expect(matchingResearchAgentSlashCommands('/')).toHaveLength(7);
		expect(matchingResearchAgentSlashCommands('/per').map((command) => command.name)).toEqual([
			'permissions'
		]);
		expect(matchingResearchAgentSlashCommands('/br').map((command) => command.name)).toEqual([
			'tree'
		]);
	});

	it('resolves aliases to the canonical command without accepting arguments', () => {
		expect(resolveResearchAgentSlashCommand('/perm')?.name).toBe('permissions');
		expect(resolveResearchAgentSlashCommand('/RESET')?.name).toBe('new');
		expect(resolveResearchAgentSlashCommand('/permissions now')).toBeNull();
		expect(resolveResearchAgentSlashCommand('Please /permissions')).toBeNull();
	});

	it('only treats an argument-free slash token as an active popup query', () => {
		expect(slashCommandQuery('/status')).toBe('status');
		expect(slashCommandQuery('/status now')).toBeNull();
		expect(slashCommandQuery('read /status')).toBeNull();
	});

	it('keeps an unknown slash token local for a client-side error', () => {
		expect(slashCommandToken('/missing')).toBe('missing');
		expect(slashCommandToken('/missing extra')).toBe('missing');
		expect(slashCommandToken('ordinary question')).toBeNull();
	});
});
