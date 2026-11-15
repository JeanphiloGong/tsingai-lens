<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { onDestroy, onMount } from 'svelte';
	import { changePassword } from '../_shared/auth';
	import { authState } from '../_shared/authState';
	import { errorMessage, isApiErrorCode } from '../_shared/api';
	import { t } from '../_shared/i18n';

	let oldPassword = '';
	let password = '';
	let confirmPassword = '';
	let error = '';
	let busy = false;
	let active = true;
	let ready = false;
	onMount(() => {
		ready = true;
	});

	onDestroy(() => {
		active = false;
		oldPassword = password = confirmPassword = '';
	});

	async function submitForm() {
		if (password !== confirmPassword) {
			error = $t('onboarding.passwordMismatch');
			return;
		}
		busy = true;
		error = '';
		try {
			await changePassword(oldPassword, password);
			if (!active) return;
			oldPassword = password = confirmPassword = '';
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- The route helper resolves its pathname before adding query parameters.
			await goto(`${resolve('/login')}?passwordChanged=1`, { replaceState: true });
		} catch (caughtError) {
			if (!active) return;
			error = isApiErrorCode(caughtError, 200301)
				? $t('onboarding.currentPasswordError')
				: errorMessage(caughtError);
		} finally {
			if (active) busy = false;
		}
	}
</script>

<svelte:head><title>{$t('onboarding.account')} - Lens</title></svelte:head>
<section class="card account-panel" aria-labelledby="account-title">
	<h1 id="account-title">{$t('onboarding.account')}</h1>
	<p class="account-notice">{$t('onboarding.changeNotice')}</p>
	<form class="account-form" on:submit|preventDefault={submitForm}>
		<label class="field">
			<span>{$t('onboarding.currentPassword')}</span>
			<input
				class="input"
				type="password"
				autocomplete="current-password"
				bind:value={oldPassword}
				disabled={!ready || busy}
				required
			/>
		</label>
		<label class="field">
			<span>{$t('onboarding.password')}</span>
			<input
				class="input"
				type="password"
				autocomplete="new-password"
				minlength="12"
				maxlength="256"
				bind:value={password}
				disabled={!ready || busy}
				required
			/>
		</label>
		<label class="field">
			<span>{$t('onboarding.confirmPassword')}</span>
			<input
				class="input"
				type="password"
				autocomplete="new-password"
				bind:value={confirmPassword}
				disabled={!ready || busy}
				required
			/>
		</label>
		{#if error}<p class="status status--error" role="alert">{error}</p>{/if}
		<button
			class="btn btn--primary"
			type="submit"
			disabled={busy || $authState.status !== 'authenticated'}
		>
			{busy ? $t('onboarding.waiting') : $t('onboarding.changePassword')}
		</button>
	</form>
</section>
