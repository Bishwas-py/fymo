# Journal Entry 036: Two Top-Level Keys, One Invisible Rope Between Them

**Date**: July 16, 2026
**Focus**: Folding `media:` into `storage.expose`, and why the migration doc is an error message
**Status**: Shipped

## The Misread That Named the Problem

`media:` and `storage:` sat side by side at the top of fymo.yml looking
like independent features. They never were. Every `media:` entry's `dir`
resolved through storage's root, storage was mandatory the moment a media
entry existed, and nothing in the config's shape admitted to any of it.
You learned the rope was there by tripping over it, or by reading source.

The proof it was a real problem came from a real project: someone reached
for the media section as the place to put fonts. Fonts. Files that live
in git, ship with the build, and have nothing to do with runtime storage.
The name invited exactly that misread, "media" sounds like "where media
files go", when what the section actually meant was "which storage
directories are reachable over HTTP". Those are different sentences.

## Making the Rope Structural

The fix is almost embarrassingly small once stated: if every exposure
entry already depends on storage, the config should say so by containment.

    storage:
      provider: local
      root: data
      expose:
        - prefix: /media/videos/
          dir: videos
          extensions: [webm]

The word is `expose` because it's already fymo's word for "reachable over
the wire on purpose". A remote function isn't callable until `@remote`
says so; a storage directory doesn't get a URL until an expose entry says
so. Same posture, same vocabulary. The runner-up names all lost on merit:
`routes` is taken twice already, `public` becomes a lie the day per-entry
auth lands, and `media` was the mischaracterization being retired.

Nesting also dissolved a bug class instead of guarding against it. "Media
exposed, storage unconfigured" used to be a representable state that
needed a build check and a runtime check to catch. Now the entries live
inside the section they depend on, and the only way left to write the
broken thing is a storage block with expose entries and no provider,
which fails at build and at boot with an error that says exactly that.

## No Shim, On Purpose

The tempting move was a deprecation cycle: accept both spellings for a
release, warn on the old one, delete later. I didn't, and the reasoning
deserves to be written down since it keeps recurring here. Pre-1.0, one
known consumer, and a shim means three states in the wild (old, new, and
both-at-once) plus resolution rules for the both-at-once case that someone
has to specify, test, and eventually delete. The alternative is one state
and one error:

    top-level `media:` was removed, exposure now lives under `storage.expose`.
    Move each media entry under storage: unchanged (prefix/dir/extensions
    keep their meaning).

That message fires at boot and at build, from one shared constant so the
two paths can't drift, and it is the entire migration guide. Anyone
holding the old config gets told what changed, where things went, and that
the entry bodies move byte-for-byte. A silent ignore would have been the
worst outcome by far: media routes just gone, every video 404ing, nothing
saying why.

## The 404 That Learned to Speak

One more silence got a voice while I was in there. An expose entry whose
directory doesn't exist yet used to 404 quietly on every request, which
reads as "fymo is broken" when it's really "nothing has written there
yet". Boot now warns, naming the fully resolved path it looked for. A
warning and not an error, deliberately: the whole point of storage is
that jobs create files at runtime, and a freshly deployed app whose
recording job hasn't run once is healthy, not misconfigured.

The serving code itself didn't change, and the tests prove it the honest
way: the byte-range, traversal, and symlink-escape tests moved files and
changed an import line, and their bodies stayed as they were. When a
change is supposed to be config-shape only, the diff of the security
tests is where that claim gets checked.

## What I'd Repeat

Two keys with a hidden dependency is a config smell worth fixing before
1.0, not after. And when the break is this clean, the error message can
carry the whole migration, provided it names the new home, states the
mapping, and refuses to let the old spelling mean nothing.

---

*End of Journal Entry 036*
