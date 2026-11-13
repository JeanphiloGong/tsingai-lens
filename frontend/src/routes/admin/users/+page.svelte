<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import PermissionGate from '../../_shared/PermissionGate.svelte';
	import { permissionState, refreshPermissions } from '../../_shared/permissions';
	import { authState, clearAuthState } from '../../_shared/authState';
	import { t } from '../../_shared/i18n';
	import { requestJson, errorMessage, getApiErrorReason, isApiErrorCode } from '../../_shared/api';
	type AdminUser = { user_id: string; email: string; display_name: string; active: boolean };
	type Group = { code: string; name: string; description: string; is_system: boolean };
	type UserPage = { items: AdminUser[]; total: number; limit: number; offset: number };
	type GroupPage = { items: Group[]; total: number; limit: number; offset: number };
	let users: UserPage = { items: [], total: 0, limit: 50, offset: 0 };
	let groups: GroupPage = { items: [], total: 0, limit: 50, offset: 0 };
	let limit = 50,
		offset = 0,
		groupOffset = 0,
		selectedUserID = '',
		groupCode = '',
		error = '';
	let saved = false;
	let busy = false,
		loading = false,
		groupsLoading = false,
		mounted = false,
		subject = '',
		loadedSubject = '';
	let userGeneration = 0,
		groupGeneration = 0;
	$: currentSubject = $authState.status === 'authenticated' ? ($authState.user?.user_id ?? '') : '';
	$: canManage =
		$permissionState.status === 'ready' &&
		$permissionState.userId === currentSubject &&
		$permissionState.codes.includes('users.manage');
	$: if (currentSubject !== subject) {
		subject = currentSubject;
		loadedSubject = '';
		saved = false;
		userGeneration++;
		groupGeneration++;
		users = { items: [], total: 0, limit, offset: 0 };
		groups = { items: [], total: 0, limit: 50, offset: 0 };
		selectedUserID = '';
		groupCode = '';
		offset = 0;
		groupOffset = 0;
		error = '';
		busy = false;
		loading = false;
		groupsLoading = false;
	}
	$: if (mounted && canManage && subject && loadedSubject !== subject) {
		loadedSubject = subject;
		void loadUsers();
	}
	$: selectedUser = users.items.find((user) => user.user_id === selectedUserID);
	onMount(() => {
		mounted = true;
	});
	onDestroy(() => {
		mounted = false;
		subject = '';
		userGeneration++;
		groupGeneration++;
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

	async function loadUsers() {
		const generation = ++userGeneration,
			owner = subject;
		loading = true;
		error = '';
		try {
			const result: UserPage = await requestJson(
				`/user-api/v1/admin/users?limit=${limit}&offset=${offset}`
			);
			if (generation === userGeneration && owner === subject) users = result;
		} catch (caught) {
			if (generation === userGeneration && owner === subject) showError(caught);
		} finally {
			if (generation === userGeneration && owner === subject) loading = false;
		}
	}
	async function loadGroups() {
		const generation = ++groupGeneration,
			owner = subject,
			target = selectedUserID;
		error = '';
		if (!target) return;
		groupsLoading = true;
		try {
			const result: GroupPage = await requestJson(
				`/user-api/v1/admin/users/${encodeURIComponent(target)}/groups?limit=50&offset=${groupOffset}`
			);
			if (generation === groupGeneration && owner === subject && target === selectedUserID)
				groups = result;
		} catch (caught) {
			if (generation === groupGeneration && owner === subject && target === selectedUserID)
				showError(caught);
		} finally {
			if (generation === groupGeneration && owner === subject && target === selectedUserID)
				groupsLoading = false;
		}
	}
	function selectUser(user: AdminUser) {
		selectedUserID = user.user_id;
		groupOffset = 0;
		groupCode = '';
		groups = { items: [], total: 0, limit: 50, offset: 0 };
		void loadGroups();
	}
	function pageUsers(next: number) {
		offset = next;
		selectedUserID = '';
		groupGeneration++;
		groups = { items: [], total: 0, limit: 50, offset: 0 };
		void loadUsers();
	}
	async function updateStatus() {
		if (busy || !selectedUser) return;
		if (selectedUser.active && !window.confirm($t('admin.confirmDisable'))) return;
		const owner = subject,
			target = selectedUser.user_id;
		busy = true;
		saved = false;
		error = '';
		try {
			await requestJson(`/user-api/v1/admin/users/${encodeURIComponent(target)}/status`, {
				method: 'PATCH',
				body: JSON.stringify({ active: !selectedUser.active })
			});
			if (owner !== subject) return;
			await loadUsers();
			if (owner !== subject) return;
			await refreshPermissions();
			if (owner === subject) saved = true;
		} catch (caught) {
			if (owner === subject) showError(caught);
		} finally {
			if (owner === subject) busy = false;
		}
	}
	async function changeGroup(method: 'PUT' | 'DELETE', code: string) {
		if (busy) return;
		const owner = subject,
			target = selectedUserID;
		busy = true;
		saved = false;
		error = '';
		try {
			await requestJson(
				`/user-api/v1/admin/users/${encodeURIComponent(target)}/groups/${encodeURIComponent(code)}`,
				{ method }
			);
			if (owner !== subject || target !== selectedUserID) return;
			groupCode = '';
			groupOffset = 0;
			await loadGroups();
			if (owner !== subject) return;
			await refreshPermissions();
			if (owner === subject) saved = true;
		} catch (caught) {
			if (owner === subject) showError(caught);
		} finally {
			if (owner === subject) busy = false;
		}
	}
</script>

<svelte:head><title>{$t('admin.title')} · Lens</title></svelte:head>
<h1>{$t('admin.users')}</h1>
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
				on:change={() => pageUsers(0)}
				disabled={busy}
				><option value={2}>2</option><option value={10}>10</option><option value={50}>50</option
				><option value={200}>200</option></select
			></label
		>
		<button class="btn btn--ghost" type="button" on:click={loadUsers} disabled={busy}
			>{$t('admin.refresh')}</button
		>
		<button
			class="btn btn--ghost"
			type="button"
			disabled={busy || offset === 0}
			on:click={() => pageUsers(Math.max(0, offset - limit))}>{$t('admin.previousUsers')}</button
		>
		<button
			class="btn btn--ghost"
			type="button"
			disabled={busy || offset + limit >= users.total}
			on:click={() => pageUsers(offset + limit)}>{$t('admin.nextUsers')}</button
		>
		<span>{$t('admin.total')}: {users.total}</span>
	</div>
	<div class="table-wrap">
		<table aria-busy={loading}>
			<thead
				><tr
					><th>{$t('onboarding.email')}</th><th>{$t('admin.name')}</th><th>{$t('admin.status')}</th
					></tr
				></thead
			><tbody>
				{#each users.items as user (user.user_id)}<tr
						class:selected={user.user_id === selectedUserID}
						><td
							><button
								class="btn btn--ghost"
								type="button"
								disabled={busy}
								aria-pressed={selectedUserID === user.user_id}
								on:click={() => selectUser(user)}>{user.email}</button
							></td
						><td>{user.display_name}</td><td
							>{user.active ? $t('admin.active') : $t('admin.disabled')}</td
						></tr
					>{/each}
			</tbody>
		</table>
	</div>
	{#if !loading && users.items.length === 0}<p>
			{$t('admin.noUsers')}
		</p>{/if}
	{#if selectedUser}
		<section aria-labelledby="selected-user">
			<h2 id="selected-user">{selectedUser.email}</h2>
			<button class="btn btn--ghost" type="button" on:click={updateStatus} disabled={busy}
				>{selectedUser.active ? $t('admin.disableAccount') : $t('admin.enableAccount')}</button
			>
			<h3>{$t('admin.groupMemberships')}</h3>
			{#if groupsLoading}<p role="status">{$t('admin.loadingAssociations')}</p>{/if}
			<ul>
				{#each groups.items as group (group.code)}<li>
						{group.name} ({group.code})
						<button
							class="btn btn--ghost"
							type="button"
							disabled={busy}
							on:click={() => changeGroup('DELETE', group.code)}
							>{$t('admin.removeGroup')} {group.code}</button
						>
					</li>{/each}
			</ul>
			{#if !groupsLoading && groups.items.length === 0}<p>
					{$t('admin.noGroupMemberships')}
				</p>{/if}
			<button
				class="btn btn--ghost"
				type="button"
				disabled={busy || groupOffset === 0}
				on:click={() => {
					groupOffset = Math.max(0, groupOffset - 50);
					void loadGroups();
				}}>{$t('admin.previousMemberships')}</button
			>
			<button
				class="btn btn--ghost"
				type="button"
				disabled={busy || groupOffset + 50 >= groups.total}
				on:click={() => {
					groupOffset += 50;
					void loadGroups();
				}}>{$t('admin.nextMemberships')}</button
			>
			<form class="admin-form" on:submit|preventDefault={() => changeGroup('PUT', groupCode)}>
				<label
					>{$t('admin.existingGroupCode')}
					<input class="input" bind:value={groupCode} required disabled={busy} /></label
				><button class="btn btn--primary" disabled={busy || !groupCode}
					>{$t('admin.assignGroup')}</button
				>
			</form>
		</section>
	{:else}
		<p class="muted">{$t('admin.selectUser')}</p>
	{/if}
</PermissionGate>
