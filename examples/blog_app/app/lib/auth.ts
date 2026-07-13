/**
 * Shared client-side auth state for the blog.
 *
 * Wraps the generated `$remote/auth` client in a Svelte store so the Nav and
 * the comment box read one source of truth. The generated client is imported
 * lazily (dynamic `import()` inside browser-only calls) so this module carries
 * no `$remote` runtime dependency during SSR — only the erased type import
 * remains at compile time.
 */
import { writable } from 'svelte/store';
import type { UserPublic } from '$remote/auth';

/** The signed-in user, or null when logged out. */
export const user = writable<UserPublic | null>(null);
/** False until the first `me()` has resolved, so UIs can avoid a flash. */
export const ready = writable(false);

const client = () => import('$remote/auth');

let started = false;

/** Resolve the current session once, on first mount. */
export async function ensureLoaded(): Promise<void> {
  if (started) return;
  started = true;
  try {
    user.set(await (await client()).me());
  } catch {
    user.set(null);
  } finally {
    ready.set(true);
  }
}

export async function login(email: string, password: string): Promise<UserPublic> {
  const u = await (await client()).login(email, password);
  user.set(u);
  return u;
}

export async function signup(email: string, password: string): Promise<UserPublic> {
  const u = await (await client()).signup(email, password);
  user.set(u);
  return u;
}

export async function logout(): Promise<void> {
  try {
    await (await client()).logout();
  } finally {
    user.set(null);
  }
}
