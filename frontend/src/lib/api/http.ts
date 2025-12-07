import { PUBLIC_API_BASE } from '$env/static/public';

// 统一的 API 基础地址
export const apiBase = (PUBLIC_API_BASE || 'http://localhost:8010').replace(/\/$/, '');

// 通用响应处理
export async function handle<T>(res: Response): Promise<T> {
  const isJson = (res.headers.get('Content-Type') || '').includes('application/json');
  const payload = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = isJson && (payload as any)?.detail ? (payload as any).detail : res.statusText;
    throw new Error(detail || '请求失败');
  }
  return payload as T;
}
