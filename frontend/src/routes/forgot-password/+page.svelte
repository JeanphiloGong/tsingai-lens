<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { issueEmailChallenge, resetPassword } from '../_shared/auth';
	import { errorMessage, getApiErrorData, isApiErrorCode } from '../_shared/api';
	import { language, t } from '../_shared/i18n';
	let email = '';
	let verificationCode = '';
	let password = '';
	let confirmPassword = '';
	let active = true;
	let ready = false;
	let emailInput: HTMLInputElement;
	let challengeId = '';
	let challengeEmail = '';
	let busy = false;
	let error = '';
	let sent = false;
	let now = Date.now();
	let retryAt = 0;
	$: remainingSeconds = Math.max(0, Math.ceil((retryAt - now) / 1000));
	$: if (email !== challengeEmail) {
		challengeId = '';
		verificationCode = '';
		sent = false;
	}
	onDestroy(() => {
		active = false;
		password = confirmPassword = verificationCode = challengeId = '';
	});
	onMount(() => {
		ready = true;
		const timer = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(timer);
	});
	function showError(value: unknown) {
		error = isApiErrorCode(value, 200203) ? $t('onboarding.unavailable') : errorMessage(value);
		const data = getApiErrorData(value) as { retry_after?: number } | null;
		if (data?.retry_after) retryAt = Date.now() + data.retry_after * 1000;
	}
	async function sendCode() {
		if (!emailInput.reportValidity()) return;
		busy = true;
		error = '';
		const requestedEmail = email;
		try {
			const result = await issueEmailChallenge(requestedEmail, 'password_reset');
			if (!active || requestedEmail !== email) return;
			challengeEmail = requestedEmail;
			challengeId = result.challenge_id;
			sent = true;
			verificationCode = '';
			retryAt = Date.now() + result.retry_after * 1000;
			now = Date.now();
		} catch (caughtError) {
			if (active) showError(caughtError);
		} finally {
			if (active) busy = false;
		}
	}
	async function submitForm() {
		if (password !== confirmPassword) {
			error = $t('onboarding.passwordMismatch');
			return;
		}
		busy = true;
		error = '';
		try {
			await resetPassword({ email, challenge_id: challengeId, code: verificationCode, password });
			if (!active) return;
			password = confirmPassword = '';
			verificationCode = '';
			challengeId = '';
			await goto('/login?passwordReset=1');
		} catch (caughtError) {
			if (active) showError(caughtError);
		} finally {
			if (active) busy = false;
		}
	}
</script>

<svelte:head><title>{$t('onboarding.recover')}</title></svelte:head>
<section class="login-shell" aria-labelledby="onboarding-title">
	<div class="login-panel">
		<img class="login-mark" src="/lens-mark-a2.svg" alt="" />
		<h1 id="onboarding-title">{$t('onboarding.recover')}</h1>
		<p class="account-notice">{$t('onboarding.legacy')}</p>
		<form class="login-form account-form" on:submit|preventDefault={submitForm}>
			<label class="field"
				><span>{$t('onboarding.email')}</span><input
					class="input"
					type="email"
					bind:this={emailInput}
					autocomplete="username"
					bind:value={email}
					disabled={!ready || busy}
					required
				/></label
			>
			<button
				class="btn code-button"
				type="button"
				on:click={sendCode}
				disabled={!ready || busy || !email.trim() || remainingSeconds > 0}
				>{$t('onboarding.send')}{remainingSeconds > 0 ? ` (${remainingSeconds}s)` : ''}</button
			>
			{#if sent}<p class="account-notice" role="status">{$t('onboarding.sent')}</p>{/if}
			<label class="field"
				><span>{$t('onboarding.code')}</span><input
					class="input"
					inputmode="numeric"
					pattern={'[0-9]{6}'}
					autocomplete="one-time-code"
					bind:value={verificationCode}
					minlength="6"
					maxlength="6"
					disabled={!ready || busy}
					required
				/></label
			>

			<label class="field"
				><span>{$t('onboarding.password')}</span><input
					class="input"
					type="password"
					autocomplete="new-password"
					bind:value={password}
					minlength="12"
					maxlength="256"
					disabled={!ready || busy}
					required
				/></label
			>
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
				disabled={!ready ||
					busy ||
					!challengeId ||
					verificationCode.length !== 6 ||
					password.length < 12}>{busy ? $t('onboarding.waiting') : $t('onboarding.recover')}</button
			>
		</form>
		<nav class="account-links" aria-label={$t('onboarding.navigation')}>
			<a href="/login">{$t('onboarding.back')}</a>
		</nav>
	</div>
	<label class="login-language">
		<span>{$t('header.languageLabel')}</span>
		<select
			disabled={!ready}
			value={$language}
			on:change={(event) => language.set(event.currentTarget.value as 'en' | 'zh')}
			><option value="en">English</option><option value="zh">简体中文</option></select
		>
	</label>
</section>
