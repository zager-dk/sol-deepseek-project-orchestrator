# Visual workflow profiles

Use this reference for `visual-design`, `ux-ui`, `storyboard`, and `motion-fx`. They extend the same manual ledger, independent acceptance plan, bounded review loop, and integration gates as `code` (the unchanged default). They are task profiles, not extra skills or model roles. Sol remains the director/router; Luna implements and reviews independently; Sol senior/reviewer and Astra retain their existing escalation/consultation boundaries. The primary director and six child roles are unchanged. There is no Unreal Engine integration.

## Evidence boundary

The CLI validates record shapes, task transitions, file presence/content fingerprints, and evidence bindings. It does **not** search references, open images, run generators/browsers/editors, render exports, play video, authenticate user approval or reviewer identity, or verify model dispatch. A recorded `available`, `opened`, or `pass` is a manual claim that must come from actual observed tool use. Tests of this ledger do not prove visual quality or live tool availability.

The worker must create and inspect the deliverables with available tools; the independent reviewer must open the current renders/screenshots with its inspection tools. Source text, filenames, an author's report, and a textual `PASS` do not establish visual acceptance. If inspection cannot run, report `inconclusive` and the unrun checks.

## Preproduction to delivery

1. **Brief and capability check.** Agree the idea, audience, constraints, deliverables, and observable acceptance criteria. Check actual tool availability before promising a workflow. Prepare an independent acceptance plan before assignment; visual tasks cannot use `--review-mode manual-control`.
2. **Real references.** Search and open relevant sources. Preserve their HTTP(S) links, inspection evidence, and specific “take” and “avoid” notes. Do not invent references or imply an unviewed link was inspected.
3. **Directions.** Prepare 2–3 coherent directions with reference boards and exact palettes. Motion directions also identify inspected motion examples. A user-approved existing style may supply one direction when its source, version, scope, and approval are recorded. It still needs a current direction approval and prototype approval for this task.
4. **Direction approval.** Present the boards, palette, rationale, and tradeoffs. Record the user's explicit selection of the current direction and exact palette. The director or reviewer cannot approve on the user's behalf.
5. **Prototype approval.** Build and render a small representative prototype of the selected direction. Show that artifact to the user and record approval of its current digest. Then explicitly enter production.
6. **Production.** Produce all agreed editable sources, previews, and a report. Stay within the approved direction and scope; do not switch style during implementation.
7. **Independent visual QA.** Submit the final manifest. A reviewer separate from the director and every author actually opens every preview, inspects editable sources, and runs the relevant profile checks below. Record visual QA, then the normal independent `review`, `integrate`, and `complete` steps.
8. **Delivery.** Hand over the editable sources, usable preview, and report with verified paths/links, formats, current revision, QA results, known limitations, and failed/unrun checks. Ledger completion records the `delivery` stage; it does not upload or send files.

The CLI stores the prepared brief/references/boards together in `visual-spec`, initially at `directions`. It records capability preflight after that spec exists; this ordering does not excuse using an unverified capability while preparing boards. The director obtains real observations first and records them against the current spec.

## Capability preflight

`visual-preflight` requires an entry for **all nine** built-in categories, plus every extra name in `required_capabilities`:

| Category | Required for |
| --- | --- |
| `reference_search` | Every visual profile |
| `image_inspection` | Every visual profile |
| `editable_export` | Every visual profile |
| `preview_export` | Every visual profile |
| `custom_roles` | Every visual profile; confirm the actual routing capability |
| `browser_interaction` | `ux-ui` |
| `temporal_inspection` | `motion-fx` |
| `image_generation` | Only if promised or listed in `required_capabilities` |
| `video_generation` | Only if promised or listed in `required_capabilities` |

Generators are optional when the brief can be met with other observed authoring tools. Do not claim a generator exists based on a model name or package installation. Conversely, do not silently drop required generation, interaction, playback, or editable export.

Every entry has `status: "available"` or `"unavailable"` and nonempty `evidence`. An available entry also needs nonempty `tool` and `source`, identifying the actual observation. The input is `{"capabilities": {"image_inspection": {"status": "available", "tool": "<actual tool>", "source": "<observation reference>", "evidence": "<what was opened and observed>"}, ...}}`; replace the ellipsis with all required entries. See the [preflight template](../examples/visual/capability-preflight.json), which deliberately starts unavailable.

An unavailable required capability blocks approval/production. Either restore it and record fresh preflight, or obtain the user's explicit agreement to a reduced scope, record `scope_reduction` in a **new spec**, and renew approvals. The `scope_reduction.removed` list must exactly name removed capabilities and formats as `role:format` (for example, `video_generation` and `editable:pdf`). A reduction cannot remove a profile's built-in capability gates; if the requested outcome becomes a different profile (for example, a storyboard instead of motion), use a separately contracted task with that profile. Never report motion completion when only still frames were possible.

## Spec JSON

Pass one JSON object to `visual-spec --file`. Required fields:

