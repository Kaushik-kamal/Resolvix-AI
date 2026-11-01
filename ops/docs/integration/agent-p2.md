# Agent P2: gaps, KB and rules pages (integration note)

Code: `ops/dashboard/src/pages/gaps/`, `kb/`, `rules/` (each `index.tsx` keeps the default export the router lazy-imports).
Tests: `gaps/GapsPage.test.tsx`, `kb/kbModel.test.ts`, `kb/KbPage.test.tsx`, `rules/RulesPage.test.tsx`
(`kb/testUtils.tsx` holds shared test fixtures and an `AuthProvider` render helper; production code never imports it).

## Behaviour contracts other code may rely on

- **Gap to KB navigation:** `/gaps` navigates to `/kb` with router state `{ kbDraft: KbDraftSeed }`
  (`pages/kb/draftSeed.ts`: `clusterId`, `label`, `department`, `questionVariants`, `idPrefix`). The KB page reads it once,
  opens the editor prefilled (department, question variants, id prefix like `TRA-`), then clears the state with a
  `replace` navigation so a reload does not reopen it. `/kb?draftFromGap=<cluster_id>` does the same by looking the
  cluster up in `GET /v1/gaps/clusters` (the param is removed afterwards).
- **KB saves are always drafts:** the form sends `status: "draft"`; the UI says "saved as draft; an admin must approve".
  The `flagged` flag of the save result shows a warning; a 409 on approve shows a message about the injection scan.
- **Role handling:** approve / archive / restore buttons and the Publish panel use `useAuth().isAdmin`; staff only see
  Edit. The server stays the authority (403 is also handled).
- **Mock publish:** `isMockPublish(warnings)` looks for `mock publish` in `KBVersionInfo.warnings`; the result shows an
  amber "MOCK PUBLISH" banner and a `Publish (mock)` badge. History rows use the `mode` field of `GET /v1/kb/publishes`.
- **Rules page** is display only and renders the urgency rules document generically (unknown keys go to an
  "Other fields" column, unknown top-level sections into collapsible blocks). Department numbers go through
  `MaskedNumber` without a reveal button; short public numbers (112) are shown as is.

## Validation that is stricter than the model (decisions)

`KBEntry` only requires `id` (pattern), `department`, `question_variants` (min 1), `answer_en` and `source_title` as
present strings. The form additionally requires `answer_en` and `source_title` to be non-blank, and rejects
`valid_until` earlier than `valid_from` (an inverted range can never be valid). Dates must be real calendar dates.

## Requests for shared files (none block the pages)

1. `src/api/extra.ts` `GapCreatedEvent`: the real payload (SSE_EVENTS.md) is
   `{gap_id, cluster_id, label, department_guess, count, ts}`; the type still has a `department` field and a comment
   "Not emitted by the API until the gaps agent finishes". Suggested replacement:
   ```ts
   export interface GapCreatedEvent extends Stamped {
     gap_id: number;
     cluster_id: string;
     label: string;
     department_guess: string | null;
     count: number;
   }
   ```
   The pages do not use this type, so nothing depends on it.
2. `COMPONENTS.md` deep-link table: `/kb?draftFromGap=<cluster_id>` is now implemented (see above).

## WALLS

None. Verified against a seeded API on port 8106 through Vite on 5175 (login, gaps, KB list, mock publish and history,
rules and departments). The temporary database and both processes were removed afterwards.
