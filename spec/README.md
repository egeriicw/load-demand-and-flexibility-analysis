# Specification Directory

## Files

| File | Purpose |
|---|---|
| `SPEC.md` | Living specification document. Edit directly as decisions are made. |
| `CHANGELOG.md` | Append-only log of changes, decisions resolved, and sections updated. |
| `adr/` | Architectural Decision Records — one file per resolved question cluster. |

## How to work with this spec

1. **Resolving an open question** — update the relevant section in `SPEC.md` (change status from UNRESOLVED to DECIDED, add the chosen approach), then append an entry to `CHANGELOG.md`, then create an ADR in `adr/` if the decision warrants one.

2. **Locking a section** — mark it `STATUS: LOCKED` at the top of the section and record the lock in `CHANGELOG.md`.

3. **Re-opening a decision** — add a `REVISION` block inside the relevant section explaining what changed and why, and log it in `CHANGELOG.md`.

4. **Tracking the open-question register** — Section 50 of `SPEC.md` is the canonical list. As questions are answered, mark them `[x]` and add the resolution inline.

## Status vocabulary used in SPEC.md

| Tag | Meaning |
|---|---|
| `LOCKED` | Decision is final; do not change without a formal revision entry |
| `DECIDED` | Agreed but not yet frozen; implementation may proceed |
| `PROVISIONAL` | Working default; expected to be revisited |
| `UNRESOLVED` | Open question; do not implement until resolved |
| `RECOMMENDED` | Proposed by the spec author; awaiting acceptance |
