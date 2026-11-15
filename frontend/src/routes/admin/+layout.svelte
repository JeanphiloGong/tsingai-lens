<script lang="ts">
	import './admin.css';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { authState } from '../_shared/authState';
	import { t } from '../_shared/i18n';
	import { permissionState } from '../_shared/permissions';
	import { ArrowLeft, Users, Layers, KeyRound, ShieldCheck } from '@lucide/svelte';
</script>

<div class="admin-workspace">
	{#if $authState.status === 'authenticated' && $permissionState.userId === $authState.user?.user_id && $permissionState.codes.includes('users.manage')}
		<aside class="admin-sidebar">
			<a class="admin-back" href={resolve('/')}
				><ArrowLeft size={15} aria-hidden="true" />{$t('admin.back')}</a
			>
			<h2>{$t('admin.title')}</h2>
			<nav aria-label={$t('admin.title')}>
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
			</nav>
			<p class="admin-sidebar-note">
				<ShieldCheck size={17} aria-hidden="true" />{$t('admin.accessManagement')}
			</p>
		</aside>
	{/if}
	<div class="admin-content"><slot /></div>
</div>
