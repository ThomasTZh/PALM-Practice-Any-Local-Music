# basseparate plan reconciliation — feasibility and edit log

This file records the edits made after reviewing the nine proposed resolutions. Line numbers below refer to the revised files in this package. `plan_edits.diff` is the authoritative exact before/after record.

## Feasibility review

| # | Resolution | Feasibility | Result |
|---|---|---|---|
| 1 | Scope Auto/Edited branches to editable symbolic/annotation analyses | Feasible | Adopted. Separation remains immutable result-version selection; mixer state remains ordinary editable project state. |
| 2 | Bundle the pinned Demucs `htdemucs_ft` baseline in the development workspace and personal end-product | Feasible for the stated private/personal package | Adopted. The verified weights live in an ignored development-workspace model directory, are copied into the release bundle, remain outside version control, and remain excluded from `.basseparate` project archives. If the package is ever redistributed, the checkpoint redistribution terms must be rechecked. |
| 3 | Use backend-managed staging plus browser downloads for Save/Export | Feasible | Adopted. Atomicity applies to the managed generated artifact; authenticated `Content-Disposition` downloads hand final filesystem placement to the browser/user. |
| 4 | Add bass-stem-specific tuning estimation as a separate M5 estimator/result | Feasible | Adopted. `BassStemTuningEstimate` is tied to one exact bass stem and has its own immutable identity/cache key. A dedicated high-resolution spectral/harmonic evidence path avoids circular dependence on pYIN/torchcrepe decoding. Project/manual tuning remains an explicit fallback/override. |
| 5 | Reword M7 as consolidation/generalization of model management | Feasible | Adopted and adjusted for #2. M7 represents distribution state (`bundled` vs `separately_installed`); bundled Demucs is verifiable/qualifiable but not ordinarily removable/downloaded. |
| 6 | Reword M6 as hardening/unification of persistent undo/redo | Feasible | Adopted. Earlier milestones retain module-local history responsibilities; M6 consolidates and hardens them project-wide. |
| 7 | Establish a generic network-download worker boundary, adjusted for bundled Demucs | Feasible | Adopted. Because M2 no longer downloads Demucs, M3 establishes the first reusable durable network-download worker for Beat This! and later non-bundled model families. Offline mode never gets silently overridden. |
| 8 | Give portable projects a separate configurable upload/archive limit | Feasible | Adopted. The M1 20 GiB media-import limit is explicitly not reused; M2 uses a distinct `max_project_archive_bytes`, with its default determined by archive/long-project stress tests and disk-safety testing. |
| 9 | Leave six-string acceptance wording as-is | Feasible | No edit made for this item. Existing M5 material already includes six-string/upper-register evaluation coverage. |

## Files and sections edited

### `basseparate_project_plan.md`

- Confirmed preferences (around lines 9–19): Demucs baseline changed from an explicit runtime download to a bundled personal-release asset; other models remain explicit retrievals.
- Repository organization (around line 116): clarified that bundled Demucs weights remain ignored/outside source control and are copied by packaging.
- §6.7 Bass transcription processing (around lines 787–816): bass-stem-specific tuning is now its own immutable result and the selected tuning interpretation is an explicit transcription dependency.
- §6.8 Whole-pipeline execution (around lines 822–836): Analyze All now runs/reuses bass-stem tuning before transcription.
- §9.2 Automatic and edited versions (around lines 1162–1177): Auto/Edited is limited to editable symbolic/annotation families; separation has immutable retained versions only.
- §9.3 Portable `.basseparate` format (around lines 1179–1219): bundled Demucs weights remain excluded; save publication now uses managed storage + authenticated browser download.
- §10.2 Export procedure (around lines 1297–1315): replaced backend “final path” semantics with managed atomic publication + browser download.
- §11.1 Local-only operation (around lines 1334–1345): bundled Demucs requires no network job; offline mode blocks only non-bundled model retrieval/YouTube retrieval.
- Section 13 Milestones 2, 5, 6, 7 (around lines 1565–1680): wording updated to match bundled Demucs, separate bass tuning, undo/redo hardening, and model-manager consolidation.

### `milestone1.md`

- §4.2 Upload protocol (around lines 217–228): clarified that the 20 GiB limit applies to local media import only, not `.basseparate` archives.

### `milestone2.md`

