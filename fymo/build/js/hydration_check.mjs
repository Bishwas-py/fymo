// Real-hydration regression check: loads a live page's actual SSR HTML into
// jsdom, then executes the actual compiled client bundle against it the same
// way a real browser would -- letting Svelte's real hydrate() run against
// real DOM APIs -- and reports any console errors/warnings raised.
//
// This exists because every hydration bug found in this codebase so far
// (the dev_orchestrator layout-fields bug, and the SSR/shell static-vs-
// dynamic component-tag bug) was invisible to the existing test suite: all
// of it talks to the WSGI app directly and asserts on HTML strings, which
// proves the server produced *some* markup but proves nothing about whether
// a browser can hydrate it. jsdom is not a full browser (no real layout/
// paint), but it runs the real Svelte runtime's real hydrate() call against
// real DOM APIs, which is exactly where both prior bugs actually fired --
// so it closes that blind spot without pulling in a full browser-automation
// dependency (Playwright et al.).
//
// jsdom cannot execute `<script type="module">` tags at all (a longstanding,
// documented jsdom limitation -- it does not implement the module
// resolution/linking algorithm), which every fymo client bootstrap uses. So
// instead of letting jsdom auto-run scripts, this script parses the HTML
// with script execution disabled, finds the module script's `src`, maps it
// to the real file already sitting in `<distDir>/client/...` on disk, and
// `import()`s that file directly through Node's own ESM loader (so its
// relative sibling-chunk imports resolve normally on the real filesystem),
// with jsdom's `window`/`document` installed as ambient globals so the
// bundle's browser-assuming top-level code (`document.getElementById(...)`,
// etc.) works exactly as it would in a real page.
//
// CLI usage: node hydration_check.mjs <url> <distDir> [timeoutMs]
// Prints one JSON line: {"ok": bool, "errors": [...], "warnings": [...]}
//
// Also importable as a library (`import { checkHydration } from
// './hydration_check.mjs'`) for callers that want to check more than one
// route without paying subprocess-startup cost per route. checkHydration is
// safe to call more than once in the same process: every global it touches
// on `globalThis` is either a fresh addition (deleted afterward) or a
// pre-existing value it saves and restores explicitly (see DOM_OVERRIDES
// below) -- nothing leaks into the next call or the rest of the process.

import { JSDOM } from 'jsdom';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

/**
 * @param {string} url page URL to fetch and hydrate
 * @param {string} distDir local filesystem path to the app's dist/ directory
 * @param {number} [timeoutMs]
 * @param {{afterBoot?: (window: object, ctx: {localPath: string}) => Promise<void>}} [opts]
 *   afterBoot, when given, runs after a clean boot and before jsdom teardown
 *   -- window/document/globalThis are still the real, hydrated page, so a
 *   caller can drive further interaction (e.g. call an exported function
 *   from the same already-imported bundle, then assert on real DOM state)
 *   without reimplementing this file's boot/global-patching dance. Anything
 *   it throws is folded into `errors` rather than crashing the check.
 * @returns {Promise<{ok: boolean, errors: string[], warnings: string[]}>}
 */
