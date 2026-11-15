<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		Users,
		Layers,
		Plus,
		RefreshCw,
		ChevronLeft,
		ChevronRight,
		Trash2
	} from '@lucide/svelte';
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
	let assigningGroup = false;
	let groupOptions: GroupPage = { items: [], total: 0, limit: 50, offset: 0 };
	let optionOffset = 0,
		optionGeneration = 0;
	let optionsLoading = false;
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
		assigningGroup = false;
		optionGeneration++;
		optionOffset = 0;
		optionsLoading = false;
		groupOptions = { items: [], total: 0, limit: 50, offset: 0 };
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
		optionGeneration++;
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
			if (generation === userGeneration && owner === subject) {
				users = result;
				if (!users.items.some((user) => user.user_id === selectedUserID)) {
					selectedUserID = '';
					if (users.items[0]) selectUser(users.items[0]);
				}
			}
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
		saved = false;
		assigningGroup = false;
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
			assigningGroup = false;
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

	async function loadGroupOptions(next = 0) {
		optionOffset = next;
		groupCode = '';
		const request = ++optionGeneration,
			owner = subject;
		optionsLoading = true;
		try {
			const result: GroupPage = await requestJson(
				`/user-api/v1/admin/groups?limit=50&offset=${next}`
			);
			if (request === optionGeneration && owner === subject) groupOptions = result;
		} catch (caught) {
			if (request === optionGeneration && owner === subject) showError(caught);
		} finally {
			if (request === optionGeneration && owner === subject) optionsLoading = false;
		}
	}
</script>

