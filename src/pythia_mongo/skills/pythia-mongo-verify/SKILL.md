---
name: pythia-mongo-verify
description: Use before claiming any MongoDB change is done, fixed, working or safe - after an apply, a deploy or a restore. Evidence first - exit codes, the read-back report, errors - and "broken", "not verified" or "WRITTEN?" said plainly.
---

# Evidence before "done"

**Announce at start:** "Using pythia-mongo-verify — evidence before done."

**Phase:** Do — the last step of every change

MongoDB accepts a validator that every stored document breaks, and a view
that fails on its first read. "It applied" is not "it works", and a claim
of done without evidence costs the developer the debugging later.

## The Iron Law

```
NO COMPLETION CLAIM WITHOUT THE EVIDENCE PRINTED IN THIS SESSION
```

## The Checklist

1. **Every write's exit code, unpiped.** 0 clean; 3 written but broken,
   written unlike its prediction, or `WRITTEN?`. A 3 means the report
   starts with "broken" or "may be written".
2. **The read-back.** A predicted write is read back after it lands: quote
   what the report said — "as predicted", or how it differs.
3. **`pythia-mongo errors <name>`** for each collection and view you
   touched. Compare with the baseline taken before the change: only new
   findings are yours.
4. **`NOT VERIFIED` is reported as such.** A collection without a
   validator, a view run over its first documents only, an option
   pythia-mongo does not model: say "applied, not verified", never "clean".
5. **The code.** If a field or a collection changed, the application code
   found in impact is where the failure hides; name it in the report.
6. **`pythia-mongo lint`** on the change's files is clean of errors.

## How to report

```
Applied t_order (VALIDATOR) — exit 0, read back as predicted.
errors t_order: none (every document checked).
Views reading it: v_paid, v_paid_big — errors: none (first 100 documents).
Application code: orders/service.py writes status — unchanged values only.
Restore if needed: pythia-mongo journal restore <entry>
```

Say "broken" first when it is; say "not verified" plainly when it is.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "apply printed Applied" | Read the exit code and the read-back, not the word. |
| "The prediction said nothing breaks" | A prediction is not evidence; the report after the write is. |
| "errors printed nothing" | With no NOT VERIFIED line, that is evidence. With one, it is not. |
| "I'll verify after reporting" | Then the report is a guess. |
