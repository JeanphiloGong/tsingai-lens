<script lang="ts">
	import { onMount } from 'svelte';
	import { ShieldCheck, ChevronDown } from '@lucide/svelte';
	import { t } from '../../../_shared/i18n';
	import { errorMessage } from '../../../_shared/api';
	import {
		fetchChatPermission,
		updateChatPermission,
		AGENT_WRITE_ACTIONS,
		type ChatPermission
	} from '../../../_shared/chatSessions';
	import {
		fetchCollectionAgentPermission,
		updateCollectionAgentPermission
	} from '../../../_shared/collections';

	export let sessionId = '';
	export let collectionId = '';
	export let scope: 'session' | 'collection' = 'session';
	export let standalone = false;
	let permission: ChatPermission | null = null;
	let mode: ChatPermission['mode'] = 'confirm';
	let actions: string[] = [];
	let hours = 1;
	let loadedHours = 1;
	let busy = false;
	let error = '';
	let disclosure: HTMLDetailsElement;
	$: hasPendingChanges = Boolean(
		permission &&
		(mode !== permission.mode ||
			actions.length !== (permission?.actions.length ?? 0) ||
			actions.some((action) => !(permission?.actions ?? []).includes(action)) ||
			(mode === 'auto' && hours !== loadedHours))
	);
	$: autoSelectionValid = mode !== 'auto' || actions.length > 0;
	const available = [...AGENT_WRITE_ACTIONS];
	function hasAllActions() {
		return available.every((action) => actions.includes(action));
	}
	function hoursUntil(expiresAt: string | null) {
		if (!expiresAt) return 1;
		const remaining = (Date.parse(expiresAt) - Date.now()) / 3600000;
		if (!Number.isFinite(remaining) || remaining <= 0) return 1;
		return Math.min(24, Math.max(1, Math.ceil(remaining)));
	}
	function hasLiveExpiry(expiresAt: string | null) {
		if (!expiresAt) return false;
		const timestamp = Date.parse(expiresAt);
		return Number.isFinite(timestamp) && timestamp > Date.now();
	}
	function applyPermission(next: ChatPermission) {
		permission = next;
		mode = next.mode;
		actions = [...next.actions];
		hours = hoursUntil(next.expires_at);
		loadedHours = hours;
	}
	async function load() {
		busy = true;
		try {
			const next =
				scope === 'collection'
					? await fetchCollectionAgentPermission(collectionId)
					: await fetchChatPermission(sessionId);
			applyPermission(next);
			error = '';
		} catch (cause) {
			error = errorMessage(cause);
		} finally {
			busy = false;
		}
	}
	onMount(load);
	async function save(revoke = false) {
		if (!permission) return;
		busy = true;
		try {
			const nextMode = revoke ? 'confirm' : mode;
			const expiresAt =
				nextMode !== 'auto'
					? null
					: permission.mode === 'auto' &&
						  hasLiveExpiry(permission.expires_at) &&
						  hours === loadedHours
						? permission.expires_at
						: new Date(Date.now() + hours * 3600000).toISOString();
			const nextPermission = {
				...permission,
				mode: nextMode,
				actions: nextMode === 'auto' ? actions : [],
				expires_at: expiresAt
			};
			const updated =
				scope === 'collection'
					? await updateCollectionAgentPermission(collectionId, nextPermission, {
							allActions: nextMode === 'auto' && hasAllActions()
						})
					: await updateChatPermission(sessionId, nextPermission, {
							allActions: nextMode === 'auto' && hasAllActions()
						});
			applyPermission(updated);
			error = '';
		} catch (cause) {
			error = errorMessage(cause);
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window
	on:keydown={(event) => {
		if (event.key === 'Escape' && disclosure?.open) {
			disclosure.open = false;
			disclosure.querySelector('summary')?.focus();
		}
	}}
/>
<div class="permission-toolbar" class:standalone>
	<details class="permissions" bind:this={disclosure} open={standalone}>
		<summary aria-label={$t('agentPermission.title')}
			><ShieldCheck size={14} /><span
				>{permission
					? $t(`agentPermission.${permission.mode}`)
					: $t('agentPermission.loading')}</span
			><ChevronDown size={12} /></summary
		>
		<div class="permission-panel">
			<strong
				>{$t(
					scope === 'collection' ? 'agentPermission.defaultTitle' : 'agentPermission.title'
				)}</strong
			>
			{#if permission}
				{#if scope === 'collection' && !standalone}
					<p class="permission-hint">{$t('agentPermission.defaultScope')}</p>
				{/if}
				<label
					>{$t('agentPermission.mode')}
					<select bind:value={mode} disabled={busy}>
						<option value="read_only">{$t('agentPermission.read_only')}</option>
						<option value="confirm">{$t('agentPermission.confirm')}</option>
						<option value="auto">{$t('agentPermission.auto')}</option>
					</select>
				</label>
				{#if mode === 'auto'}
					<fieldset disabled={busy}>
						<legend
							>{$t(
								scope === 'collection'
									? 'agentPermission.defaultActions'
									: 'agentPermission.actions'
							)}</legend
						>
						<label class="select-all"
							><input
								type="checkbox"
								checked={hasAllActions()}
								on:change={() => (actions = hasAllActions() ? [] : [...available])}
							/>{$t('agentPermission.allActions')}</label
						>
						{#each available as action (action)}
							<label
								><input type="checkbox" bind:group={actions} value={action} />{$t(
									`agentPermission.${action}`
								)}</label
							>
						{/each}
						<label
							>{$t('agentPermission.hours')}<input
								type="number"
								min="1"
								max="24"
								bind:value={hours}
							/></label
						>
						<p class="permission-hint">{$t('agentPermission.automaticScope')}</p>
						{#if hasAllActions()}
							<p class="permission-warning" role="note">
								{$t('agentPermission.automaticWarning')}
							</p>
						{/if}
					</fieldset>
					{#if !autoSelectionValid}<p class="permission-hint" role="status">
							{$t('agentPermission.selectAction')}
						</p>{/if}
				{/if}
				{#if hasPendingChanges}<p class="permission-dirty" role="status">
						{$t('agentPermission.unsaved')}
					</p>{/if}
				{#if permission.expires_at}<p>
						{$t('agentPermission.expires')}: {new Date(permission.expires_at).toLocaleString()}
					</p>{/if}
				<button
					type="button"
					disabled={busy ||
						!autoSelectionValid ||
						(mode === 'auto' && !(hours >= 1 && hours <= 24))}
					on:click={() => save()}>{$t('agentPermission.save')}</button
				>
				{#if permission.mode === 'auto'}<button
						type="button"
						class="secondary"
						disabled={busy}
						on:click={() => save(true)}>{$t('agentPermission.revoke')}</button
					>{/if}
			{/if}
			{#if error}<p role="alert">{error}</p>
				<button type="button" disabled={busy} on:click={load}>{$t('agentPermission.reload')}</button
				>{/if}
		</div>
	</details>
</div>

<style>
	.permission-toolbar {
		display: flex;
		justify-content: flex-end;
		padding: 4px 20px;
		min-height: 34px;
		flex-shrink: 0;
	}
	.permission-toolbar.standalone {
		display: block;
		padding: 0;
	}
	.permissions {
		position: relative;
		font-size: 12px;
		max-width: 100%;
	}
	.standalone .permissions {
		width: 100%;
	}
	summary {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 6px;
		cursor: pointer;
		color: var(--text-secondary);
		list-style: none;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	.permission-panel {
		position: absolute;
		right: 0;
		top: calc(100% + 4px);
		width: min(350px, calc(100vw - 40px));
		max-height: 65dvh;
		overflow-y: auto;
		padding: 18px;
		box-sizing: border-box;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
		box-shadow: 0 8px 28px #00000014;
		z-index: 20;
	}
	.standalone .permission-panel {
		position: static;
		width: 100%;
		max-height: none;
		box-shadow: none;
	}
	.permission-panel > strong {
		display: block;
		margin-bottom: 14px;
		color: var(--text-primary);
	}
	summary:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 3px;
	}
	label {
		display: flex;
		gap: 8px;
		align-items: center;
		margin: 8px 0;
		flex-wrap: wrap;
	}
	fieldset {
		border: 0;
		padding: 0;
	}
	.select-all {
		padding-bottom: 8px;
		border-bottom: 1px solid var(--border-default);
		font-weight: 700;
	}
	select,
	input[type='number'] {
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		padding: 6px 8px;
	}
	input[type='number'] {
		width: 70px;
	}
	button {
		margin: 4px 8px 4px 0;
		padding: 7px 10px;
		border: 1px solid var(--brand-primary);
		border-radius: 6px;
		background: var(--brand-primary);
		color: white;
		cursor: pointer;
	}
	button.secondary {
		border-color: var(--border-default);
		background: var(--surface-card);
		color: var(--text-primary);
	}
	button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	p {
		overflow-wrap: anywhere;
	}
	.permission-hint,
	.permission-dirty {
		margin: 8px 0;
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 16px;
	}
	.permission-dirty {
		color: var(--warning-text);
	}
	.permission-warning {
		margin: 10px 0;
		padding: 8px 10px;
		border-left: 3px solid var(--warning-text);
		background: color-mix(in srgb, var(--warning-text) 10%, transparent);
		color: var(--text-primary);
		font-size: 11px;
		line-height: 16px;
	}
</style>
