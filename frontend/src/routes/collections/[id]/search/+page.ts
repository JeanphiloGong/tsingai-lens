import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ params, url }) => {
  const search = url.search ? url.search : '';
  throw redirect(307, `/collections/${params.id}/steps${search}`);
};
