<script lang="ts">
  import LegacyRouteNotice from '../../_shared/LegacyRouteNotice.svelte';
</script>

<svelte:head>
  <title>Legacy Config Upload Route</title>
</svelte:head>

<LegacyRouteNotice
  title="Legacy Config Upload Route Retired"
  lead="Uploading backend config files from the browser is not supported in the current frontend contract."
  reason="This route no longer posts to old config upload endpoints. Use /api/docs if you need backend reference material."
/>
