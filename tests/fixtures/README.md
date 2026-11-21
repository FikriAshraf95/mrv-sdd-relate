# Test fixtures

Small repos that mirror each reference format, with **invented content** (SPEC-10 §3). Nothing is
copied from the reference projects.

- `tool_style/`: this tool's own conventions. A toy tea-timer ("kettle") with stable task IDs,
  `(after …)`, a nested checkbox, a Feature line, acceptance checks and a deviation with a task and
  `Affects`. Used by the test host and the SPEC-03 parser tests.
- `rag_style/`: the office-rag format, domain "community library lending". Legacy tasks without
  IDs, `### Backend/Frontend/Tests` groups, header blockquotes with `Status`/`Owner of`, a
  multi-link *Read first* line, `docs/deviations/` empty.
- `suite_style/`: the office-suite format, domain "plant nursery stock". `**Spec ID:**` headers,
  schema tables per `###` heading, nested `> > **DEVIATION:**` notes, multi-line *Read first*,
  `DONE (date)` status paragraphs, a letter-suffixed milestone with its plan, and deviation files
  of several shapes (plain, linked and design-system `Spec:` fields).
