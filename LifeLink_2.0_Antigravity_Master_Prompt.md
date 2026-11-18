# LifeLink 3.0 — Google Antigravity Master Implementation Prompt

> **Copy this entire document into Google Antigravity's Agent chat, or place this file in the workspace and instruct the agent to execute it.** Put the user's renamed planning file `LifeLink_2.0_Plan.md` in the project workspace first. This prompt defines a software-engineering mission, not a claim that the current system is built, medically certified, or validated.

## 0. ROLE AND EXECUTION MANDATE

You are the lead software architect, senior full-stack engineer, embedded-systems engineer, biometric-computer-vision engineer, PostgreSQL/Supabase engineer, security engineer, QA engineer, and Raspberry Pi integration engineer for **LifeLink 3.0**, a fully wired, offline-first emergency medical identity and patient-information platform.

Your assignment is to **implement a functioning, testable project from scratch within this workspace**, using the provided plan and the referenced open-source iris repositories as source material. Do not merely explain what should be built or generate an impressive but non-functional UI. Write code, migrations, firmware, configuration, tests, documentation, and reproducible development/deployment scripts. Run the tests available in the current environment, examine failures, and fix defects.

Operate in Antigravity's structured planning/agent workflow: first create a task list, architecture and implementation-plan artifact; then implement in **small, verifiable milestones**, producing diffs, test results, and walkthrough artifacts. Respect any review/approval gates enforced by the environment. Do not claim a hardware or clinical test was performed when access to hardware, data, software weights, or permissions was missing. Continue useful software work using explicitly labeled simulators/mocks whenever the real hardware is unavailable.

**Execution policy:** Do not block on nonessential preferences. Make reasonable choices consistent with this prompt and document them in an ADR. Request a decision only for material safety/security, licensing, hardware/electrical, regulated deployment, credentials, or destructive data operations. Never run irreversible deletion, production database migrations, secret exposure, live-patient processing, or unapproved flashing against real hardware without explicit authorization. Do not access real patient data unless explicitly authorized and configured.

## 1. FIRST: READ THE WORKSPACE PLAN AND ESTABLISH SOURCE TRUTH

Locate and read the ENTIRE file named `LifeLink_2.0_Plan.md` (also accept `LifeLink_2.0_Plan` or a user-provided matching Markdown filename). Treat it as the user-supplied master planning input. If the file is absent, clearly report this blocker, scaffold only the uncontroversial foundational work, and do not pretend to have read it.

The plan may actually contain the **LifeLink 3.0 revised specification**, despite the renamed `LifeLink_2.0_Plan` filename. Follow the **substance and version within the file**, not the filename. If `PROJECT_DOCUMENTATION.md` is also available, treat it as historical LifeLink 2.0 background, not as authorization to restore Wi-Fi functionality.

Hierarchy for conflicts:
1. This prompt's non-negotiable revised requirements and safety constraints.
2. The latest user-supplied `LifeLink_2.0_Plan.md` for requirements, fields, architecture and workflows.
3. Actual audited behavior and documented interfaces of the checked-out hardware/AI repositories.
4. Verified official product datasheets, platform manuals, library documentation and standards.
5. Explicitly labeled engineering assumptions/ADRs, only where unavoidable.

Before implementation, produce `docs/requirements-traceability.md` mapping requirements to modules, APIs, tests and current status. Produce `docs/source-audit.md` with **source-derived facts vs proposed adaptations vs blocked/unverified assumptions**. Do not silently alter the plan's intent. Report conflicts and the practical resolution.

## 2. REQUIRED REPOSITORY RESEARCH AND REUSE

Inspect the following GitHub repositories directly, including their READMEs, actual Python/Android source, model definitions, requirements, checkpoints, licenses, upstream attribution, training/evaluation scripts, and current revisions. Record commit SHAs and license conclusions in `docs/third-party-audit.md`.

- **Parent research/index:** https://github.com/naveengv7/VISIrisHub
- **Segmentation:** https://github.com/naveengv7/LightIrisNet
- **VIS iris recognition:** https://github.com/naveengv7/Vis-IrisFormer
- **Android capture and quality reference:** https://github.com/naveengv7/IrisQualityCapture

