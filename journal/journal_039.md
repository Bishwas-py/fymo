# Journal Entry 039: The Most Common Line of JavaScript Was a Hang

**Date**: July 18, 2026
**Focus**: console.log during SSR corrupted the sidecar protocol and hung requests forever
**Status**: Shipped

## One Line, No Error, Nothing

Put `console.log('hello')` at the top of any component's script and request
the page. Not an error page, not a slow response, nothing in the terminal.
The request just never comes back. curl gives up whenever curl gives up,
the dev server sits there looking healthy, and there is not one line of
output anywhere pointing at the cause.

The first debugging tool anyone reaches for, in the language half this
framework exists to serve, was a remote detonator.

## Two Jobs, One Pipe

The sidecar talks to Python over stdout: four bytes of length, then that
many bytes of JSON, repeat. Strict, binary, position is everything. And
stdout is also where Node sends console.log. Component code runs during
render, render runs inside the sidecar, so a stray log line lands in the
middle of the frame stream and the parser on the Python side reads the
word "hello" as a length header. From that byte on, the two processes are
reading different books.

The part that made it a hang instead of a crash was subtler, and it was on
my side of the pipe. There was a timeout, thirty seconds, and it looked
protective. It guarded exactly one thing: how long until the first byte
arrives. Garbage arrives instantly. After that first byte the code dropped
into a read loop with no clock at all, waiting patiently for the rest of a
frame that could never complete. A timeout that only times the wait for
byte one is a lock on a door standing next to an open window.

## The Fix Is Old

RPC over stdio is not a new idea and neither is this failure. Language
servers hit it years ago and settled on the answer: the protocol owns
stdout, everything else goes to stderr. So the sidecar now rebinds
console.log, info, warn, and debug onto stderr before it wires up its
stdin listener. Nothing that runs during a render can touch the frame
stream, including dependencies nobody audited.

That alone would trade a hang for a black hole, logs going somewhere
nobody looks. So Python now captures the sidecar's stderr and forwards it
line by line, prefixed `[sidecar]`, onto its own. There is a trap in that
move: a captured pipe that nobody drains fills up in about sixty-four
kilobytes and then blocks the child mid-write, which is the same hang
wearing a different hat. The forwarder is a dedicated thread that starts
with the process and reads until the pipe dies, and there is a test that
logs two hundred kilobytes in one render to prove the trap stays shut.

And the clock now covers the whole frame. One deadline, start to last
byte, checked before every read. A desynced stream fails in bounded time
with an error that says what it suspects, and the failed process gets
replaced instead of trusted with the next request. While wiring that I
had to move the reads off Python's buffered file object onto the raw file
descriptor, because select watches the fd while the buffer hoards bytes
above it, and the two disagree about what "ready" means. The kind of
detail nobody writes down until it costs an afternoon.

## The Test That Freezes

The honest moment of this fix: the first regression test froze the whole
suite. Of course it did, the bug is a hang, and a test that reproduces a
hang hangs. The tests now run the render on a worker thread and give it
ten seconds to come home, so the failure mode is a red assertion instead
of a suite that never finishes. Watching that thread refuse to die before
the fix, and come back instantly after, was the whole story in one test
run.

---

*End of Journal Entry 039*
