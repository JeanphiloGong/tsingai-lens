export type ResearchAgentSlashCommandName =
	| 'permissions'
	| 'settings'
	| 'status'
	| 'new'
	| 'history'
	| 'tree'
	| 'help';

export type ResearchAgentSlashCommand = {
	name: ResearchAgentSlashCommandName;
	aliases?: readonly string[];
	labelKey: string;
	descriptionKey: string;
};

/**
 * Commands are client actions. They are deliberately kept outside the model
 * message so a control action cannot become research context by accident.
 */
export const RESEARCH_AGENT_SLASH_COMMANDS: readonly ResearchAgentSlashCommand[] = [
	{
		name: 'permissions',
		aliases: ['perm'],
		labelKey: 'researchAgent.commands.permissionsLabel',
		descriptionKey: 'researchAgent.commands.permissionsDescription'
	},
	{
		name: 'settings',
		labelKey: 'researchAgent.commands.settingsLabel',
		descriptionKey: 'researchAgent.commands.settingsDescription'
	},
	{
		name: 'status',
		labelKey: 'researchAgent.commands.statusLabel',
		descriptionKey: 'researchAgent.commands.statusDescription'
	},
	{
		name: 'new',
		aliases: ['reset'],
		labelKey: 'researchAgent.commands.newLabel',
		descriptionKey: 'researchAgent.commands.newDescription'
	},
	{
		name: 'history',
		aliases: ['sessions'],
		labelKey: 'researchAgent.commands.historyLabel',
		descriptionKey: 'researchAgent.commands.historyDescription'
	},
	{
		name: 'tree',
		aliases: ['branches'],
		labelKey: 'researchAgent.commands.treeLabel',
		descriptionKey: 'researchAgent.commands.treeDescription'
	},
	{
		name: 'help',
		aliases: ['commands'],
		labelKey: 'researchAgent.commands.helpLabel',
		descriptionKey: 'researchAgent.commands.helpDescription'
	}
];

function commandNames(command: ResearchAgentSlashCommand) {
	return [command.name, ...(command.aliases ?? [])];
}

/** Return the slash token while the composer is still editing a command. */
export function slashCommandQuery(input: string): string | null {
	if (!input.startsWith('/') || /\s/.test(input)) return null;
	return input.slice(1).toLowerCase();
}

/** Return the first slash token so unknown commands can stay local as well. */
export function slashCommandToken(input: string): string | null {
	if (!input.startsWith('/')) return null;
	const token = input.trim().split(/\s+/, 1)[0] ?? '/';
	return token.slice(1).toLowerCase();
}

/** Filter canonical commands for the popup; aliases are accepted but not shown twice. */
export function matchingResearchAgentSlashCommands(input: string) {
	const query = slashCommandQuery(input);
	if (query === null) return [] as ResearchAgentSlashCommand[];
	return RESEARCH_AGENT_SLASH_COMMANDS.filter((command) =>
		commandNames(command).some((name) => name.startsWith(query))
	);
}

/** Resolve only a complete, argument-free command. Other text remains a normal question. */
export function resolveResearchAgentSlashCommand(input: string): ResearchAgentSlashCommand | null {
	const value = input.trim().toLowerCase();
	if (!/^\/[a-z0-9_-]+$/.test(value)) return null;
	return (
		RESEARCH_AGENT_SLASH_COMMANDS.find((command) =>
			commandNames(command).includes(value.slice(1))
		) ?? null
	);
}