Required handling:
- `VISIrisHub` is a research/reference index; do not assume it contains a complete application.
- `LightIrisNet` provides visible-light iris/pupil segmentation based on a MobileNetV3/DeepLabv3+-style design; inspect the actual model, normalization, transforms and inference code. A `model/best_mobilenetv3.pt` file appears in the repository, but verify it can be loaded and used correctly.
- `Vis-IrisFormer` supplies a VIS-adapted matcher consuming normalized iris strips; inspect how **embeddings and pairwise scores are actually computed**. Its README refers to an externally hosted pretrained checkpoint; verify download permission, availability, SHA-256/hash and correct tensor shapes. Never assume the model exists just because the README references it.
- `IrisQualityCapture` is **Android-specific** (Camera2/MediaPipe/OpenCV and optional BIQT server). Use it as a **conceptual/algorithmic reference for focus, framing, blur, glare, exposure and quality**. Do NOT copy Android APIs, build an Android app as the primary LifeLink client, or carry over Wi-Fi/cloud quality service dependencies. Port only justified, compatible algorithms to Python/Picamera2/OpenCV for the Pi Zero W and Pi 5. Verify licenses before porting source.
- Check permissions and attribution for EACH repository, particularly `Vis-IrisFormer` and its upstream; public code does not automatically imply a license to redistribute or commercially deploy it. Respect third-party model, weight and dataset terms. Do not push pretrained weights or datasets to a public repo without permission.
- The research paper's reported error rates are **not** LifeLink's measured accuracy. Do not import thresholds such as `0.84` or claim ISO compliance without testing the actual hardware/data.
- Isolate all borrowed code under documented adapters/vendor dependencies; preserve notices. Prefer small, maintainable inference interfaces over copying large training repositories into the app.

Create `docs/iris-repository-integration.md` describing exact classes/functions/files selected from these sources, modifications, weight requirements, source licenses, ARM64 CPU compatibility, and unresolved blockers.

## 3. NON-NEGOTIABLE LIFE LINK FUNCTIONAL REQUIREMENTS

**A. GUI and login:** Raspberry Pi 5 runs a touchscreen kiosk application. Initial screen offers **Clinical Login**, **Hospital Login**, and **Admin Login**. Each user has a unique identity; these are role-based entrances, not three shared passwords. After normal staff login the main dashboard has **Register Patient**, **Retrieve Existing Patient**, and **Update Existing Patient**. Admin accounts access a distinct Admin Dashboard with properly scoped capabilities.

**B. Registration sequence (must preserve order):**
1. Fingerprint enrollment (R1–R5, L1–L5; three acquisition passes per usable finger per GT-521F32 enrollment behavior).
2. Iris enrollment (right/OD and left/OS) through Pi Zero W camera.
3. Optionally take patient face photograph from the same camera via a separate capture mode.
4. Enter **basic**, **emergency**, **medical**, and **clinical-record** details as defined by the planning document.
5. Duplicate-candidate check, review/confirmation, validation and atomic local commit.
6. Generate permanent internal UUID plus human-friendly LifeLink ID; sync approved clinical fields to Supabase when connected.

Allow explicit, audited exceptions for missing fingers, injuries, unscannable eyes and low-quality acquisitions. Do not report ten fingerprints or both irises as complete when scans failed.

**C. Retrieval:** A biometric scan should search for possible existing patients (**1:N identification**), confirm candidate identity (additional 1:1 checks and/or other evidence), then show authorized patient details with prioritized emergency alerts, provenance and record-freshness indicators. When biometric matching is unavailable, inconclusive or ambiguous, use explicit fallback flows (authorized ID search, temporary unidentified patient, supervised emergency access). **Never silently select the top candidate.**

**D. Update:** Repeat identification/confirmation and check the operator's permission; load the existing record, allow only authorized field edits, show before/after diff, require reason on significant changes, save record revisions and audit events, and queue cloud sync. Biometric re-enrollment is a separate high-privilege operation.

**E. Admin dashboard:** Authenticated and properly scoped administrators can search/list and **view, edit, archive/deactivate and request deletion** of patient data; manage staff accounts/roles; see biometric enrollment **status** (not raw templates), devices, audits, backup health, synchronization/conflicts, and system settings. Separate records administrator from technical system administrator. No unrestricted hard-delete button in the browser. Apply retention/legal-hold checks, approval workflow, cross-database tombstones, and evidence of completed erasure where lawful.

**F. Clinical scope:** The system is an **information-retrieval and clinical decision-support prototype**, not a medical diagnostic or autonomous treatment engine. Show only attributable medical facts and clearly labeled summaries; do not synthesize unsupported diagnoses, contraindications or blood groups. Any future clinical AI summary must be opt-in, source-cited and reviewed by a licensed clinician.

