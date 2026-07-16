# Journal Entry 023: Four Characters That Were Wrong Since 0.6.0

**Date**: July 16, 2026
**Focus**: The remote router's empty-payload fallback never actually encoded "no arguments"
**Status**: Shipped

## A Bug Nobody Hit Through the Front Door

The remote router has a fallback for requests that omit the `payload`
field: instead of erroring on the missing key, it substitutes a hardcoded
devalue string meant to represent an empty args list, so a zero-arg
function can be called with a bare `{}` body. Considerate design. Except
the hardcoded string was `"[1,[]]"`, and `devalue.parse("[1,[]]")` returns
the integer `1`, not `[]`. Two lines later the router checks
`isinstance(args, list)`, the integer fails the check, and the whole
considerate fallback collapses into a `bad_payload` 400 for exactly the
caller it was written to accommodate.

The correct encoding is `"[[]]"` — that's literally what
`devalue.stringify([])` produces. I verified both claims in a REPL before
touching anything, because a bug report that says "this constant is wrong,
here's the right one" deserves thirty seconds of confirmation rather than
blind trust, even when it's my own report.

Nobody noticed for seven versions because the generated `$remote` client
always sends a real, properly encoded payload, so the fallback string sat
there unexecuted by any legitimate traffic. The only people who ever
reached it were people poking at an endpoint with curl — which is
precisely the audience a fallback like this exists for. It failed only
and exactly for its intended users. There's something almost elegant
about that.

## The Fix and the Proof

The fix is four characters. The work was making sure those four characters
are pinned down forever: two failing tests first — one for an omitted
`payload` key, one for `"payload": ""`, both against a zero-arg function
through the real WSGI handler — watched them fail with the exact
`bad_payload` envelope from the report, then changed the constant and
watched them pass. Plus a third test that pins the invariant itself:
`devalue.stringify([]) == "[[]]"` round-trips to `[]`, so if the devalue
encoding ever changes shape, the test that breaks will point at the
dependency rather than leaving the fallback to silently rot again.

Then the part that actually mattered for a curl-shaped bug: I scaffolded a
throwaway app with a zero-arg `ping()` remote function, built it for real,
served it with wsgiref on a live port, and hit it with actual curl three
ways — bare `{}`, explicit empty payload, and no body at all. All three
came back `{"type": "result", "result": "[\"pong\"]"}`. That's the exact
command sequence from the bug report, running against a real socket,
returning the answer it should have returned since 0.6.0.

## The Count

787 passing, 123 skipped, zero failed. One constant, three tests, and a
reminder that the code paths nobody exercises are the ones that stay wrong
the longest — the fallback was written with care, reviewed presumably, and
shipped broken for over half a year because the string in it looked
plausible and nothing ever parsed it.

---

*End of Journal Entry 023*
