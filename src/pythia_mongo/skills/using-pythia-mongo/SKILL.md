---
name: using-pythia-mongo
description: Use when starting any conversation that touches MongoDB, a collection, a document's shape, a validator, an index or a view - it picks the right pythia-mongo skill BEFORE any response or action, including clarifying questions. Fires on plain requests in any language - "build/add/fix/explain/review X", "lam/them/sua/tao/giai thich/kiem tra X" (Vietnamese, with or without diacritics). Also use whenever unsure which pythia-mongo skill applies.
---

# Using pythia-mongo — the pocket handbook

**Phase:** Learn → Ask → Do — this page opens the right one

pythia-mongo is pythia for MongoDB. Its one job here is consistency:
whether a session measures the blast radius and asks before it writes
should not depend on the agent's mood that day.

## The Rule

If there is even a small chance a pythia-mongo skill applies, open it
**before acting** — before answering, before exploring, before clarifying
questions. Opened the wrong one? Close it, no harm done.

## Route by what the developer said

| The request sounds like | Open first | Then |
|---|---|---|
| "explain X / why / what does a document look like" ("giải thích") | `pythia-mongo-explore` | |
| "is it safe to touch X" | `pythia-mongo-impact` | |
| "change / fix / add X" ("sửa", "thêm") | `pythia-mongo-impact` | write, then `pythia-mongo-apply` |
| "land / apply this" — one command | `pythia-mongo-apply` | `pythia-mongo-verify` |
| "run these data changes together" ("chạy script") | `pythia-mongo-deploy` | `pythia-mongo-verify` |
| "do it all without asking me" ("tự động hoàn toàn") | `pythia-mongo-autopilot` — one lease, never a blank cheque | the task's own skills |
| "undo / restore X" | `pythia-mongo-apply` (a restore is a write) | `pythia-mongo-verify` |
| documents rejected, a view that fails | `pythia-mongo-explore` (`errors`, `src`) | |
| about to say done / fixed / works | `pythia-mongo-verify` — evidence first | |
| setup, connection failures, the hooks not running | `pythia-mongo doctor`, then `pythia-mongo check` | |

Priority when several apply: **process before construction** — impact
before writing, apply's preview before any write, verify before "done".
Announce the skill you opened ("Using pythia-mongo-impact — ...") so the
developer sees which page you are on.

## A request with open decisions

A change that leaves real decisions open — documents kept or deleted, a
field required or optional, what a validator does with a document that
breaks it (refuse or warn), an index unique or not, a security or audit
trade-off — becomes questions with options and a recommendation, asked
**before** anything is written. A new decision found mid-build stops the
build.

## Red flags

| Thought | Reality |
|---------|---------|
| "This task is simple" | Simple tasks hide decisions; ask the open ones first. |
| "I'll just run it in mongosh / Compass" | Those have no snapshot, no rehearsal or prediction, no journal. The guard denies mongosh writes. |
| "I know what the documents look like" | The live database is the truth: `pythia-mongo cols` reads a sample. |
| "Nothing depends on this collection" | MongoDB records only views: the application code that uses it is invisible to the database. |
| "I remember what that skill says" | Open the current page. |

## Session state

The session-start brief ends with `STATE` lines: the connections (the
default is starred) and the write policy per group. Read them before
deciding whether a write is even allowed — `data_dml` and `structural` are
`deny` until the developer says otherwise.

No STATE line this session means the hooks are not running and the guard
is off: say so to the developer before any write and ask them to run
`pythia-mongo doctor`. Every rule still binds.
