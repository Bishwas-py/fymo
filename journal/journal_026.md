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

My first version of that rule was a lie, and review caught it cold. I
anchored the scan to CREATE at the start of a line, which reads as a
tidy simplification and is actually a silent-skip mechanism: a CREATE
tucked inside a DO block, or a second CREATE sharing a line, just never
existed as far as the parser was concerned. Worse, the proof was already
sitting in procrastinate's real schema, which opens with an indented
CREATE EXTENSION inside a DO block that my parser walked straight past
while its tests glowed green, because the drift guard used the same
anchor and shared the same blind spot. The kill chain writes itself: a
future procrastinate guards a new table behind the same DO pattern, the
list misses it, the next diff drops it. So the anchor is gone. The
parser now strips comments and visits every CREATE token in the text,
wherever it hides, and each one is classified or the parser raises;
there is no third outcome, by construction. The guard test got rebuilt
on a different axis entirely, a flat token walk that shares no code with
the parser, so the two can't agree on a blind spot again. And the
catalog cross-check now runs against a real Postgres on every push
instead of only when someone remembers to point it at one.

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
output: tables, functions, types, sequences equal exactly, explicit
indexes and triggers equal once constraint-backed ones are set aside as
their tables' problem. The enumeration and reality agree on every one of
the forty-six objects, the guarded plpgsql extension included. The next
diff plan that wants to drop the queue will have to get past a generated
exclude list instead of my reading comprehension.

---

*End of Journal Entry 026*
