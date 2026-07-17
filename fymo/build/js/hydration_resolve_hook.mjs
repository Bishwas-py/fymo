// Module-resolution hook for hydration_check.mjs.
//
// esbuild's publicPath (see build.mjs's client pass) makes code-splitting
// chunk imports browser-absolute ("/dist/client/chunk-x.HASH.js"), which a
// real browser resolves against the origin fymo serves /dist/ from. Node's
// own ESM loader instead treats that as an absolute filesystem path and
// fails, so this hook applies the same mapping the harness already does
// for the entry script's src: anchor the "/dist/..." specifier to the real
// dist directory the importing module itself lives under. Scoped to
// parents under a dist/ directory so nothing else in the process changes.
export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('/dist/') && context.parentURL) {
    const idx = context.parentURL.lastIndexOf('/dist/');
    if (idx !== -1) {
      return {
        url: context.parentURL.slice(0, idx) + specifier,
        shortCircuit: true,
      };
    }
  }
  return nextResolve(specifier, context);
}