<svelte:head><title>{$t('admin.users')} · Lens</title></svelte:head>
<PermissionGate code="users.manage">
	<header class="admin-page-header">
		<div>
			<h1>{$t('admin.users')}</h1>
			<p>{$t('admin.usersDescription')}</p>
		</div>
		<button
			class="btn btn--ghost admin-icon-button"
			type="button"
			aria-label={$t('admin.refresh')}
			title={$t('admin.refresh')}
			disabled={busy || loading}
			on:click={loadUsers}><RefreshCw size={16} aria-hidden="true" /></button
		>
	</header>
	{#if saved}<p class="status admin-success" role="status">{$t('admin.saved')}</p>{/if}
	{#if error}<p class="status status--error" role="alert">{error}</p>{/if}
	{#if loading}<p class="status" role="status">{$t('admin.loading')}</p>{/if}
	<div class="admin-user-layout">
		<section class="admin-panel" aria-label={$t('admin.allUsers')}>
			<div class="admin-panel-header">
				<h2>{$t('admin.allUsers')}</h2>
				<span class="admin-count">{$t('admin.total')}: {users.total}</span>
			</div>
			<div class="admin-table-wrap">
				<table class="admin-users-table" aria-busy={loading}>
					<thead
						><tr
							><th>{$t('admin.name')}</th><th>{$t('admin.status')}</th><th>{$t('admin.actions')}</th
							></tr
						></thead
					><tbody>
						{#each users.items as user (user.user_id)}<tr
								class:selected={user.user_id === selectedUserID}
								><td
									><div class="admin-person">
										<span class="admin-avatar" aria-hidden="true"
											>{(user.display_name || user.email).slice(0, 1).toUpperCase()}</span
										>
										<div>
											<strong>{user.display_name || user.email}</strong><small>{user.email}</small>
										</div>
									</div></td
								><td
									><span class="admin-badge" class:admin-badge--active={user.active}
										><span class="admin-status-dot" aria-hidden="true"></span>{user.active
											? $t('admin.active')
											: $t('admin.disabled')}</span
									></td
								><td
									><button
										class="admin-text-button"
										type="button"
										disabled={busy || loading}
										aria-label={$t('admin.manageUser', { name: user.display_name || user.email })}
										aria-pressed={selectedUserID === user.user_id}
										on:click={() => selectUser(user)}>{$t('admin.manageAccess')}</button
									></td
								></tr
							>{/each}
					</tbody>
				</table>
			</div>
			{#if !loading && !users.items.length}<div class="admin-empty">
					<Users size={26} aria-hidden="true" />
					<p>{$t('admin.noUsers')}</p>
				</div>{/if}
			<footer class="admin-pagination">
				<span
					>{$t('admin.pageRange', {
						start: users.items.length ? offset + 1 : 0,
						end: offset + users.items.length,
						total: users.total
					})}</span
				>
				<div class="admin-pagination-controls">
					<label class="admin-page-label"
						>{$t('admin.pageSize')}<select
							class="input"
							aria-label={$t('admin.pageSize')}
							bind:value={limit}
							on:change={() => pageUsers(0)}
							disabled={busy || loading}
							><option value={2}>2</option><option value={10}>10</option><option value={50}
								>50</option
							><option value={200}>200</option></select
						></label
					><button
						class="btn btn--ghost"
						type="button"
						aria-label={$t('admin.previousUsers')}
						disabled={busy || loading || offset === 0}
						on:click={() => pageUsers(Math.max(0, offset - limit))}
						><ChevronLeft size={15} aria-hidden="true" /></button
					><button
						class="btn btn--ghost"
						type="button"
						aria-label={$t('admin.nextUsers')}
						disabled={busy || loading || offset + limit >= users.total}
						on:click={() => pageUsers(offset + limit)}
						><ChevronRight size={15} aria-hidden="true" /></button
					>
				</div>
			</footer>
		</section>
		{#if selectedUser}
			<section class="admin-panel admin-user-detail" aria-labelledby="selected-user-heading">
				<header class="admin-detail-heading">
					<div class="admin-detail-title">
						<span class="admin-avatar" aria-hidden="true"
							>{(selectedUser.display_name || selectedUser.email).slice(0, 1).toUpperCase()}</span
						>
						<div>
							<h2 id="selected-user-heading">{selectedUser.display_name || selectedUser.email}</h2>
							<span class="admin-code">{selectedUser.email}</span>
						</div>
					</div>
				</header>
				<div class="admin-detail-body">
					<dl class="admin-user-data">
						<div>
							<dt>{$t('admin.userId')}</dt>
							<dd class="admin-code">{selectedUser.user_id}</dd>
						</div>
						<div>
							<dt>{$t('admin.status')}</dt>
							<dd>
								<span class="admin-badge" class:admin-badge--active={selectedUser.active}
									><span class="admin-status-dot" aria-hidden="true"></span>{selectedUser.active
										? $t('admin.active')
										: $t('admin.disabled')}</span
								>
							</dd>
						</div>
					</dl>
					<div>
						<div class="admin-section-heading">
							<h3>{$t('admin.groupMemberships')}</h3>
							<span class="admin-count">{groupsLoading ? '…' : groups.total}</span>
						</div>
						{#if groupsLoading}<p class="admin-help" role="status">
								{$t('admin.loadingAssociations')}
							</p>{/if}
						<ul class="admin-associations" aria-busy={groupsLoading}>
							{#each groups.items as group (group.code)}<li>
									<span class="admin-symbol"><Layers size={16} aria-hidden="true" /></span>
									<div class="admin-association-content">
										<strong>{group.name}</strong><span class="admin-code">{group.code}</span>
									</div>
									<button
										class="admin-text-button admin-remove"
										type="button"
										disabled={busy || groupsLoading}
										aria-label={`${$t('admin.removeGroup')} ${group.code}`}
										on:click={() => changeGroup('DELETE', group.code)}>{$t('admin.remove')}</button
									>
								</li>{/each}
						</ul>
						{#if !groupsLoading && !groups.items.length}<p class="admin-context-note">
								{$t('admin.noGroupMemberships')}
							</p>{/if}
						{#if groups.total > 50}<div class="admin-pagination admin-association-pagination">
								<span>{$t('admin.total')}: {groups.total}</span>
								<div class="admin-pagination-controls">
									<button
										class="btn btn--ghost"
										type="button"
										aria-label={$t('admin.previousMemberships')}
										disabled={busy || groupsLoading || groupOffset === 0}
										on:click={() => {
											groupOffset = Math.max(0, groupOffset - 50);
											void loadGroups();
										}}><ChevronLeft size={15} aria-hidden="true" /></button
									><button
										class="btn btn--ghost"
										type="button"
										aria-label={$t('admin.nextMemberships')}
										disabled={busy || groupsLoading || groupOffset + 50 >= groups.total}
										on:click={() => {
											groupOffset += 50;
											void loadGroups();
										}}><ChevronRight size={15} aria-hidden="true" /></button
									>
								</div>
							</div>{/if}
						{#if assigningGroup}<form
								class="admin-form admin-picker"
								on:submit|preventDefault={() => changeGroup('PUT', groupCode)}
							>
								<label
									>{$t('admin.existingGroupCode')}<select
										class="input"
										aria-label={$t('admin.existingGroupCode')}
										bind:value={groupCode}
										disabled={busy || optionsLoading}
										required
										><option value="">{$t('admin.chooseGroup')}</option
										>{#each groupOptions.items as group (group.code)}<option value={group.code}
												>{group.name} ({group.code})</option
											>{/each}</select
									></label
								>
								{#if optionsLoading}<p class="admin-help" role="status">
										{$t('admin.loading')}
									</p>{/if}
								<div class="admin-pagination">
									<span>{$t('admin.total')}: {groupOptions.total}</span>
									<div class="admin-pagination-controls">
										<button
											class="btn btn--ghost"
											type="button"
											aria-label={$t('admin.previousOptions')}
											disabled={busy || optionsLoading || optionOffset === 0}
											on:click={() => loadGroupOptions(Math.max(0, optionOffset - 50))}
											><ChevronLeft size={15} aria-hidden="true" /></button
										><button
											class="btn btn--ghost"
											type="button"
											aria-label={$t('admin.nextOptions')}
											disabled={busy || optionsLoading || optionOffset + 50 >= groupOptions.total}
											on:click={() => loadGroupOptions(optionOffset + 50)}
											><ChevronRight size={15} aria-hidden="true" /></button
										>
									</div>
								</div>
								<div class="admin-form-actions">
									<button
										class="btn btn--ghost"
										type="button"
										disabled={busy}
										on:click={() => (assigningGroup = false)}>{$t('admin.cancel')}</button
									><button class="btn btn--primary" disabled={busy || optionsLoading || !groupCode}
										>{$t('admin.assignGroup')}</button
									>
								</div>
							</form>
						{:else}<button
								class="admin-text-button"
								type="button"
								disabled={busy}
								aria-expanded="false"
								on:click={() => {
									assigningGroup = true;
									void loadGroupOptions();
								}}><Plus size={15} aria-hidden="true" />{$t('admin.assignGroup')}</button
							>{/if}
					</div>
				</div>
				<footer class="admin-detail-footer">
					<button
						class="btn"
						class:admin-danger={selectedUser.active}
						class:btn--ghost={!selectedUser.active}
						type="button"
						disabled={busy}
						on:click={updateStatus}
						>{#if selectedUser.active}<Trash2
								size={15}
								aria-hidden="true"
							/>{/if}{selectedUser.active
							? $t('admin.disableAccount')
							: $t('admin.enableAccount')}</button
					>
				</footer>
			</section>
		{:else}<section class="admin-panel admin-empty">
				<Users size={26} aria-hidden="true" />
				<h2>{$t('admin.users')}</h2>
				<p>{$t('admin.selectUser')}</p>
			</section>{/if}
	</div>
</PermissionGate>
