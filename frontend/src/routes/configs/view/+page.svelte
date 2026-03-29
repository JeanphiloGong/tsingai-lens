<script lang="ts">
  import LegacyRouteNotice from '../../_shared/LegacyRouteNotice.svelte';
</script>

<svelte:head>
  <title>Legacy Config View Route</title>
</svelte:head>

<LegacyRouteNotice
  title="Legacy Config View Route Retired"
  lead="Viewing backend config files in the browser is no longer a supported frontend feature."
  reason="This route no longer fetches raw config files from old engine endpoints. Use the current API docs for contract details instead."
/>
