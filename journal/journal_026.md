# Journal Entry 026: The Diff That Wanted to Drop the Queue

**Date**: July 16, 2026
**Focus**: fymo schema provider-tables, and who owns what in a shared database
**Status**: Shipped

## The Plan I Almost Applied

A declarative schema diff against a real database produced a plan that
was, line by line, a demolition order for the job queue. DROP TABLE
procrastinate_jobs. DROP TABLE procrastinate_events. DROP FUNCTION,
DROP TYPE, all of it. The tool wasn't wrong, it was doing exactly its
job: diff the database against the schema file, and the schema file only
declares what the app owns. Nobody told it that fymo's job provider had
quietly moved furniture into the same schema. I caught it by reading the
plan before applying it, which is luck wearing the costume of process.

The gap wasn't in the schema tool and it wasn't really in procrastinate
either. It was that fymo's providers create real, permanent database
objects and offer no way for anything outside fymo to ask which ones.

## Deriving Instead of Declaring

The obvious fix is a documented list: procrastinate creates these four
tables, these types, done. I wrote that list out and then deleted it,
because a hardcoded list is a lie with a delay on it. Procrastinate
upgrades, adds a table or a function version suffix, and the list keeps
confidently naming last year's objects while the diff tool eyes the new
ones.

It turns out procrastinate ships its own answer: the package bundles the
exact SQL it applies, exposed programmatically, no database connection
required. So the provider now derives its declaration by parsing that
bundled DDL. Whatever version is installed is whatever gets enumerated,
and the two cannot drift apart because there is only one source.

The parser has one rule I care about more than any feature: if it meets
a CREATE statement it can't classify, it raises. A partial list is worse
than no list, because the whole point is feeding an exclude list to a
tool that deletes what isn't mentioned.

Two details earned their place the hard way. Tables with bigserial or
identity columns create sequences nobody wrote a CREATE SEQUENCE for,
and a schema tool that enumerates sequences will happily propose
dropping procrastinate_jobs_id_seq even if the table itself is excluded,
so the parser surfaces those too. And every Postgres table secretly
registers a row type in pg_type, which briefly made my catalog
cross-check claim the output was missing four types before I understood
the catalog was the one padding the count.

## The Seam

Each provider base class now answers owned_schema_objects(), default
empty. Procrastinate overrides it. The threaded job provider owns
nothing, honestly. The postgres broadcast provider, which the issue
half-suspected of the same crime, turns out to be innocent: pure
LISTEN/NOTIFY, not a single table, and saying so explicitly in a test
felt better than leaving it implied.

I deliberately kept the method off the provider Protocols. They're
runtime-checkable, and existing custom providers written before this
seam would suddenly fail isinstance checks over a feature they never
asked for. The CLI reaches through a small duck-typed helper instead,
which also means anything that isn't a job or broadcast provider, say a
user store that creates its own tables someday, can join by defining the
same method.

The command itself is `fymo schema provider-tables`, a group with one
subcommand, because the issue's third wish (schema fragments an app can
import) will want the same roof eventually. Plain output is one
kind-prefixed name per line, --json for tooling, stdout kept pure so it
pipes, notes and errors on stderr. Configured but uninstalled
procrastinate exits 1 naming the extra, never printing half a list.

## Proof Against a Real Catalog

The acceptance test I trust most applied procrastinate's schema to a
throwaway Postgres and diffed the actual catalog against the command's
output: tables, functions, types, sequences equal exactly, triggers and
explicit indexes accounted for, constraint-backed indexes left to their
tables. The enumeration and reality agree on every one of the forty-five
objects. The next diff plan that wants to drop the queue will have to
get past a generated exclude list instead of my reading comprehension.

---

*End of Journal Entry 026*
