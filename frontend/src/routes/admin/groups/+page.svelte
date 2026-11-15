<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import PermissionGate from '../../_shared/PermissionGate.svelte';
	import { permissionState, refreshPermissions } from '../../_shared/permissions';
	import { authState, clearAuthState } from '../../_shared/authState';
	import { t } from '../../_shared/i18n';
	import { requestJson, errorMessage, getApiErrorReason, isApiErrorCode } from '../../_shared/api';
	type Entry = { code: string; name: string; description: string; is_system: boolean };
	type EntryPage = { items: Entry[]; total: number; limit: number; offset: number };
	let page: EntryPage = { items: [], total: 0, limit: 50, offset: 0 };
	let limit = 50,
		offset = 0,
		selected = '',
		newCode = '',
		newName = '',
		newDescription = '',
		editName = '',
		editDescription = '',
		error = '';
	let saved = false;
	let busy = false,
		loading = false,
		associationLoading = false,
		mounted = false,
		subject = '',
		loadedSubject = '',
		generation = 0;
	$: currentSubject = $authState.status === 'authenticated' ? ($authState.user?.user_id ?? '') : '';
	$: canManage =
		$permissionState.status === 'ready' &&
		$permissionState.userId === currentSubject &&
		$permissionState.codes.includes('users.manage');
	$: if (currentSubject !== subject) {
		subject = currentSubject;
		loadedSubject = '';
		saved = false;
		generation++;
		page = { items: [], total: 0, limit, offset: 0 };
		selected = '';
		offset = 0;
		newCode = '';
		newName = '';
		newDescription = '';
		editName = '';
		editDescription = '';
		error = '';
		busy = false;
		loading = false;
		associationLoading = false;
		associationGeneration++;
		association = { items: [], total: 0, limit: 50, offset: 0 };
		associationOffset = 0;
		permissionCode = '';
	}
	$: if (mounted && canManage && subject && loadedSubject !== subject) {
		loadedSubject = subject;
		void load();
	}
	$: selectedItem = page.items.find((item) => item.code === selected);
	onMount(() => {
		mounted = true;
	});
	onDestroy(() => {
		mounted = false;
		subject = '';
		generation++;
		associationGeneration++;
	});
	function showError(caught: unknown) {
		saved = false;
		const reason = getApiErrorReason(caught);
		error =
			reason === 'already_exists'
				? $t('admin.duplicate')
				: reason === 'invalid_request'
					? $t('admin.invalid')
					: errorMessage(caught);
		if (isApiErrorCode(caught, 200301)) clearAuthState();
		else if (isApiErrorCode(caught, 200203)) void refreshPermissions();
	}

	async function load() {
		const request = ++generation,
			owner = subject;
		loading = true;
		error = '';
		try {
			const result: EntryPage = await requestJson(
				`/user-api/v1/admin/groups?limit=${limit}&offset=${offset}`
			);
			if (request === generation && owner === subject) page = result;
		} catch (caught) {
			if (request === generation && owner === subject) showError(caught);
		} finally {
			if (request === generation && owner === subject) loading = false;
		}
	}
	function select(item: Entry) {
		selected = item.code;
		editName = item.name;
		editDescription = item.description;
		associationOffset = 0;
		permissionCode = '';
		association = { items: [], total: 0, limit: 50, offset: 0 };
		void loadAssociation();
	}
	function pageEntries(next: number) {
		offset = next;
		selected = '';
		associationGeneration++;
		void load();
	}
	async function mutate(method: string, path: string, body?: unknown): Promise<boolean> {
		if (busy) return false;
		const owner = subject;
		busy = true;
		saved = false;
		error = '';
		try {
			await requestJson(path, {
				method,
				...(body === undefined ? {} : { body: JSON.stringify(body) })
			});
			if (owner !== subject) return false;
			await load();
			if (selected && page.items.some((item) => item.code === selected)) {
				associationOffset = 0;
				await loadAssociation();
			}
			if (owner !== subject) return false;
			await refreshPermissions();
			saved = owner === subject;
			return owner === subject;
		} catch (caught) {
			if (owner === subject) showError(caught);
			return false;
		} finally {
			if (owner === subject) busy = false;
		}
	}
	async function createItem() {
		if (
			await mutate('POST', '/user-api/v1/admin/groups', {
				code: newCode,
				name: newName,
				description: newDescription
			})
		) {
			newCode = '';
			newName = '';
			newDescription = '';
		}
	}
	async function saveMetadata() {
		await mutate('PATCH', `/user-api/v1/admin/groups/${encodeURIComponent(selected)}`, {
			name: editName,
			description: editDescription
		});
	}
	async function deleteItem() {
		if (!window.confirm($t('admin.confirmDelete'))) return;
		if (await mutate('DELETE', `/user-api/v1/admin/groups/${encodeURIComponent(selected)}`))
			selected = '';
	}

	let association: EntryPage = { items: [], total: 0, limit: 50, offset: 0 };
	let permissionCode = '',
		associationOffset = 0,
		associationGeneration = 0;
	async function loadAssociation() {
		const request = ++associationGeneration,
			owner = subject,
			target = selected;
		if (!target) return;
		associationLoading = true;
		try {
			const result: EntryPage = await requestJson(
				`/user-api/v1/admin/groups/${encodeURIComponent(target)}/permissions?limit=50&offset=${associationOffset}`
			);
			if (request === associationGeneration && owner === subject && target === selected)
				association = result;
		} catch (caught) {
			if (request === associationGeneration && owner === subject && target === selected)
				showError(caught);
		} finally {
			if (request === associationGeneration && owner === subject && target === selected)
				associationLoading = false;
		}
	}
	async function changePermission(method: 'PUT' | 'DELETE', code: string) {
		if (
			await mutate(
				method,
				`/user-api/v1/admin/groups/${encodeURIComponent(selected)}/permissions/${encodeURIComponent(code)}`
			)
		)
			permissionCode = '';
	}
