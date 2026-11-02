import { expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { language } from '../../../_shared/i18n';
import MessageComposer from './MessageComposer.svelte';

it('keeps stop available while sending is disabled and prevents duplicate stops', async () => {
	language.set('en');
	const stop = vi.fn();
	const screen = render(MessageComposer, { disabled: true, sending: true, canStop: true, onStop: stop });
	await expect.element(screen.getByRole('button', { name: 'Stop response' })).toBeEnabled();
	await screen.getByRole('button', { name: 'Stop response' }).click();
	expect(stop).toHaveBeenCalledOnce();
	await screen.rerender({ stopping: true });
	await expect.element(screen.getByRole('button', { name: 'Stopping…' })).toBeDisabled();
	await screen.rerender({ canStop: false, stopping: false, sending: false, disabled: false, input: 'Use another comparison.' });
	await expect.element(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
});