## 4. HARDWARE TOPOLOGY — EVERYTHING WIRED

Implement this architecture, with mock/simulator substitutes in development:

```
GT-521F32 --UART TX/RX/GND--> ESP32 --USB serial--> Pi 5 USB-A host
Camera Module 3 Wide NoIR --CSI ribbon--> Pi Zero W --USB gadget Ethernet--> Pi 5 USB-A host
Touchscreen --DSI OR HDMI+USB touch--> Pi 5
Pi 5 --localhost--> Flask, iris inference, local PostgreSQL
Pi 5 --wired Ethernet / authenticated HTTPS (only if present)--> Supabase Cloud
```

**No runtime Wi-Fi, Bluetooth, wireless AP, ESP32 HTTP polling, wireless camera link, or wireless template transfer.** Disable radios where supported for deployment; keep development controls separate. Hosted Supabase still needs external network/internet access **over Ethernet**; distinguish `offline` from `wired` and do not suggest Supabase Cloud works without internet.

Hardware details are subject to board-specific verification:
- GT-521F32 UART TX → classical ESP32 GPIO16 RX2; sensor RX → ESP32 GPIO17 TX2; GND common. For other boards use suitable pins. Verify sensor power and UART voltage against actual datasheets before energizing. Do not assert a universal VCC pin voltage without checking the module.
- Classic ESP32 boards generally use an onboard USB-UART bridge (CP2102/CH340), whereas USB-native variants differ. Host connects via **Pi 5 USB-A**, not the Pi 5 USB-C power input. Discover device via `/dev/serial/by-id` or a stable udev rule; never rely blindly on `/dev/ttyUSB0`.
- If ESP32 runs MicroPython and USB serial shares the REPL console, design a robust dedicated runtime framing channel; **no REPL banners/print statements may contaminate biometric frames**. Test startup/reset behavior. MicroPython is preferred to reuse the original driver, but a documented switch to Arduino/C++/ESP-IDF may be proposed if it demonstrably solves protocol reliability issues without altering the architecture.
- Pi Zero W: use its micro-USB **USB/data** port for Linux USB Ethernet gadget; not its power-only connector. Verify `dwc2`/gadget configuration, the Bookworm-compatible commands, stable MACs, static link addressing, enumeration, and sufficient power. Use the correct CSI ribbon for the chosen Zero W/camera combination.
- Camera Module 3 Wide NoIR is NOT proven to yield enough VIS iris detail for recognition. Assess resolution, focus/macro limit, working distance, dynamic range, illumination and eye safety. `NoIR` does not mean a requirement to use NIR illumination; the provided research code targets visible-light iris images. If optics or hardware are inadequate, document measurable limits and recommend alternative close-focus optics/camera for user approval rather than faking results.
- Keep the Pi Zero W camera service running and idle between captures. Do not automatically shut it down after each frame unless a separate documented power/restart controller exists.
- Power the Pi 5 with a suitable dedicated PSU; document USB power budgets, ESD, enclosure and cable strain relief. Provide a UPS/recovery plan.

Deliver `docs/wiring.md`, `docs/hardware-bom.md`, `docs/pi-zero-usb-gadget.md`, and setup scripts with tested/untested labels.

## 5. RECOMMENDED MAINTAINABLE PROJECT ARCHITECTURE

Use a monorepo with clear boundaries. Prefer the plan's established Flask/JavaScript/MicroPython/Python/PostgreSQL stack unless a documented technical reason justifies a change. A suggested starting layout (adapt after inspecting actual files):

```
LifeLink/
  LifeLink_2.0_Plan.md
  AGENTS.md
  README.md
  .env.example
  .gitignore
  frontend/                  # kiosk UI, styles, JS, component/state boundaries
  backend/                   # Flask app factory, auth, patient/admin APIs, services
  fingerprint-device/
    esp32/                   # MicroPython firmware + sensor driver
    host/                    # Pi 5 USB serial transport & command worker
    protocol/                # documented message frames and test vectors
  iris-module/
    camera-client/           # Pi Zero W image capture + quality + USB HTTP service
    engine/                  # Pi 5 API, segmentation, normalization, matching
    adapters/                # LightIrisNet, Vis-IrisFormer integrations
  database/
    local/migrations/        # PostgreSQL
    supabase/migrations/     # hosted schema / RLS
  sync/                      # durable outbox + reconciliation worker
  deploy/
    systemd/
    pi5/
    pizero/
    esp32/
  scripts/                   # bootstrap, smoke tests, demo data, backups
  tests/
    unit/
    integration/
    contracts/
    security/
    hardware/                # opt-in physical tests
    e2e/
  docs/
    adr/
    architecture/
    protocols/
    validation/
```

