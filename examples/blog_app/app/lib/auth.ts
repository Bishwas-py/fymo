/**
 * Shared client-side auth state for the blog.
 *
 * Wraps the app-owned auth endpoints (app/remote/auth.py, scaffolded by
 * `fymo generate auth` and edited freely) in a Svelte store so the Nav and
 * the comment box read one source of truth. The generated $remote client is
 * imported lazily (dynamic `import()` inside browser-only calls) so this
 * module carries no `$remote` runtime dependency during SSR.
 */
import { writable } from 'svelte/store';

/** The whitelisted subset me() returns; see app/remote/auth.py. */
export interface UserPublic {
  uid: string;
  email: string;
  created_at?: string;
}

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
    user.set(((await (await client()).me()) as UserPublic | null) ?? null);
  } catch {
    user.set(null);
  } finally {
    ready.set(true);
  }
}

/**
 * Server-driven flow: on success the login endpoint answers with a redirect
 * envelope and the $remote client navigates (back to the current page), so
 * the reloaded page sees the session cookie. On bad credentials it throws.
 */
export async function login(email: string, password: string): Promise<void> {
  const next = window.location.pathname + window.location.search;
  await (await client()).login(email, password, next);
}

export async function signup(email: string, password: string): Promise<UserPublic> {
  const u = (await (await client()).signup(email, password)) as UserPublic;
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
