---
version: 1
slug: "frontend-app-page-tsx"
primary_target: "frontend/app/page.tsx"
related_targets: []
---

# Surface: AP workbench (frontend/app/page.tsx)

Mode: Operate. Single page; no routing. Audience: AP analyst (primary), Zamp evaluators watching a recorded/live demo. Task: upload one invoice, watch the pipeline run, read the decision, change the price tolerance and re-run to see the verdict change. Constraints: offline, light mode, system fonts, indigo accent, no animation libraries, plain-English labels. Out of scope: audit viewer, override UI, exports, auth, multi-file upload, theme toggle.

## Direction contract

THESIS: A run is evidence you can read top to bottom, and a re-run is a diff. Refuses the KPI-tile dashboard and the chat-style "AI result" card.

OWN-WORLD: Cool off-white ground (#f5f6f8), white panels with 1px slate hairlines, deep navy top bar (#101a2e), indigo (#4338ca) for actions and selection only. Status hues only where they mean something: green auto-approve, yellow pending, amber flag, red reject, solid dark red fraud, slate for pending/skipped. System sans; mono with tabular digits for amounts, IDs, tax IDs.

STORY: The analyst sees each bucket and check light up with its evidence, reads a plain decision with its reason and next step, then sees that one tolerance change flips exactly one check and the verdict.

FIRST VIEWPORT: Navy bar with product name and live config version. Left 65%: upload strip, then the vertical run trace (Collection, Categorization, Processing with 11 checks in 6 plain steps, Verdict). Right 35%: sticky Recent runs list. Primary action: the upload drop zone.

FORM: Pinned by brief (Linear / Notion / Stripe workbench register); signature move = run-to-run diff (changed checks tagged "Failed → Passed", old badge struck through, confidence counts to the new value, narrative crossfades). seed: none (unavailable)

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
