import { apiBase, handle } from './http';

// 健康检查
export async function healthCheck() {
  return handle<{ status: string }>(await fetch(`${apiBase}/graph/health`));
}
