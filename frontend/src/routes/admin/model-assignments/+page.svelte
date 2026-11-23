<script lang="ts">
	import { onDestroy } from 'svelte';
	import PermissionGate from '../../_shared/PermissionGate.svelte';
	import { authState } from '../../_shared/authState';
	import { errorMessage, requestJson } from '../../_shared/api';
	import type { ModelConnectionChoice } from '$lib/agent/model-connections';
	import { t } from '../../_shared/i18n';
	import { permissionState } from '../../_shared/permissions';

	type Assignment = { connection_id: string | null; version: number };
	const endpoint = '/admin/model-assignments';
	const purposes = [
		{ value: 'document_profile', label: 'modelAssignments.documentProfile' },
		{ value: 'research_analysis', label: 'modelAssignments.researchAnalysis' },
		{ value: 'feedback', label: 'modelAssignments.feedback' },
		{ value: 'embedding', label: 'modelAssignments.embedding' }
	];
	let purpose = 'document_profile';
	let subject = '';
	let request = new AbortController();
	let assignment: Assignment | null = null;
	let choices: ModelConnectionChoice[] = [];
	let selected = '';
	let loading = false;
	let saving = false;
	let saved = false;
	let error = '';

	$: allowed =
		$authState.status === 'authenticated' &&
		$permissionState.status === 'ready' &&
		$permissionState.userId === $authState.user?.user_id &&
		$permissionState.codes.includes('models.manage');
	$: account = allowed ? $authState.user?.user_id || '' : '';
	$: if (account !== subject) {
		subject = account;
		request.abort();
		assignment = null;
		choices = [];
		selected = '';
		error = '';
		saved = false;
		loading = false;
		saving = false;
	}
	$: if (subject) void load();

	async function load() {
		request.abort();
		request = new AbortController();
		const signal = request.signal;
		loading = true;
		assignment = null;
		error = '';
		saved = false;
		try {
			const [current, available] = await Promise.all([
				requestJson(`${endpoint}/${purpose}`, { signal }) as Promise<Assignment>,
				requestJson(`${endpoint}/choices?kind=${purpose === 'embedding' ? 'embedding' : 'chat'}`, {
					signal
				}) as Promise<{ items: ModelConnectionChoice[] }>
			]);
			if (signal.aborted) return;
			assignment = current;
			selected = current.connection_id || '';
			choices = available.items;
		} catch (cause) {
			if (!signal.aborted) error = errorMessage(cause);
		} finally {
			if (!signal.aborted) loading = false;
		}
	}

	async function save() {
		if (!subject || saving || !assignment || !selected || selected === assignment.connection_id)
			return;
		const signal = request.signal;
		saving = true;
		error = '';
		saved = false;
		try {
			const updated = (await requestJson(`${endpoint}/${purpose}`, {
				method: 'PUT',
				signal,
				body: JSON.stringify({ connection_id: selected, expected_version: assignment.version })
			})) as Assignment;
			if (signal.aborted) return;
			assignment = updated;
			selected = updated.connection_id || '';
			saved = true;
		} catch (cause) {
			if (!signal.aborted) error = errorMessage(cause);
		} finally {
			if (!signal.aborted) saving = false;
		}
	}

	onDestroy(() => request.abort());
</script>

<svelte:head>
	<title>{$t('modelAssignments.title')} | Lens</title>
</svelte:head>

<PermissionGate code="models.manage">
	<h1>{$t('modelAssignments.title')}</h1>
	<div class="admin-form">
		<label>
			{$t('modelAssignments.purpose')}
			<select
				class="input"
				value={purpose}
				disabled={saving}
				on:change={(event) => {
					purpose = event.currentTarget.value;
					void load();
				}}
			>
				{#each purposes as item (item.value)}
					<option value={item.value}>{$t(item.label)}</option>
				{/each}
			</select>
		</label>
	</div>
	{#if loading}
		<p role="status">{$t('modelAssignments.loading')}</p>
	{:else if assignment}
		<form class="admin-form" on:submit|preventDefault={save}>
			<label>
				{$t('modelAssignments.connection')}
				<select class="input" bind:value={selected} disabled={saving || !choices.length}>
					<option value="" disabled>{$t('modelAssignments.unassigned')}</option>
					{#each choices as choice (choice.connection_id)}
						<option value={choice.connection_id}>{choice.display_name} · {choice.model}</option>
					{/each}
				</select>
			</label>
			<button
				class="btn btn--primary"
				disabled={saving || !selected || selected === assignment.connection_id}
			>
				{$t('modelAssignments.save')}
			</button>
		</form>
		{#if !choices.length}<p>{$t('modelAssignments.noModels')}</p>{/if}
	{/if}
	{#if saved}<p role="status">{$t('modelAssignments.saved')}</p>{/if}
	{#if error}
		<p role="alert">{error}</p>
		<button type="button" class="btn" on:click={load}>{$t('modelAssignments.reload')}</button>
	{/if}
</PermissionGate>
