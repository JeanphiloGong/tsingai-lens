<script lang="ts">
	import './admin.css';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { authState } from '../_shared/authState';
	import { t } from '../_shared/i18n';
	import { permissionState } from '../_shared/permissions';
	import { ArrowLeft, ClipboardList, Cpu, History, Users, Layers, KeyRound, ShieldCheck } from '@lucide/svelte';

	$: permissionCodes =
		$authState.status === 'authenticated' &&
		$permissionState.status === 'ready' &&
		$permissionState.userId === $authState.user?.user_id
			? $permissionState.codes
			: [];
	$: canManageUsers = permissionCodes.includes('users.manage');
	$: canManageModels = permissionCodes.includes('models.manage');
</script>

<div class="admin-workspace">
	{#if canManageUsers || canManageModels}
		<aside class="admin-sidebar">
			<a class="admin-back" href={resolve('/')}
				><ArrowLeft size={15} aria-hidden="true" />{$t('admin.back')}</a
			>
			<h2>{$t('admin.title')}</h2>
			<nav aria-label={$t('admin.title')}>
				{#if canManageUsers}
					<a
						href={resolve('/admin/users')}
						aria-current={$page.url.pathname === '/admin/users' ? 'page' : undefined}
						><Users size={18} aria-hidden="true" />{$t('admin.users')}</a
					>
					<a
						href={resolve('/admin/groups')}
						aria-current={$page.url.pathname === '/admin/groups' ? 'page' : undefined}
						><Layers size={18} aria-hidden="true" />{$t('admin.groups')}</a
					>
					<a
						href={resolve('/admin/permissions')}
						aria-current={$page.url.pathname === '/admin/permissions' ? 'page' : undefined}
						><KeyRound size={18} aria-hidden="true" />{$t('admin.permissions')}</a
					>
				{/if}
				{#if canManageModels}
					<a
						href={resolve('/admin/models')}
						aria-current={$page.url.pathname === '/admin/models' ? 'page' : undefined}
						><Cpu size={18} aria-hidden="true" />{$t('modelAdmin.title')}</a
					>
					<a
						href={resolve('/admin/model-assignments')}
						aria-current={$page.url.pathname === '/admin/model-assignments' ? 'page' : undefined}
						><ClipboardList size={18} aria-hidden="true" />{$t('modelAssignments.title')}</a
					>
					<a
						href={resolve('/admin/model-connection-audit')}
						aria-current={$page.url.pathname === '/admin/model-connection-audit' ? 'page' : undefined}
						><History size={18} aria-hidden="true" />{$t('modelAudit.title')}</a
					>
				{/if}
			</nav>
			{#if canManageUsers}
				<p class="admin-sidebar-note">
					<ShieldCheck size={17} aria-hidden="true" />{$t('admin.accessManagement')}
				</p>
			{/if}
		</aside>
	{/if}
	<div class="admin-content"><slot /></div>
</div>