| Field | Shape / meaning |
| --- | --- |
| `brief` | Object with nonempty `idea`, `audience`, and nonempty `constraints` string list |
| `references` | Nonempty list of objects with unique `id`, real HTTP(S) `url`, `take`, `avoid`, and `inspection_source`; motion sources additionally use `kind: "motion"` |
| `directions` | 2–3 objects, or exactly one when `existing_style` is present |
| Each direction | Unique `id`, `summary`, nonempty `palette` of `#RRGGBB` strings, nonempty `reference_ids`, and `board: {"path": "...", "format": "..."}` |
| Motion direction | Also nonempty `motion_reference_ids` pointing to references with `kind: "motion"` |
| `deliverables` | Object with nonempty `editable`, `preview`, and `report` lists of promised format strings |
| `required_capabilities` | Optional list of additional required capability names |
| `existing_style` | Optional object with `source`, `version`, `scope`, and `approval` using the user-source shape below |
| `scope_reduction` | Object required when removing promised formats or extra required capabilities; contains `description`, `removed` list, and `approval` using the same user-source shape |

Board and artifact paths must name existing regular files inside the project. Parent traversal, Git metadata, protected `.codex` configuration, and symlinks/junctions are refused. Use project-relative paths such as `design/board-a.svg`. Content is fingerprinted even for ignored files. A format label is a declared contract string, not a validated MIME type or proof the file opens; reviewers must verify usable exports. Every promised final format must have a matching artifact `role` and `format`.

The [static spec](../examples/visual/static-spec.json) and [UI spec](../examples/visual/ui-spec.json) illustrate the shape. First copy the packaged `examples/visual` directory from the skill into `<project>/examples/visual`; the example specs resolve their board paths relative to that project, not the installed skill. Example assets and templates are scaffolding, not researched references, observed capabilities, approved designs, or completed QA. Replace placeholders with real task evidence.

## Approval and artifact JSON

Every user-source approval contains these fields. This is a template, not approval:

```json
{
  "decision": "approved",
  "origin": "user",
  "source": "<exact message or approval source>",
  "quote": "<the user's actual approval words>",
  "approved_by": "<the user who approved>",
  "revision": 1,
  "direction_id": "direction-a",
  "palette": ["#17243A", "#F6EEDB"]
}
```

For direction approval, `revision` must be the current integer revision, `direction_id` must select a current direction, and `palette` must exactly match its palette (including order). For prototype approval, use the same user-source fields and `revision`, with `artifact_digest` copied from `visual.prototype_digest` in `visual-status`; `direction_id`/`palette` are not needed. This digest binds approval to the registered prototype and selected direction. Do not fabricate source references, quotes, identity, or a digest. See the [approval template](../examples/visual/approval-template.json).

Both prototype and final registration take an `artifacts` list:

```json
{
  "artifacts": [
    {"path": "design/source.svg", "format": "svg", "role": "editable"},
    {"path": "design/preview.png", "format": "png", "role": "preview"},
    {"path": "design/report.md", "format": "md", "role": "report"}
  ]
}
```

Each manifest needs a preview and unique paths; roles are exactly `editable`, `preview`, or `report`. A prototype can contain only a preview. A final manifest must cover **every** promised format for all three roles. For `motion-fx`, every preview additionally needs `kind: "video"`, a `format` of `mp4`, `webm`, `mov`, or `gif`, a matching file extension, and a finite positive `duration_seconds`. This checks declarations and file bytes, not decoding or actual playback. The CLI records a `content` fingerprint for each artifact. Copy that exact field from `visual-status` into QA evidence; do not calculate a substitute or assume it is just a raw SHA-256.

Keep approved prototype files immutable at separate paths from evolving production sources and final renders (for example, `design/prototype-v1.png` and `design/final.png`). Production checks deliberately reject changed prototype bytes; overwriting the prototype while making the final output stales approval.

## Independent QA and profile acceptance

`visual-qa` takes `reviewer`, `result` (`pass`, `fail`, or `inconclusive`), and nonempty `findings`. A passing record additionally needs `unrun: []`, an `opened` observation for **every** final preview, and the required `checks` map. Every declared check, including extra checks, must have `result: "pass"`, `evidence`, `tool`, and `source`, all drawn from an actual inspection. A failed, inconclusive, or unrun extra check also prevents PASS. The nonempty reviewer ID must match the nonempty `--actor` and be distinct from the director and all recorded authors.

An `opened` observation has `path`, the exact registered `content`, `tool`, `source`, and a concrete `observation`. For motion, also record `mode: "playback"`, `start_seconds: 0`, and `end_seconds` equal to the preview's full `duration_seconds`. Review full temporal playback, including beginning, end, and any loop seam. Contact sheets and stills can supplement playback; they cannot replace it. See the [QA template](../examples/visual/qa-template.json); its placeholders are not a passing observation.

All profiles require checks named `visual`, `palette`, `references`, and `editable_source`. Define concrete thresholds and scenarios in the original acceptance plan. The CLI requires these names and evidence fields; the reviewer judges the quality and coverage:

| Profile | Acceptance guidance | Extra required check names |
| --- | --- | --- |
| `visual-design` | Open the rendered output at intended sizes. Check composition, hierarchy, typography/legibility, spacing, clipping, approved palette and reference take/avoid choices. Open the editable source and verify that its structure and export are usable. | None |
| `ux-ui` | Inspect screenshots and the running UI. Exercise agreed flows and relevant states/errors, navigation and keyboard use. Check representative viewports, overflow and responsive hierarchy, focus/labels/contrast and other agreed accessibility requirements. A static mockup cannot prove interactions. | `interactions`, `responsive`, `accessibility` |
| `storyboard` | Open the complete ordered board. Verify shot order, framing, action and intent, readable annotations, spatial/character/prop continuity, and any agreed timing cues. Ensure editable panels and preview sequence are complete. | `sequence`, `continuity` |
| `motion-fx` | Play every preview in full at the intended playback conditions. Verify pacing, easing/timing, transitions, continuity, start/end or loop behavior, and specified duration/output constraints. Inspect the editable timeline/project as well. | `timing`, `transitions`, `continuity` |

Record defects as `fail`, uncertain or unrun coverage as `inconclusive`. `visual-qa` records evidence but does not itself change the task's acceptance state. Follow it with normal `review --result fail|inconclusive` to return work for correction or block it. A passing visual record alone cannot integrate or complete a task; the existing independent review, fresh-context evidence, high-risk rules, and exact integrated snapshot checks still apply.

## Command surface

Use `python scripts/orchestrate.py --project /path/to/repo COMMAND`. The installed runtime has the same interface under `<CODEX_HOME>/skills/sol-deepseek-project-orchestrator/scripts/orchestrate.py`. The table omits that common prefix:

| Command | Actor / purpose |
| --- | --- |
| `add V-101 --profile visual-design --goal "..." --scope "design" --acceptance "..." --actor director` | Create a visual task; use the usual dependencies, risk, and priority options as needed |
| `visual-spec V-101 --actor director --file spec.json` | Record prepared brief/references/boards and create the next visual revision |
| `visual-preflight V-101 --actor director --file capabilities.json` | Record all observed capability categories for this revision |
| `visual-approve V-101 --actor director --target direction --file direction-approval.json` | Record sourced explicit user direction/palette approval |
| `visual-artifacts V-101 --actor worker --target prototype --file prototype.json` | In-progress owner registers a rendered prototype |
| `visual-approve V-101 --actor director --target prototype --file prototype-approval.json` | Record sourced approval of its current digest |
| `visual-production V-101 --actor director` | In-progress task enters production after both current approvals |
| `visual-artifacts V-101 --actor worker --target final --file final.json` | Owner registers all promised deliverables |
| `submit V-101 --actor worker` | Enter normal review state and visual `qa` stage |
| `visual-qa V-101 --actor reviewer --file qa.json` | Independent reviewer records actual observations after submission |
| `visual-status V-101` | Read the profile, full visual record, revisions, digests, and fingerprints |

This is the visual portion, not a standalone runnable lifecycle: also `init`, `plan-review`, `assign`, and `start` before owner artifact registration, then `review`, `integrate`, and `complete` after QA. See [Delegation contract](DELEGATION_CONTRACT.md) and each command's `--help` for those unchanged contracts. Only the task's recorded creator/director records the spec, preflight, approvals, and production transition. All mutating visual commands accept `--reason` from `initial` (default), `user-feedback`, `direction-change`, `capability-change`, `qa-fix`, `scope-change`, or `recovery`.

## Revisions, corrections, and statistics

- A new `visual-spec` increments the visual revision, preserves spec history, and resets preflight, approvals, prototype/final manifests, and QA. It is accepted in `planned`, `in_progress`, or `blocked`. A direction or palette change always needs this new spec and fresh approvals, even if the change seems small.
- Bindings include the visual revision, spec digest, and task contract revision. Replanning the task contract invalidates old bindings. Board changes stale the spec's recorded board evidence; do not overwrite an approved board and retain its approval.
- Before production, registering a changed prototype removes prototype approval. Once production starts, return through a new spec to change the prototype/direction. Final corrections invalidate QA; re-register final artifacts and repeat observed review after the usual failure/correction transition.
- Visual QA binds to the artifact set, both approval records, owner history, and implementation attempt. File drift, an author change, or a new attempt cannot reuse its pass. Integrated/completed tasks cannot mutate visual records; create a follow-up task for a new delivered revision. Interruption recovery still requires preservation of edits and a stopped-owner declaration.
- `stats --format json` adds a `visual` sidecar section with per-profile counts and category records (`event`, `stage`, `revision`, `reason`, and optional result) using pseudonymous task references. Its `summary` contains `events_by_type`, `revision_reasons`, and `qa_results` category counters. Raw user quotes, paths, sources, and findings stay out of that export. JSON-only visual details do not extend the fixed CSV columns. `evidence_source` is `manual_ledger_records`; `observed_model`, `observed_tokens`, and `observed_cost` remain `null`. These records do not support model, token, spend, or savings claims.