- §1.1/§1.2 and fixed decisions (lines ~10–100): Demucs is now a bundled baseline rather than a user-installed model.
- M2.3 (starting around line 274): renamed to “Pin and provision the bundled Demucs baseline”; added ignored workspace storage, release-copy verification, bundle states, local repair/developer import, and no network Install action.
- M2.13 WAV export (starting around line 1082): backend publishes managed export artifacts and returns authenticated browser download IDs/URLs rather than authoritative filesystem paths.
- M2.15 portable save (starting around line 1242): archive generation/publication is atomic in managed storage; browser handles final save location.
- M2.16 portable open (starting around line 1305): added independent `max_project_archive_bytes`; it does not inherit the 20 GiB media limit.
- M2.17 API (starting around line 1379): replaced Demucs install API with verify/qualify API and added authenticated generated-artifact download endpoint.
- M2.18 tests + final checklist (starting around lines 1445 and 1654): replaced download/resume tests with bundled-integrity/repair/packaging tests.

### `milestone3.md`

- §4.3 (around line 514): M3 now establishes the first reusable durable network-download worker boundary because M2 Demucs is bundled. Explicitly states that offline mode must be disabled by the user before an install; the Install action may not override it silently.

### `milestone4.md`

- §5.7 Installation workflow (around line 1032): now reuses M2 registry/provenance conventions and the separate network-download flow established in M3.

### `milestone5.md`

- Required workflow and included capabilities (starting around line 13): added bass-stem tuning estimate/result selection before transcription.
- Fixed decisions and run/result schemas (around lines 149–450): selected tuning interpretation can reference `BassStemTuningEstimate`, project tuning, or manual override.
- M5.3 (starting around line 587): explicit tuning-interpretation selection and dependency split; bass-stem estimates cannot be silently reused across stem versions.
- M5.4 additions §6.9–§6.10 (around lines 778–817): added independent spectral/harmonic bass-stem tuning estimator and immutable `BassStemTuningEstimate` schema/cache identity.
- M5.22 API/job graph (starting around line 2550): run requests, validation, stages, and progress now include bass-stem tuning estimation/resolution.
- Cache/staleness and portable-project sections (around lines 2780–2920): tuning-result identity is part of decode cache/staleness/provenance and saved project state.
- Evaluation §27.6 and §28.2 (around lines 3030 and 3096): added known-detuning/uncertain cases and quantitative tuning-offset metrics.
- Final checklist (around line 3721): added dedicated bass-stem tuning estimator acceptance items.
- Handoff/final acceptance (around lines 3905–3950): M6 receives explicit bass-stem tuning dependencies and M5 completion now includes the separate tuning result.

### `milestone6.md`

- Scope/workflow (starting around line 13): persistent undo/redo is explicitly project-wide hardening; Auto/Edited applies only to families with editable branches.
- M6.7 (starting around line 882): separation uses retained immutable result-set selection with no generic Edited mode.
- M6.23/M6.29/M6.35 (around lines 2125, 2579, 3008): exports use managed staging/publication plus authenticated `Content-Disposition` browser downloads; arbitrary browser-supplied backend filesystem paths are no longer the baseline.
- M6.33 API (around line 2842): added authenticated generated-artifact download route.
- Direct traceability table (around line 4121): wording aligned with revised main-plan Milestone 6.

### `milestone7.md`

- Outcome/included decisions (starting around line 11): Demucs baseline is bundled; installs/downloads apply to non-bundled models.
- §4.3 (around line 357): added explicit distribution state and bundled-specific availability states.
- M7.16 (starting around line 1161): model manager now distinguishes bundled vs separately installed assets; bundled Demucs is verifiable/qualifiable but not normally removable.
- M7.17 (starting around line 1232): download jobs explicitly apply only to separately installed models.
- Analyze All graph (around line 1886): adds/reuses bass-stem tuning estimate before transcription.
- Traceability/completion wording (around lines 3571–3640): updated to “consolidate/generalize” model management and non-bundled download progress.

### `milestone8.md`

- Fixed decisions and §2.2 (around lines 169–245): personal base release now explicitly contains verified `htdemucs_ft`; other model artifacts remain separately installed/imported.
- Release manifest (starting around line 342): includes bundled Demucs manifest/artifact hashes and bundle-relative locations.
- Offline qualification (around line 1090): distinguishes bundled Demucs from already-installed optional models.
- M8.27 offline model import (around line 1568): ordinary offline import applies to separately installable models; bundled Demucs uses verification/repair/reinstall semantics.
- Model/runtime checklist and final acceptance (around lines 2752 and 2944): online install/remove requirements now explicitly exclude the bundled Demucs baseline.

### `milestone0.md`

No edit was required. Its default `offline_mode = enabled` remains intact; M3 now specifies the explicit user action needed to disable offline mode before downloading later non-bundled models.

## Exact patch

See `plan_edits.diff` for every changed line in unified-diff format, including original and revised text with hunk line numbers.