Separate runtime services with well-defined interfaces. Flask communicates with a **single owner** of the fingerprint serial port and with the local iris service. Device jobs use unique IDs, cancellation, retry, timeouts and state transitions. Design typed schemas/contracts so the frontend, backend, simulator, device workers and tests agree.

Produce root `AGENTS.md` (concise and below Antigravity's per-rule-file size limit) containing durable project invariants, safety/PII rules, commands and directory map. Put long implementation instructions in `docs/`, not as oversized always-on rules.

## 6. FINGERPRINT PIPELINE — REAL IMPLEMENTATION, NOT PLACEHOLDERS

Inspect the actual GT-521F32 protocol/datasheet and the provided `fplibMicro.py` if present. Implement/open-sensor, LED, finger detection, capture, three-stage enrollment, template retrieval, scratch-slot wiping, set/load template, native 1:1 verification, and robust status/error reports. Verify packet structures, checksums, ACK/NACK, default/changed baud rate, template payload length and supported slot count against the actual device. Do not hard-code a mistaken packet assumption or treat all GT-521Fx2 variants as identical. The planning file refers to a 498-byte data area and scratch slot 199; explicitly validate both with the GT-521F32 revision and tests.

ESP32-to-Pi protocol must include a version, magic, message kind, request/job ID, command, length, binary payload, CRC/checksum, response status, and safe upper bounds. Implement host parsing that handles partial reads, merged frames, desynchronization, corrupted messages and reconnects. Add commands such as `HELLO`, `STATUS`, `LED`, `ENROLL`, `CAPTURE`, `GET_TEMPLATE`, `LOAD_TEMPLATE`, `VERIFY_1_TO_1`, `DELETE_TEMP`, `CANCEL`, `PING`; map them to actual supported sensor operations. No biometric data in debug output.

**Sensitive-data rule:** Do not permanently retain templates on the ESP32 filesystem or Pi Zero W filesystem. After sensor enrollment and successful Pi 5 acceptance, wipe allocated temporary sensor slots. Acknowledge that hardware-specific wear-leveling/remanence may prevent proving physical erasure; report verified deletion semantics, not an absolute guarantee of zero extractable residue. Encrypt biometric templates in Pi 5 PostgreSQL with protected key material and minimize plaintext lifetimes.

**1:N gap:** GT-521F32 templates are proprietary. Do not claim that a generic Python/OpenCV library can directly match them. Prototype and benchmark candidate search using device-native 1:1 reference loads and/or vendor-verified alternatives. Measure 10/100/1,000 reference performance and error rates; if infeasible, define a design gate and fallback to validated iris candidate search plus second-factor confirmation. Never mark unresolved identification as implemented.

Deliver firmware, Pi 5 host service, simulator, command/response test vectors, CLI smoke-test utility, hardware checklist and latency/error benchmark results when possible.

## 7. IRIS CAMERA, SEGMENTATION, NORMALIZATION AND MATCHING

Split responsibilities:

**Pi Zero W acquisition service**
- Control Camera Module 3 using Picamera2/libcamera when compatible, acquire frames directly to RAM, auto-exposure settle, eye localization/crop, focus/exposure/glare/occlusion/iris-size quality checks, left-vs-right labeling and bounded retry logic. Adapt quality concepts from `IrisQualityCapture`, not its Android dependencies or external BIQT server requirement.
- Provide authenticated, wired-USB-restricted request/response endpoints for status, iris capture, photo capture, cancel and health, with bounded image sizes, request IDs, checksums/hashes, timeouts, and clear quality reasons. Use volatile buffers for iris data where possible; avoid unnecessary raw-eye storage. Capture patient photo as an explicit, separately consented/authorized profile artifact according to retention policy.

**Pi 5 iris inference service**
- Load LightIrisNet model and checkpoint from inspected repo code. Test transform correctness, model eval mode, no-grad/inference mode, mask shape, eye/iris/pupil localization, low-quality and no-iris rejection.
- Normalize annular iris textures (e.g. Daugman rubber-sheet when supported by actual masks and model) to the representation required by the matcher; the Vis-IrisFormer README states normalized grayscale `64x512` input, but verify actual implementation.
- Load verified VIS-IrisFormer weights; reproduce its **real score computation**, patch embedding handling, angular displacement compensation/masking, and model metadata. Do not assume plain cosine similarity of flattened vectors accurately reproduces the repo's matching algorithm.
- Expose `enroll`, `extract`, `quality`, `identify_candidates`, `verify`, `health` interfaces. Keep model/version, tensor shape, channel order, preprocess config and threshold version on every template record. Reject cross-model comparisons unless a validated migration/re-enrollment procedure exists.
- Benchmark CPU/RAM/thermal behavior on actual Pi 5 (not only development workstation), and optional ONNX/quantized variants **only after numerical equivalence and accuracy checks**. Never silently degrade to an unvalidated model to make the demo appear to pass.

**Identification policy:** Build offline-capable candidate search using indexed feature retrieval **only if verified equivalent to the model's intended scoring**; re-rank candidates using the faithful matcher. Require calibrated thresholds and quality gates from genuine/impostor test pairs, non-enrolled-person trials, and real camera captures. Evaluate FAR, FRR, EER, false-positive identification, failure-to-acquire, confidence margin and latency. `0.84` from prior documentation is a placeholder, not a validated LifeLink decision threshold. Support `MATCH`, `NO_MATCH`, `INCONCLUSIVE`, and `CAPTURE_FAILED` with distinct UI behavior.

Capture quality evaluation should document which ISO/IEC 29794-6 dimensions are approximated versus formally tested. Do not advertise ISO certification or clinical-grade iris recognition.

## 8. DATABASE — OFFLINE LOCAL POSTGRESQL + SUPABASE CLOUD

Implement a **hybrid** persistence model:
- Pi 5 local PostgreSQL is the always-available operational store for encrypted fingerprint/iris templates, patient UUID mapping, a controlled offline patient/clinical cache, device jobs, audit entries, drafts and a transactional synchronization outbox.
- Supabase Cloud stores approved centralized demographics, emergency/medical/clinical records, staff metadata/role assignments and central audit/sync metadata. By default, **do not upload biometric templates or raw iris images** to Supabase. If a user later requests cloud biometrics, require a separate privacy/security design review.
- Only Pi 5 backend/sync worker accesses sensitive Supabase operations; **never embed service-role or database credentials in browser JavaScript or ESP32/Pi Zero firmware.** Configure strict Row Level Security on exposed Supabase tables and backend authorization for all actions. Supabase Auth may serve online staff authentication, but design a separately secured offline-authorization path; do not assume cached Supabase sessions are sufficient for offline identity/privileges.

Schema should include at minimum: patient UUID and LifeLink ID, patient status, demographics, emergency contacts, allergies, conditions, medications, surgeries/implants, clinical records and provenance, staff identities, roles, permissions, sessions, fingerprint templates by finger position, iris templates by eye/model/version, biometric sessions, device jobs, encounter records, record revisions, audit entries, deletion requests/approvals, local outbox/inbox, sync receipts/conflicts and retention/legal holds.

Detailed requirements:
- SQL migration scripts for local and Supabase stores, indexes/FKs/unique constraints, binary encrypted template columns, patient-version concurrency fields and example RLS policies.
- Durable **transactional outbox** for offline changes; idempotency keys, exponential retries, bounded failures, conflict states and visible last-sync timestamps. Reject silent last-write-wins for clinically important fields. Define authority and reconciliation per table/field.
- Data minimization for local cache; handle unavailable/stale cloud records clearly. Provide synthetic demo seed data only; no real patient identifiers or medical secrets.
- Design archive, merge, correction and deletion with tombstones on both stores, referential integrity, backup retention policies and prevention of deleted-record resurrection after sync.
- Migration scripts must be reviewable and reversible where possible. Never apply destructive production migrations automatically.

## 9. SECURITY, AUTHENTICATION, PRIVACY AND ADMIN CONTROLS

Implement unique staff accounts, role scopes, backend-enforced RBAC/ABAC, least privilege, short-lived sessions, secure cookies/CSRF protection as appropriate, strong password hashing (Argon2id or equivalent), rate limiting, lockout controls, optional admin MFA, device identities, USB camera API authentication, input and payload limits, logging redaction, secret management and encrypted backups. Do not use hard-coded credentials from old example documentation. Ship `.env.example` with placeholders and exclude real `.env`, passwords, tokens, keys, biometrics and model-sensitive datasets from Git.

Roles to model: clinician, nurse, registration staff, records administrator and system administrator, assigned as permission sets within the Clinical/Hospital/Admin login presentation. System-admin role does not imply unrestricted medical record access.

Admin Patient Management:
- Search/page/filter records; view only authorized details; show biometric **metadata/status** rather than raw payload.
- Edit with validation, field-level scope, rationale, optimistic concurrency and a before/after diff.
- Archive/deactivate with reversible state and audited reason.
- Deletion request with reason, retention and legal-hold checks, second-person approval where required, execution coordination between local/Supabase/cache/backups, and completion evidence. No unconditional browser `DELETE` on patients.
- Staff and role management with full audits; device status, sync error worklist, audit explorer and database backup health.

Audit all sensitive reads and changes: actor, action, patient reference, timestamp, reason, result, originating terminal and correlation ID; never include template bytes. Review relevant healthcare privacy/data-protection obligations and institution-specific retention/clinical approval; treat compliance certification as a separate project with legal/security reviewers.

## 10. TOUCHSCREEN GUI — REAL FUNCTIONAL FLOWS

Build a clean, high-contrast, professional, responsive **clinical workstation UI**, optimized for 7–10 inch or specified touchscreen, 48px+ touch targets, keyboard support, focus visibility and accessible alerts. Preserve any explicit design preferences from the plan. Avoid making the interface look verified/certified through unsupported badges. Browser must never access serial USB or sensitive Supabase secrets directly; talk to authenticated Flask APIs.

Screens (at minimum):
1. Startup/self-test with device and database health status.
2. Clinical/Hospital/Admin role choice, then individual account login, logout, session lock/timeout.
3. Standard dashboard with **Register / Retrieve / Update**.
4. Guided ten-finger capture with per-finger status, three impressions, retry/unavailable reasons, progress, cancellation.
5. Guided right/left iris capture with eye-position, quality feedback, retries/unavailable reasons.
6. Optional patient photo acquisition.
7. Basic details form; emergency details form; medical details form; clinical records form; validation and draft recovery.
8. Duplicate patient candidate review and confirmation; precommit summary.
9. Registration completion/receipt and human-friendly LifeLink ID.
10. Retrieve by biometrics with matching/inconclusive states; alternate manual lookup and temporary unidentified-patient path.
11. Emergency-oriented patient dashboard highlighting **source/verification status** of critical facts, warnings and last-sync freshness.
12. Update workflow with re-authorization, edit scopes, change preview and revision history.
13. Admin dashboard: patient table/detail, authorized edit, archive/deletion request, staff management, roles, audit events, device diagnostics, sync conflicts, backup status.
14. Visible offline/degraded states and explicit permissions/errors throughout.

Make the UI functional against the **real backend in mock-hardware mode**. Do not ship static buttons, mock dashboard numbers pretending to be real database counts, or successful capture animations for missing hardware. Label simulators and synthetic data. Preserve accessible navigation even when biometrics are unavailable.

## 11. EXPLICIT API CONTRACTS AND DEVICE JOB STATE MACHINES

Define versioned typed request/response contracts (Pydantic/JSON Schema or equivalent) and API documentation. Suggested API families (adapt naming to plan):

```
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
GET  /api/v1/devices/health
POST /api/v1/biometrics/fingerprint/enroll-jobs
POST /api/v1/biometrics/iris/capture-jobs
GET  /api/v1/jobs/{id}
POST /api/v1/jobs/{id}/cancel
POST /api/v1/patients/registration-drafts
PATCH /api/v1/patients/registration-drafts/{id}
POST /api/v1/patients/registration-drafts/{id}/commit
POST /api/v1/identify
POST /api/v1/verify
GET  /api/v1/patients/{id}
PATCH /api/v1/patients/{id}
GET  /api/v1/patients/{id}/revisions
GET  /api/v1/admin/patients
POST /api/v1/admin/patients/{id}/archive
POST /api/v1/admin/patients/{id}/deletion-requests
GET  /api/v1/admin/staff
GET  /api/v1/admin/audit
GET  /api/v1/admin/sync
POST /api/v1/admin/sync/conflicts/{id}/resolve
```

Use `pending -> running -> waiting_for_finger/eye -> processing -> completed/failed/cancelled/timed_out` style state transitions only where valid; explicit ownership and concurrency limits; idempotent job creation and completion, progress event delivery (polling/SSE appropriate), bounded retries and safe reset/wipe on interruption. Build API contract tests and negative authorization tests.

## 12. TESTING: MOCK MODE, HARDWARE MODE, VALIDATION MODE

Implement honest, distinct run modes:
- `MOCK_MODE=true`: Fully runnable developer demo on PC/CI using simulator-generated **synthetic, explicitly labeled results and records**. Must include controllable low-quality captures, sensor disconnect, timeout, wrong user, ambiguous match, and no-match scenarios. No simulated biometric success should be used to assert real performance.
- `HARDWARE_MODE=true`: Raspberry Pi 5 with attached ESP32/GT-521F32 and Pi Zero W/Camera Module 3. Require explicit detection; fail safely if peripherals absent.
- `VALIDATION_MODE=true`: Controlled enrolled/non-enrolled biometric evaluation with authorized volunteers/test datasets, consent, metrics, pinned model versions and benchmark reporting.

Tests must include:
1. Unit tests: serialization, checksum, packet boundaries, capture state machine, encryption wrappers, role checks, form validation, conflict logic, identity statuses.
2. Contract/integration tests: Pi device API mocks, local Postgres, Supabase stub/test project, sync retries/idempotency, tenant/role isolation, audit integrity.
3. Negative security tests: no cross-role record leakage, no frontend service key, no unaudited update/delete, path traversal/input injection, replay and stale-session requests.
4. E2E UI tests: login, registration order, capture exception, review/commit, retrieval, inconclusive identification, update/revision, admin archive/deletion request, offline mode, reconnection.
5. Hardware tests (opt-in): UART power/baud, template round-trip, scratch wipe, USB CRC/resync, Pi Zero USB enumeration, image quality, Pi 5 model memory/latency/temperature, cable disconnect, startup after power loss.
6. Biometric statistical tests: genuine/impostor pairs, unknown-person 1:N, duplicated subject/finger, wrong-eye, image blur/glare, false-positive ID, false-negative ID, thresholds, per-demographic disparities where ethical and feasible.
7. Backup and disaster recovery tests: local Postgres restore, key availability, sync replay prevention, patient record correction and delete tombstone propagation.

Report both measured results and explicit untested gaps. Define gates: **No live patient use** until independent privacy/security/clinical review, validated biometric error rates, safe emergency fallback and reliable backups.

## 13. PHASED EXECUTION ORDER WITH HARD ACCEPTANCE CRITERIA

### Phase 0 — Source audit and executable plan
- Read and reconcile planning file; inspect four repos and licenses; record pinned SHAs, assumptions, risks and ADRs.
- Produce architecture diagrams, dependency/BOM inventory, threat model, implementation-plan artifact, initial traceability matrix.
- **Gate:** Every required feature has owner/module/tests and unresolved high-risk blockers are visible.

### Phase 1 — Working application foundation
- Scaffold monorepo, developer setup, Flask app, frontend shell, config validation, local Postgres migrations, tests, CI, scripts, seed data, mock adapters and health APIs.
- **Gate:** One-command local startup and tests work with no Pi hardware, Supabase credentials or model weights.

### Phase 2 — Auth, patient data, Supabase and administration
- Staff accounts, three role-based login experiences, permission checks, full patient CRUD with controlled admin deletion, versioning, audit, offline cache, outbox and Supabase test integration.
- **Gate:** End-to-end synthetic registration/retrieval/update/admin actions work securely in mock mode, with tested offline syncing.

### Phase 3 — Fingerprint transport and capture
- Sensor driver adaptation, ESP32 firmware, framed USB protocol, single-owner host worker, enrollment/verify and simulator.
- **Gate:** Contract tests pass; hardware-specific claims marked pending until actual GT-521F32 tests confirm template integrity, scratch wipe and reconnect.

### Phase 4 — Camera transport and capture
- Pi Zero USB Ethernet gadget instructions, camera service, quality pipeline and Pi 5 ingestion.
- **Gate:** JPEG/eye image passes validated on-wire integrity tests; camera quality and optical suitability recorded, not assumed.

### Phase 5 — Iris ML integration
- LightIrisNet segmenter adapter, normalization, real VIS-IrisFormer inference, weight loading/verification, iris quality and matching APIs.
- **Gate:** Reproducible inference on pinned data; CPU/ARM64 and actual sensor image tests clearly separated.

### Phase 6 — Identity search and fusion
- Actual 1:1 verification, careful 1:N shortlist/search, cross-modal confirmation, unknown-person handling and duplicate detection.
- **Gate:** Report measured accuracy and latency; block auto-selection if identification performance is unvalidated.

### Phase 7 — Finished LifeLink GUI
- Fully wire all register/retrieve/update/admin pages to real APIs and jobs; do responsive/accessibility and kiosk testing.
- **Gate:** All three workflows and admin tasks pass browser-based E2E in mock mode, and hardware-specific testing is separately reported.

### Phase 8 — Deployment, reliability, security hardening
- systemd service files, device permissions, setup scripts, secrets, backup/recovery, wired network/firewall, failure playbooks, testing matrix, operating manual.
- **Gate:** Clean Pi 5 install instructions, recoverable offline mode, deterministic reboot behavior, bounded failures, and accurate validation report.

If the environment prevents a phase from being completed, finish independently testable tasks, create a concrete blocker record, and continue work not dependent on that blocker. **Never create a fake passing result to satisfy a milestone.**

## 14. REQUIRED OUTPUT FILES AND ARTIFACTS

Deliver, at minimum:
- Working source tree with reproducible setup commands, pinned dependency lockfiles/versions and non-secret sample environment config.
- `README.md` (project summary and quickstart).
- `AGENTS.md` (short persistent Antigravity workspace rules).
- `docs/requirements-traceability.md`.
- `docs/source-audit.md`, `docs/third-party-audit.md`, `docs/iris-repository-integration.md`.
- `docs/architecture.md`, diagrams and ADRs.
- `docs/wiring.md`, `docs/hardware-bom.md`, `docs/pi-zero-usb-gadget.md`.
- `docs/database-design.md`, local/Supabase migrations and RLS policy notes.
- `docs/api.md`, `docs/usb-serial-protocol.md`, `docs/device-state-machines.md`.
- `docs/security-threat-model.md`, `docs/privacy-and-retention.md`, `docs/emergency-fallbacks.md`.
- `docs/iris-validation.md`, `docs/fingerprint-validation.md` containing actual measured metrics or clearly marked pending items.
- `docs/test-report.md`, `docs/deployment-pi5.md`, `docs/operations-runbook.md` and `docs/remaining-blockers.md`.
- Unit, integration, browser E2E, protocol test vectors, simulators, hardware smoke-test commands, and a synthetic-data demo.
- Antigravity implementation-plan and walkthrough artifacts highlighting real code changes, test outputs and known issues.

Include commands for: `bootstrap`, `migrate`, `seed-demo`, `run-mock`, `run-pi5`, `test`, `lint`, `backup`, `restore-test`, and `health-check`. Use suitable scripts/Makefile targets with help and platform guards; never let demo scripts mutate production records.

## 15. REPORTING FORMAT AFTER EVERY PHASE

At the end of each phase, report:
1. **Implemented** — exact files/modules changed, runnable features and contracts.
2. **Test evidence** — commands executed, results, relevant screenshots/artifacts where available.
3. **Not verified** — absent hardware, missing weights, licensing restrictions, accuracy not measured, untested Pi 5 performance, etc.
4. **Risks / decisions** — unresolved technical blockers and required approvals.
5. **Next implementation milestone** — the next executable set of tasks.

Use terminology precisely: `implemented`, `tested in mock mode`, `tested on real hardware`, `benchmarked on Pi 5`, `unverified`, `blocked`, and `production approval pending` are different states. Do not label the project “medical grade,” “FIPS certified,” “ISO compliant,” or “production ready” based solely on generated software or upstream README claims.

## 16. START NOW — YOUR FIRST ACTIONS

1. Inspect the workspace and find `LifeLink_2.0_Plan.md`; read it in full.
2. Audit the four GitHub iris repositories and any available legacy LifeLink code; compare existing functionality against this prompt.
3. Publish a **Requirements Traceability Matrix**, **Technical Architecture**, **Third-Party/Model Audit**, **Risk Register**, and **phased Implementation Plan** artifact.
4. Create the initial root `AGENTS.md`, project skeleton and mock-mode start/test script.
5. Begin implementation immediately after the plan-review gate, proceeding through phases and providing evidence with each completed milestone.
6. Treat hardware access, clinical deployments, dangerous migrations, model licensing and production credentials as explicit approval gates, while keeping safe, locally testable engineering work moving.

**Final success criterion:** A coherent, source-backed, running LifeLink 3.0 prototype in which the fully wired peripherals (or honest mock adapters) integrate with a Raspberry Pi 5–oriented GUI, the three patient workflows and Admin Dashboard operate through secured backend APIs, local Postgres works offline, optional Supabase synchronization is robust, and biometric matching capability/limitations are reported truthfully with tests—not assumed from documentation.
