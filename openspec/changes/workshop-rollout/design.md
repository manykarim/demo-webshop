## Context

The four workshop changes were archived before their rollout and verification tasks could run, because those tasks need systems outside the working tree: GitHub pull requests and workflow runs, the GHCR package, the Coolify host, an Apple Silicon machine, real tags, the maintainer and the workshop day. See proposal.md, Why. The code, workflow file, runbook and tooling those tasks exercise already exist; nothing here is implementation work.

## Goals / Non-Goals

**Goals:**
- Keep every open task of the four sources tracked, with its full original verification text.
- Run them in an order that respects the sources' own dependencies.

**Non-Goals:**
- Changing application behaviour, specs or tests. A task that uncovers a defect gets its own change instead of widening this one.
- Re-deciding anything the sources decided.

## Decisions

### D1. Tasks move word for word, with their origin

Each moved task keeps its original text and starts with **(was `<source>` <n.m>)**. The texts cross-reference each other by their original numbers (for example "task 10.5" or "`acceptance-conformance` task 18.1"), and "this change" inside a moved task means its source change. Rewriting 26 long verification texts would risk changing what they check. So the numbers stay, and the table below resolves them. Alternative considered: renumber the cross-references inside the text. Rejected because it edits verification wording that the source reviews already confirmed.

| New | Source change | Original | Original group |
|---|---|---|---|
| 1.1 | `reproducible-image` | 9.2 | 9. GitHub Actions workflow |
| 1.2 | `reproducible-image` | 9.3 | 9. GitHub Actions workflow |
| 1.3 | `drift-coverage` | 16.2 | 16. CI test job (design Decision 16, A5) |
| 1.4 | `acceptance-conformance` | 6.1 | 6. CI gate (D6) |
| 1.5 | `acceptance-conformance` | 6.2 | 6. CI gate (D6) |
| 1.6 | `reproducible-image` | 10.1 | 10. Rollout |
| 2.1 | `reproducible-image` | 9.4 | 9. GitHub Actions workflow |
| 2.2 | `reproducible-image` | 9.5 | 9. GitHub Actions workflow |
| 2.3 | `reproducible-image` | 10.2 | 10. Rollout |
| 2.4 | `drift-coverage` | 17.1 | 17. Release and handover |
| 2.5 | `acceptance-conformance` | 6.3 | 6. CI gate (D6) |
| 2.6 | `acceptance-conformance` | 1.1 | 1. Prerequisites and local target |
| 3.1 | `reproducible-image` | 10.3 | 10. Rollout |
| 3.2 | `reproducible-image` | 10.4 | 10. Rollout |
| 3.3 | `workshop-spaces` | 14.1 | 14. Coolify validation: early candidate and gating capacity test |
| 3.4 | `workshop-spaces` | 14.2 | 14. Coolify validation: early candidate and gating capacity test |
| 3.5 | `workshop-spaces` | 14.3 | 14. Coolify validation: early candidate and gating capacity test |
| 4.1 | `acceptance-conformance` | 17.2 | 17. Close-out and decision-record review |
| 4.2 | `acceptance-conformance` | 18.1 | 18. Release and handoff |
| 4.3 | `workshop-spaces` | 14.4 | 14. Coolify validation: early candidate and gating capacity test |
| 4.4 | `acceptance-conformance` | 18.2 | 18. Release and handoff |
| 4.5 | `acceptance-conformance` | 18.3 | 18. Release and handoff |
| 4.6 | `reproducible-image` | 10.5 | 10. Rollout |
| 5.1 | `workshop-spaces` | 15.1 | 15. Workshop tag deployment |
| 5.2 | `workshop-spaces` | 15.2 | 15. Workshop tag deployment |
| 5.3 | `acceptance-conformance` | 18.4 | 18. Release and handoff |

The sources are archived under `openspec/changes/archive/<date>-<source>/`. Their `tasks.md` still lists each moved task unchecked, with a pointer to its new number here.

### D2. Order by rollout phase, not by source

The groups follow the order in which the systems become available: pull request and merge, then the first `main` run and the public package, then Coolify and the `v0.2.0` tag, then the audit review, the gating capacity test and the workshop tag, and finally the workshop day and the handoff. Inside a group, the order follows the sources' dependencies. For example, the blocked rehearsal tag (4.2) comes before the real workshop tag (4.5), and the image-level checks of the workshop tag (4.6) come after it.

### D3. The sources' own archive tasks are done by the archive itself

The four sources each had a final archive task (`reproducible-image` 10.6, `workshop-spaces` 15.3, `drift-coverage` 17.3, `acceptance-conformance` 18.5). Archiving all four now carries out those tasks, earlier than their designs planned. Their verification checks, that the capability specs exist with the named requirements and that `openspec list` no longer shows the change, are run right after archiving, and the tasks are ticked in the sources. They are therefore not moved here.

## Risks / Trade-offs

- **[Archived before rollout]** The four capability specs now state behaviour whose published-image and hosted checks have not run yet. → The specs describe behaviour that is implemented and tested locally. This change is the open record of what still has to be proven on the real systems, and a failure found here goes into a new change.
- **[Stale references]** Moved texts name tasks by their source numbers. → The D1 table resolves every reference, and the archived sources keep the original numbering.
- **[Ordering pressure]** Several sources assumed they would be archived in a fixed order (for example `drift-coverage` before `acceptance-conformance` starts). → Both are complete. The only lasting effect of that order, the `planted-bugs` spec being available, holds because `drift-coverage` is archived before `acceptance-conformance`.

## Migration Plan

1. Open the pull request for the working branch and run group 1.
2. Continue group by group. Groups 3 to 5 need the maintainer's Coolify access and the workshop schedule.
3. Archive this change (task 6.1).

## Open Questions

- The workshop id for the first `workshop-<id>` tag and the registered participant count (the load-test target) are set by the maintainer when groups 3 and 4 start. Neither changes the tasks.
