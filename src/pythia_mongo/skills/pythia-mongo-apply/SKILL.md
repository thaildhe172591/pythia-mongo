---
name: pythia-mongo-apply
description: Use when landing any change in MongoDB - a validator, a view, an index, a new or dropped collection, an insert/update/delete, or restoring a previous version. Every write goes through pythia-mongo apply - one command document, rehearsed or predicted, previewed, approved by the developer, then written.
---

# Apply through the gate

**Announce at start:** "Using pythia-mongo-apply — preview first, then the developer approves."

**Phase:** Ask → Do — the preview is the Ask, the confirm is the Do

mongosh, Compass, mongoimport or a driver script would write with no
snapshot, no rehearsal or prediction and no journal; the guard denies them.
pythia-mongo writes one way, and says which of two it is:

- **Data** (`insert`, `update`, `delete`) is **rehearsed**: run in a
  transaction and aborted. A replica set is required.
- **A validator, a view, an index, a new or dropped collection** cannot run
  in a transaction in MongoDB, so it is **predicted** —
  "predicted — nothing ran" — from the data as it stands, written once
  after the approval, and read back.

## The Iron Law

```
NO WRITE WITHOUT A PREVIEW THE DEVELOPER SAW AND APPROVED
```

## The Workflow

1. **Impact first** (`pythia-mongo-impact`) — the number, and the code the
   database cannot see, were known before the command was written.
2. **One command document per file**, in Extended JSON — the document
   MongoDB takes, never mongosh JavaScript — linted first:
   `pythia-mongo lint <files>`. Errors are fixed, not argued. See
   `reference/refusals.md` for each refusal and its way forward.
3. **Preview:** `pythia-mongo apply change.json`. Nothing is kept. It prints:
   - the diff of the definition before and after (a validator, a view);
   - the rehearsal — the documents it touched — or the prediction: the
     documents a new validator would reject, a view that would fail over
     its first documents, the views built on it that would break, the
     views a drop breaks — and a unique index that would meet duplicates
     is refused before anything is asked;
   - an UPDATE or DELETE's documents: the count, a sample, a fingerprint;
   - `! DESTRUCTIVE`, and a token with the approval doors.
4. **Relay the preview verbatim.** Never call a prediction a rehearsal;
   never drop a `NOT VERIFIED` or a "would break" line.
5. **Ask, through the first door that works** — the next one unasked when
   a door fails (the hook or the tool result says which):
   1. **AskUserQuestion** (Claude Code): run
      `pythia-mongo approve --card <token>` and ask with exactly its output,
      options Approve / Reject, never with answers filled in.
   2. **The `pythia_mongo_approve` tool** (MCP; Codex starts here), with the
      token. The developer answers its prompt.
   3. **The developer's terminal:** relay `pythia-mongo approve <token>`.

   Never mint a grant, pipe anything into `approve --hook`, or set
   `PYTHIA_MONGO_CI` — the guard denies all three. A Reject means stop and
   ask what should change.
6. **Confirm:** `pythia-mongo apply change.json --confirm <token>`. It
   rehearses or predicts again and writes only if the file, the object,
   the documents and the prediction still match what was approved;
   otherwise it names what moved and writes nothing.
7. **Verify** (`pythia-mongo-verify`) before any "done".

## Exit codes are the verdict

| Exit | Meaning | You say |
|---|---|---|
| 0 | written, and read back as predicted (or NOT VERIFIED, said plainly) | what landed, and what was not checked |
| 1 | refused, nothing written | the reason, verbatim; never route around it |
| 3 | written **but broken**, written **but unlike the prediction**, or **`WRITTEN?`** | "broken" first: the report and the printed restore command; the developer chooses fix-forward or restore |

**`WRITTEN?`** means the command was sent and no answer says whether it
landed. Stop, relay the output verbatim, and let the developer look before
anything else runs. Never read the exit code through a pipe.

## Policy

`data_dml` and `structural` are `deny` by default; `source` (views and
validators) needs the developer's approval. `pythia-mongo policy` shows the
policy and whether rollback is real per group. Loosening it (`policy set`)
and `--yes` are the developer's acts, at a console — never yours.

## Restore is a write

`pythia-mongo history <name>` lists every version the journal holds;
`pythia-mongo journal restore <entry>` previews putting one back, and goes
through the same approval and `--confirm <token>`. Views and validators
have a restore (a new view's is a drop); documents, a dropped collection
and a dropped index do not come back.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "It's one updateMany, mongosh is faster" | And the documents it changed are gone with no record. |
| "The prediction said nothing breaks, so it's verified" | A prediction is not a rehearsal; the report after the write is the evidence. |
| "Exit 3, but it mostly worked" | Exit 3 is broken, or unlike what was approved. Say so first. |
| "The developer said go ahead earlier" | They approve a token, after seeing its preview. |
| "I'll write it as mongosh JavaScript" | Refused: one command document, the one MongoDB takes. |