</script>

<svelte:head><title>{$t('admin.title')} · Lens</title></svelte:head>
<h1>{$t('admin.groups')}</h1>
<PermissionGate code="users.manage">
	{#if saved}<p class="status admin-success" role="status">{$t('admin.saved')}</p>{/if}
	{#if error}<p class="status status--error" role="alert">{error}</p>{/if}
	{#if loading}<p class="status" role="status">{$t('admin.loading')}</p>{/if}
	<div class="toolbar">
		<label
			>{$t('admin.pageSize')}
			<select
				class="input"
				aria-label={$t('admin.pageSize')}
				bind:value={limit}
				on:change={() => pageEntries(0)}
				disabled={busy}
				><option value={2}>2</option><option value={10}>10</option><option value={50}>50</option
				><option value={200}>200</option></select
			></label
		>
		<button class="btn btn--ghost" type="button" disabled={busy} on:click={load}
			>{$t('admin.refresh')}</button
		>
		<button
			class="btn btn--ghost"
			type="button"
			disabled={busy || offset === 0}
			on:click={() => pageEntries(Math.max(0, offset - limit))}
			>{$t('admin.previousEntries')}</button
		>
		<button
			class="btn btn--ghost"
			type="button"
			disabled={busy || offset + limit >= page.total}
			on:click={() => pageEntries(offset + limit)}>{$t('admin.nextEntries')}</button
		>
		<span>{$t('admin.total')}: {page.total}</span>
	</div>
	<div class="table-wrap">
		<table aria-busy={loading}>
			<thead
				><tr
					><th>{$t('admin.code')}</th><th>{$t('admin.name')}</th><th>{$t('admin.builtIn')}</th></tr
				></thead
			><tbody>
				{#each page.items as item (item.code)}<tr class:selected={item.code === selected}
						><td
							><button
								class="btn btn--ghost"
								type="button"
								disabled={busy}
								aria-pressed={selected === item.code}
								on:click={() => select(item)}>{item.code}</button
							></td
						><td>{item.name}</td><td>{item.is_system ? $t('admin.yes') : $t('admin.no')}</td></tr
					>{/each}
			</tbody>
		</table>
	</div>
	{#if !loading && page.items.length === 0}<p>
			{$t('admin.noEntries')}
		</p>{/if}
	<section aria-labelledby="create-entry">
		<h2 id="create-entry">{$t('admin.createGroup')}</h2>
		<form class="admin-form" on:submit|preventDefault={createItem}>
			<label
				>{$t('admin.newGroupCode')}
				<input
					class="input"
					maxlength="64"
					pattern="[a-z][a-z0-9_]*"
					bind:value={newCode}
					required
					disabled={busy}
				/></label
			>
			<label
				>{$t('admin.newGroupName')}
				<input class="input" maxlength="100" bind:value={newName} required disabled={busy} /></label
			>
			<label
				>{$t('admin.newGroupDescription')}
				<input class="input" maxlength="1000" bind:value={newDescription} disabled={busy} /></label
			>
			<button class="btn btn--primary" disabled={busy}>{$t('admin.createGroup')}</button>
		</form>
	</section>
	{#if selectedItem}
		<section aria-labelledby="selected-entry">
			<h2 id="selected-entry">{selectedItem.code}</h2>
			<p class="muted">{$t('admin.stableCode')}</p>
			{#if selectedItem.is_system}<p>
					{$t('admin.protectedEntry')}
				</p>{/if}
			<form class="admin-form" on:submit|preventDefault={saveMetadata}>
				<label
					>{$t('admin.groupName')}
					<input
						class="input"
						maxlength="100"
						bind:value={editName}
						required
						disabled={busy}
					/></label
				>
				<label
					>{$t('admin.groupDescription')}
					<input
						class="input"
						maxlength="1000"
						bind:value={editDescription}
						disabled={busy}
					/></label
				>
				<button class="btn btn--primary" disabled={busy}>{$t('admin.saveMetadata')}</button>
			</form>
			<button
				class="btn btn--ghost"
				type="button"
				disabled={busy || selectedItem.is_system}
				on:click={deleteItem}>{$t('admin.deleteGroup')}</button
			>

			<h3>{$t('admin.groupPermissions')}</h3>
			{#if associationLoading}<p role="status">{$t('admin.loadingAssociations')}</p>{/if}
			<ul>
				{#each association.items as item (item.code)}<li>
						{item.name} ({item.code})
						<button
							class="btn btn--ghost"
							type="button"
							disabled={busy}
							on:click={() => changePermission('DELETE', item.code)}
							>{$t('admin.removePermission')} {item.code}</button
						>
					</li>{/each}
			</ul>
			{#if !associationLoading && association.items.length === 0}<p>
					{$t('admin.noGroupPermissions')}
				</p>{/if}
			<button
				class="btn btn--ghost"
				type="button"
				disabled={busy || associationOffset === 0}
				on:click={() => {
					associationOffset = Math.max(0, associationOffset - 50);
					void loadAssociation();
				}}>{$t('admin.previousGroupPermissions')}</button
			>
			<button
				class="btn btn--ghost"
				type="button"
				disabled={busy || associationOffset + 50 >= association.total}
				on:click={() => {
					associationOffset += 50;
					void loadAssociation();
				}}>{$t('admin.nextGroupPermissions')}</button
			>
			<form
				class="admin-form"
				on:submit|preventDefault={() => changePermission('PUT', permissionCode)}
			>
				<label
					>{$t('admin.existingPermissionCode')}
					<input class="input" bind:value={permissionCode} required disabled={busy} /></label
				><button class="btn btn--primary" disabled={busy || !permissionCode}
					>{$t('admin.addPermission')}</button
				>
			</form>
		</section>
	{:else}
		<p class="muted">{$t('admin.selectEntry')}</p>
	{/if}
</PermissionGate>