export async function checkHydration(url, distDir, timeoutMs = 5000, { afterBoot } = {}) {
  const errors = [];
  const warnings = [];

  const res = await fetch(url);
  const html = await res.text();

  // runScripts is intentionally omitted (scripts never auto-execute) --
  // we run the module bundle ourselves below.
  const dom = new JSDOM(html, { url, resources: 'usable', pretendToBeVisual: true });
  const { window } = dom;

  const moduleScript = window.document.querySelector('script[type="module"][src]');
  if (!moduleScript) {
    window.close();
    return { ok: false, errors: [`no <script type="module"> found in ${url}`], warnings: [] };
  }

  // The src is an absolute path like "/dist/client/posts.HASH.js" -- fymo
  // serves everything under distDir's parent at that same "/dist/..."
  // prefix, so strip the leading "/dist" segment and resolve what remains
  // against the real distDir on disk.
  const srcPath = moduleScript.getAttribute('src');
  const relPath = srcPath.replace(/^\/dist\//, '');
  const localPath = path.join(distDir, relPath);

  // Install browser globals the bundle's top-level code assumes exist.
  // Svelte's internals reference a broad set of DOM classes/constructors
  // (Element, Comment, Text, Node, Event, ...) directly as globals, not
  // just `window`/`document` -- copy every own property jsdom exposes on
  // `window`, mirroring what `jsdom-global`-style shims do, rather than
  // hand-picking a subset that will keep needing new entries as Svelte's
  // internals evolve. Restored after so a second call in this same process
  // (or anything else running here) never sees this call's globals.
  const previousKeys = new Set(Object.getOwnPropertyNames(globalThis));

  // The bundle references the ambient `console` identifier, which resolves
  // to globalThis.console -- Node's own console object, not jsdom's
  // window.console (a distinct object). `console` already exists on
  // globalThis, so the copy loop below (which skips anything already
  // present) never touches it; patch Node's real console directly instead,
  // and restore the original methods afterward.
  const originalConsoleError = console.error;
  const originalConsoleWarn = console.warn;
  console.error = (...args) => errors.push(args.map(String).join(' '));
  console.warn = (...args) => warnings.push(args.map(String).join(' '));

  // Node.js has its own native, spec-compliant implementations of several
  // Web-standard classes (Event, EventTarget, CustomEvent, AbortController,
  // ...) -- but they are a SEPARATE class hierarchy from jsdom's own DOM
  // implementation. Every jsdom-created node (an Element, a real DOM event
  // dispatched by `dispatchEvent`, ...) is an instance of *jsdom's*
  // EventTarget/Event, not Node's. The generic "skip if already in
  // globalThis" rule below would leave Node's version in place for these
  // names, silently breaking any `instanceof Event`/`instanceof
  // EventTarget` check the bundle's code (or Svelte's own internals) makes
  // against a real jsdom object. Force jsdom's version to win for exactly
  // this set of overlapping DOM/Web-standard names; nothing else Node
  // predefines (Object, Array, Promise, process, setTimeout, ...) belongs
  // on this list, since those aren't part of the DOM object graph the
  // bundle under test walks.
  const DOM_OVERRIDES = new Set([
    'Event', 'EventTarget', 'CustomEvent', 'MessageEvent', 'ErrorEvent',
    'ProgressEvent', 'AbortController', 'AbortSignal',
  ]);
  // Unlike the generic copy loop below (which only ever ADDS keys that
  // weren't on globalThis before, and so can be undone by just deleting
  // them), these names already exist on Node's globalThis -- overriding
  // them REPLACES a value that must come back afterward, or Node's own
  // Event/EventTarget would stay silently swapped out for jsdom's version
  // for the rest of this process, corrupting every check after this call
  // (including a second route checked via a second checkHydration() call).
  const previousDomOverrideValues = new Map();
  for (const key of DOM_OVERRIDES) {
    if (key in window) {
      previousDomOverrideValues.set(key, globalThis[key]);
      globalThis[key] = window[key];
    }
  }

  for (const key of Object.getOwnPropertyNames(window)) {
    if (key === 'window' || key === 'self' || key === 'top' || key === 'parent') continue;
    if (DOM_OVERRIDES.has(key)) continue; // already force-copied above
    // Skip anything else Node already provides globally (Object, Array,
    // Promise, Symbol, JSON, Math, process, setTimeout, ...). These exist
    // in both environments; overwriting Node's own copies -- especially by
    // binding constructors like `Object` to `window`, which silently
    // strips their static methods -- corrupts the process's own JS
    // runtime, not just the page under test. Only DOM-only globals Node
    // lacks (Element, Document, HTMLElement, ...) get copied.
    if (key in globalThis) continue;
    try {
      const value = window[key];
      // Methods (addEventListener, requestAnimationFrame, ...) must stay
      // bound to `window` -- calling them unbound breaks jsdom's internal
      // `this`-based bookkeeping. Constructors (Node, Element, Event, ...)
      // must NOT be bound -- `Function.prototype.bind` returns a wrapper
      // with no `.prototype` of its own, which silently breaks every
      // `SomeClass.prototype` access (observed: Svelte's internals reading
      // `Node.prototype` to grab property descriptors, getting `undefined`
      // back once `Node` was a bound wrapper). DOM/JS convention is that
      // constructors are PascalCase and methods are camelCase, which is a
      // reliable enough signal here (this is test tooling, not shipped
      // code) to tell the two apart without a large explicit allow-list.
      const isConstructor = typeof value === 'function' && /^[A-Z]/.test(key);
      globalThis[key] = typeof value === 'function' && !isConstructor ? value.bind(window) : value;
    } catch {
      // Some window properties (e.g. certain getters) can't be copied as
      // plain assignments -- safe to skip, they're not things Svelte's
      // internals reference as bare identifiers.
    }
  }
  globalThis.window = window;
  globalThis.document = window.document;

  window.addEventListener('error', (e) => errors.push(`window error: ${e.message}`));
  window.addEventListener('unhandledrejection', (e) => {
    errors.push(`unhandled rejection: ${(e.reason && e.reason.message) || e.reason}`);
  });

  try {
    await import(pathToFileURL(localPath).href);
  } catch (e) {
    errors.push(`bundle import threw: ${e && (e.stack || e.message || e)}`);
  }

  const deadline = Date.now() + timeoutMs;
  while (!window.__fymoBooted && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 25));
  }
  // Let any microtask-queued console output (e.g. <svelte:boundary>'s
  // onerror, which Svelte defers) flush after boot.
  await new Promise((r) => setTimeout(r, 100));

  const booted = !!window.__fymoBooted;
  if (!booted) errors.push(`client bundle never set window.__fymoBooted within ${timeoutMs}ms`);

  if (booted && afterBoot) {
    try {
      await afterBoot(window, { localPath });
    } catch (e) {
      errors.push(`afterBoot hook threw: ${e && (e.stack || e.message || e)}`);
    }
  }

  console.error = originalConsoleError;
  console.warn = originalConsoleWarn;
  window.close();
  // The generic copy loop only ever ADDS keys that weren't on globalThis
  // before, so undoing it is just deleting those additions -- no
  // pre-existing global's value was ever touched there. The DOM_OVERRIDES
  // are the one exception (see above): they replaced a real prior value,
  // so they need an explicit write-back, not a delete.
  for (const key of Object.getOwnPropertyNames(globalThis)) {
    if (!previousKeys.has(key)) {
      try { delete globalThis[key]; } catch { /* non-configurable, leave it */ }
    }
  }
  for (const [key, value] of previousDomOverrideValues) {
    globalThis[key] = value;
  }

  return { ok: errors.length === 0 && booted, errors, warnings };
}

// CLI entrypoint -- only runs when this file is executed directly (`node
// hydration_check.mjs ...`), not when imported by another module (e.g. a
// test harness calling checkHydration() directly).
if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const url = process.argv[2];
  const distDir = process.argv[3];
  const timeoutMs = Number(process.argv[4] ?? 5000);

  if (!url || !distDir) {
    console.error('usage: node hydration_check.mjs <url> <distDir> [timeoutMs]');
    process.exit(2);
  }

  checkHydration(url, distDir, timeoutMs)
    .then((result) => {
      console.log(JSON.stringify(result));
      process.exit(result.ok ? 0 : 1);
    })
    .catch((e) => {
      console.log(JSON.stringify({ ok: false, errors: [`checker crashed: ${e && (e.stack || e.message)}`], warnings: [] }));
      process.exit(1);
    });
}
