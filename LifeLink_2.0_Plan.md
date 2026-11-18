# LifeLink 3.0 — Revised Technical Specification and Implementation Plan

**Project:** Emergency Medical Identity & Patient Information Management System  
**Version:** 3.0 (proposed architecture)  
**Target:** Raspberry Pi 5 touchscreen terminal  
**Design:** Fully wired peripherals, offline-first local operations, optional Supabase cloud synchronization  
**Status:** Design specification; not a claim of medical certification, production readiness, validated matching accuracy, or completed implementation

---

## 1. Project vision

LifeLink 3.0 is a biometric-assisted emergency patient identification and medical record management system. Authorized personnel use a Raspberry Pi 5 touchscreen to register patients, identify existing patients, retrieve their available records, and update authorized information. An administrative dashboard provides controlled patient-data and staff management.

### Goals

- Provide **Clinical Login**, **Hospital Login**, and **Admin Login**, backed by **individual staff accounts** and enforced permissions.
- After standard staff login, provide **Register Patient**, **Retrieve Patient**, and **Update Patient**.
- For registration: **fingerprints → iris scans → patient details → review → save**.
- For retrieval: **capture biometrics → identify/verify patient → display authorized records**.
- For update: **capture biometrics → identify/verify patient → check staff permissions → edit → review → save with history**.
- Add an **Admin Dashboard** with controlled **view, edit, archive/deactivate, and deletion-request** features for existing data.
- Keep **all peripheral connections wired**; do not require Wi-Fi/Bluetooth for hardware links.
- Support **offline local patient workflows** when the external network is unavailable; synchronize approved records to Supabase when connectivity exists.
- Protect biometric data and keep medical information attributable, auditable, and correctable.

### Scope boundary

This design supports clinical information access but **does not independently determine diagnosis or treatment**. Biometric matching and clinical alerts must be validated before real patient use. A failed biometric search does not establish that a patient has no existing record.

---

## 2. Reference architecture: LifeLink 2.0 to 3.0

The supplied `PROJECT_DOCUMENTATION.md` (LifeLink 2.0) specifies an ESP32/GT-521Fx2 fingerprint station, a Pi Zero W/Camera Module 3 Wide NoIR camera unit, a Raspberry Pi 5 Flask touchscreen terminal, a local PostgreSQL biometric database, and Supabase-hosted clinical records. It originally uses a private Wi-Fi access point and HTTP for the fingerprint and camera runtime links.

**LifeLink 3.0 changes:**

| Area | Original design (2.0) | Revised design (3.0 proposal) |
|---|---|---|
| Entry | Standby/home | Clinical, Hospital, or Admin login |
| Main functions | Enrollment and identification | Register, Retrieve, Update, plus Admin Dashboard |
| Fingerprint communication | UART sensor → ESP32; Wi-Fi/HTTP ESP32 → Pi 5 | UART sensor → ESP32; **USB serial** ESP32 → Pi 5 |
| Camera communication | CSI camera → Pi Zero W; Wi-Fi/HTTP to Pi 5 | CSI camera → Pi Zero W; **USB Ethernet gadget** to Pi 5 |
| Data | Local biometrics + Supabase clinical records | Local-first operations + optional Supabase synchronization |
| Matching | 1:1 sensor fingerprint verification; proposed iris similarity | Explicit 1:N candidate search plus 1:1 confirmation; must be validated |
| Administration | Settings/diagnostics | Dedicated patient/staff/audit/device/sync admin module |
| Patient changes | Backend update APIs | Audited, permission-scoped GUI updates and version history |

---

## 3. Hardware architecture — no wireless peripheral links

```text
 GT-521F32 fingerprint sensor
       │  UART (TX/RX/GND and appropriate power)
       ▼
     ESP32 ─────────────── USB data / serial ───────────────┐
                                                            │
 Camera Module 3 Wide NoIR                                  │
       │  CSI ribbon                                        ▼
       ▼                                          RASPBERRY PI 5
  Raspberry Pi Zero W ─ USB Ethernet gadget ──►  - Touchscreen GUI
                                                  - Flask application/API
 Touchscreen ───── DSI or HDMI + USB touch ───►  - Fingerprint device service
                                                  - Iris inference service
                                                  - Local PostgreSQL
                                                  - Sync and audit services
                                                            │
                                                Wired Ethernet (optional)
                                                            │ HTTPS
                                                            ▼
                                                   Supabase Cloud
```

**Important distinction:** “Fully wired” describes physical device communication. **Supabase Cloud still requires internet access**, even if that internet connection is provided by Ethernet. Core local functions should not rely on it.

### Physical interfaces

| Link | Physical interface | Implementation notes |
|---|---|---|
| GT-521F32 ↔ ESP32 | UART | On classic ESP32 DevKit: sensor TX → GPIO16 (RX2), sensor RX → GPIO17 (TX2), common GND; check board specifics |
| Sensor power | Regulated supply | Verify the **specific sensor module’s** voltage, logic-level requirements and ESP32 regulator budget before wiring |
| ESP32 ↔ Pi 5 | USB cable to Pi 5 USB-A host port | Classic ESP32 USB-UART converter usually `/dev/ttyUSB*`; native USB CDC often `/dev/ttyACM*` |
| Camera ↔ Pi Zero W | CSI ribbon | Use correct Pi Zero camera cable and confirm module support/focus/illumination |
| Pi Zero W ↔ Pi 5 | Pi Zero **USB/data** micro-USB port ↔ Pi 5 USB-A | Configure Linux USB gadget Ethernet; use wired private addressing, no Wi-Fi |
| Touchscreen ↔ Pi 5 | DSI or HDMI plus touch input | Depends on exact display |
| Pi 5 ↔ optional hospital/cloud network | Gigabit Ethernet | Network segmentation, HTTPS, service authentication |
| Pi 5 power | Dedicated approved supply | Do not use the Pi 5 USB-C power connector as a peripheral data port |

### Hardware verification gates

1. Confirm exact ESP32 board revision, GPIO availability, USB connector/data support, and sensor electrical requirements.
2. Verify reliable sensor command responses and complete binary template retrieval.
3. Verify Pi Zero W USB Ethernet gadget enumeration, camera operations, and USB power budget.
4. Measure iris image focus, iris pixel count, glare, and actual matching performance; the Camera Module 3 must **not** be assumed clinically suitable without testing.
5. Disable Wi-Fi and Bluetooth during the fully wired runtime, where supported.

---

## 4. Software architecture

| Component | Suggested stack | Responsibility |
|---|---|---|
| Touchscreen client | HTML/CSS/JavaScript in Chromium kiosk | Login, register, retrieve, update, admin UI |
| Core backend | Python Flask | Authz, patient workflows, API orchestration |
| Fingerprint firmware | ESP32 MicroPython; reuse/adapt `fplibMicro.py` | Sensor commands, enrollment, template export, 1:1 matching |
| USB fingerprint host | Python `pyserial` | Exclusive serial-port owner, framing and jobs |
| Camera client | Pi Zero W Python/Picamera2 | Image capture, quality screening and transmission |
| Wired camera transport | Linux USB gadget Ethernet + restricted HTTP API | Pi 5 ↔ Pi Zero W control and image transfer |
| Iris processing | FastAPI, PyTorch, validated model | Segmentation, feature extraction, candidate search/matching |
| Local DB | PostgreSQL with appropriate encryption | Offline patient cache, biometric templates, changes, audit |
| Cloud records | Supabase Postgres/Auth/Storage as appropriate | Central patient records and staff identities |
| Sync worker | Python service with transactional outbox | Retry and reconcile local/remote changes |
| Services | systemd | Startup, supervision, health status |

Only a designated **fingerprint host service** should open the ESP32 serial port. The GUI and Flask endpoints send it jobs rather than competing for `/dev/ttyUSB0`.

---

## 5. Login and role-based access

### Initial screen

1. **Clinical Login** — doctors, nurses, and other authorized clinical users.
2. **Hospital Login** — registration and records staff.
3. **Admin Login** — authorized records and technical administrators.

These are role-based entrances, **not shared passwords**. Every action must be attributable to an individual account.

### Suggested permissions

| Action | Clinical | Hospital | Records admin | System admin |
|---|---|---|---|---|
| Register patients | If authorized | Yes, if assigned | By exception | No default |
| Retrieve patient details | Clinical scope | Limited assigned scope | Approved scope | No default |
| Update clinical information | Within professional privileges | No | No unless independently authorized | No |
| Update demographics/contacts | If assigned | Yes | Yes | No default |
| Archive/deletion requests | No default | No default | Yes, approval-gated | No default |
| Staff/role management | No | No | Restricted | Yes |
| Device maintenance | No | No | No | Yes |
| View audit reports | Limited | Limited | As authorized | Security/technical scope |

Security controls: individual identities, strong authentication, server-side RBAC, field-level checks, short-lived sessions, session lock, login throttling, protected tokens, audit logging, emergency-access policy, and no privileged keys in frontend JavaScript.

**Offline login requirement:** If Supabase Auth is unavailable, use a separately designed and tested secure offline identity method. Do not assume previously cached Supabase sessions solve all offline-login requirements.

---

## 6. Main dashboard

After login, show:

- **Register Patient**
- **Retrieve Patient**
- **Update Patient**
- **Admin Dashboard** only when the account is authorized
- Device readiness: fingerprint sensor, ESP32 serial, camera, Pi Zero link, database, cloud sync status
- Explicit online/offline and last-synced indicators
- Logout / lock screen

---

## 7. Workflow A — Register patient

```text
Staff login → Register
  → Fingerprint enrollment (up to 10 fingers)
  → Iris enrollment (right OD, left OS)
  → Duplicate-patient candidate check
  → Basic, emergency, medical and clinical details
  → Review and confirm
  → Commit to local database
  → Queue appropriate Supabase synchronization
  → Display LifeLink patient ID
```

### 7.1 Fingerprints

- Finger positions: Right thumb/index/middle/ring/little (`R1`–`R5`) and Left thumb/index/middle/ring/little (`L1`–`L5`).
- GT-521F32 captures the finger and performs supported enrollment steps (typically three impressions per enrollment).
- ESP32 retrieves the sensor-proprietary fingerprint template and transports it through USB to the Pi 5.
- Sensor scratch storage is cleared after successful transfer/verification; **verify deletion behavior on actual firmware**.
- Store finger position, quality/capture status, device ID, template format and version, timestamps, and encrypted template.
- Offer retries and documented `Unavailable` exceptions for injury, missing finger, or poor capture.
- Stage registration rather than committing an incomplete patient record as fully enrolled.

The original document describes **498-byte template data**, a temporary enrollment slot **199**, `GetTemplate`/`DeleteID`, and `Verify1_1`. These are implementation assumptions to verify with the exact sensor model and firmware.

### 7.2 Irises

- Capture **OD/right** then **OS/left** with a guided UI.
- Pi 5 instructs Pi Zero W over the USB virtual Ethernet link.
- Pi Zero W captures camera frames in RAM, applies image-quality screening, and sends an accepted image to Pi 5.
- Pi 5 runs segmentation, normalization, feature extraction, and quality checks.
- Store encrypted derived iris templates with eye side and model/version metadata; avoid unnecessary raw iris-image retention.
- If one or both eyes cannot be captured, record the reason and use a controlled exception policy.

The LifeLink 2.0 iris design names **LightIrisNet**, **Daugman normalization**, and **VIS-IrisFormer** with a nominal **0.84** cosine similarity cutoff. These remain **proposed components/parameters until the actual software and accuracy are validated**.

### 7.3 Patient fields

| Section | Examples |
|---|---|
| Basic | Name, DOB, sex/gender as relevant, contact, address, photo, LifeLink ID |
| Emergency | Emergency contacts, relationship, phone numbers, immediate alerts |
| Medical | Allergies, conditions, drugs, doses, surgeries, implanted devices |
| Clinical records | Visits, diagnoses, labs, scans, prescriptions, immunizations, discharge records |
| Provenance | Source of information, author, verification status, record date, last review |

Blood group, allergies, and prescriptions must come from appropriately sourced/verified medical information; do **not** derive them from biometric scans.

### 7.4 Final review and commit

- Confirm required details and biometric capture status.
- Check duplicate candidates and require authorized review of likely matches.
- Generate a permanent patient UUID and readable LifeLink identifier.
- Commit local data transactionally; stage outbound changes in a durable outbox.
- Show success only after the relevant local transaction succeeds; display cloud synchronization separately.

---

## 8. Workflow B — Retrieve existing patient

```text
Staff login → Retrieve
  → Scan fingerprint and/or iris
  → Find candidate patient(s) [1:N identification]
  → Verify candidate [1:1 confirmation and human safeguards]
  → Check staff access permission
  → Display permitted patient summary and records
  → Log access and show data freshness
```

### Crucial distinction: identification versus verification

- **1:1 verification** asks whether a live scan matches a **known** patient record.
- **1:N identification** searches a gallery to determine **which** patient, if any, may match an unknown scan.

The original GT-521F32 design largely specifies **1:1** on-device verification; it also reports concerns with the sensor’s `Identify1_N` function. Therefore, reliable database-wide identification is an **unresolved engineering dependency**, not a completed feature.

### Matching plan

1. **Fingerprint:** Keep sensor-proprietary templates; benchmark loading references into temporary slots and executing native 1:1 comparisons. Test performance at 10, 100, and 1,000+ templates. Do not assume generic OpenCV/software can compare these templates directly.
2. **Iris:** After validating camera/AI, compute embeddings and shortlist candidates locally with a similarity search; verify candidate identities with validated thresholds and quality constraints.
3. **Fusion:** Use additional evidence (second biometric, verified record/photo, staff review) for candidate confirmation, especially when results are ambiguous.
4. **No reliable match:** Offer authorized manual lookup, an unidentified-patient pathway, or controlled emergency access; never silently assign an uncertain identity.

### Retrieval view priorities

Immediately show source-backed critical allergies, relevant current medication, chronic conditions, implants, emergency contacts, and last-verified timestamps. Detailed records remain accessible according to role. Flag outdated/offline-cached records clearly.

---

## 9. Workflow C — Update patient

```text
Staff login → Update
  → Biometric identification or approved alternate identification
  → Identity confirmation
  → Operator privilege check
  → Load permitted editable fields
  → Modify data with reason/source
  → Review difference
  → Save new version locally; queue sync
  → Record audit event
```

- Separate demographic edits from clinical edits.
- Apply field-level authorization and, where needed, clinician approval.
- Preserve record versions and audit metadata (who, what, when, reason).
- Use optimistic concurrency/version numbers and surface synchronization conflicts rather than silently overwriting changes.
- Treat biometric re-enrollment as a separate, privileged process with stronger identity verification.

---

## 10. Admin Dashboard — added requirement

The Admin Dashboard must enable authorized users to **view, edit, and manage deletion of existing data**, as well as manage staff, device status, audits, and database synchronization.

### 10.1 Admin home widgets

- Total registered patient records
- Active versus archived records
- Staff accounts and role counts
- Complete/incomplete biometric enrollment counts
- Pending synchronization and conflicts
- Device connectivity and fault history
- Recent approved administrative actions

### 10.2 Patient Management

Search by LifeLink ID, patient name, or other approved identifier. For each selected record, provide:

- **View:** Basic, emergency, medical and clinical records according to administrator’s access scope; biometric **status/metadata**, not raw templates.
- **Edit:** Open allowed sections, require reason for material modifications, preserve previous versions, and audit the changes.
- **Archive/Deactivate:** Remove the record from normal active workflows without erasing records that must be retained.
- **Delete Request:** Initiate a controlled erasure/retention review; do not allow unguarded irreversible browser-side deletion.
- **Biometric maintenance:** Inspect capture status; invalidate/re-enroll with separate elevated authorization.

### 10.3 Secure deletion workflow

```text
Records admin selects patient → chooses Request Deletion
 → supplies reason → retention/legal-hold checks
 → required additional authorization/approval
 → plan local & Supabase changes
 → archive, anonymize, or lawfully erase as permitted
 → reconcile references, cached records and backups under policy
 → record tamper-evident audit outcome
```

*Why not immediate hard-delete?* Hospital records may be subject to retention obligations, and patient UUIDs link clinical records and biometric references across two databases. Simply deleting a Supabase row could leave identifiable local biometric data or broken associations.

### 10.4 Other admin modules

| Module | Functions |
|---|---|
| Staff and roles | Create/disable accounts, reset access, assign scoped privileges |
| Audit | Search access, edit, export, admin and deletion events |
| Biometric enrollment | View enrollment status; request privileged invalidation/re-enrollment |
| Devices | Fingerprint UART/USB, ESP32, Pi Zero camera, health and calibration status |
| Database and sync | Last sync, failed jobs, conflict resolution, backup and restore status |
| System settings | Retention policies, approved emergency access settings, maintenance |

Distinguish **records administration** from **technical system administration**; system admins should not automatically access full patient histories.

### 10.5 Proposed admin API

```http
GET   /api/admin/patients
GET   /api/admin/patients/{patient_id}
PATCH /api/admin/patients/{patient_id}
POST  /api/admin/patients/{patient_id}/archive
POST  /api/admin/patients/{patient_id}/deletion-requests
GET   /api/admin/staff
POST  /api/admin/staff
PATCH /api/admin/staff/{staff_id}
GET   /api/admin/audit
GET   /api/admin/devices
GET   /api/admin/sync-status
```

Each endpoint requires backend authorization, scoped record access, input validation, and audit events. No direct unrestricted `DELETE` endpoint should be exposed to the frontend.

---

## 11. Database plan: local PostgreSQL + Supabase

**Recommended approach:** A hybrid design, with the local Pi 5 database ensuring offline biometric and emergency-record availability and hosted Supabase supporting centralized approved medical data and staff identities.

### 11.1 Proposed data placement

| Data | Pi 5 local PostgreSQL | Supabase Cloud |
|---|---|---|
| Patient UUID/ID mapping | Yes | Yes |
| Fingerprint templates | **Encrypted primary storage** | Not by default |
| Iris templates | **Encrypted primary storage** | Not by default |
| Basic details | Offline copy | Central copy |
| Emergency/medical details | Controlled offline copy | Central clinical records |
| Clinical history | Selected authorized offline records | Central records |
| Staff identities | Offline access strategy, if required | Supabase Auth/role metadata |
| Audit | Local audit and outbound queue | Authorized central reports/events |
| Sync state | Durable sync outbox and conflict records | Corresponding versions/receipts |

### 11.2 Suggested tables

```text
Local:
  patients_cache
  fingerprint_templates
  iris_templates
  biometric_sessions
  device_jobs
  offline_staff_credentials_or_verifiers  [only if securely designed]
  clinical_cache
  audit_events
  sync_outbox
  sync_conflicts
  record_versions

Supabase:
  patients
  emergency_contacts
  allergies
  medical_history
  medications
  surgeries
  medical_devices
  clinical_records
  staff_profiles
  roles
  role_assignments
  patient_status_history
  record_revisions
  deletion_requests
  audit_events
```

These are conceptual names. Normalize schema and foreign keys during implementation. Keep a stable UUID mapping between systems.

### 11.3 Offline and synchronization rules

1. Local operations do **not** require Wi-Fi or internet.
2. Cloud operations require working **wired Ethernet plus internet** to reach hosted Supabase.
3. Queue authorized offline writes in a transactional local outbox.
4. Retry idempotently with operation IDs; never duplicate registrations because of a retransmission.
5. Use version numbers/ETags and explicit conflict resolution; do not blindly choose last write for clinically significant data.
6. Display **last synchronized at** and source-of-truth/freshness status to staff.
7. Define merge, archive, restoration, and deletion semantics across both databases.
8. Back up and test recovery for both local operational data and hosted records.

**Alternative:** Self-hosted Supabase on a dedicated wired hospital server is possible, but entails operating the full service stack and is not part of the minimum Pi 5 prototype.

---

## 12. Wire protocols and device services

### 12.1 ESP32 USB serial protocol

Use structured binary framing, e.g.:

```text
MAGIC | VERSION | REQUEST_ID | COMMAND | PAYLOAD_LENGTH | PAYLOAD | CRC
```

Supported logical actions:

| Action | Meaning |
|---|---|
| `HELLO` | Identify firmware/device/protocol version |
| `STATUS` | Read sensor readiness and firmware metadata |
| `ENROLL` | Start a guided enrollment sequence |
| `CAPTURE` | Acquire a live finger sample |
| `GET_TEMPLATE` | Transfer a previously generated template |
| `LOAD_TEMPLATE` | Load a temporary reference template for comparison |
| `VERIFY` | Request on-sensor 1:1 comparison |
| `CANCEL` | Stop the active operation safely |
| `CLEAR_SLOTS` | Clear temporary sensor references |

Include ACK/NACK, length bounds, checksums, job IDs, timeout/retry behavior, disconnect recovery, and cancellation rules. Encrypt/protect sensitive payloads appropriately; avoid exposing them in logs. The Pi 5 host service must exclusively own the serial port.

### 12.2 Pi Zero W camera protocol

Use authenticated HTTP **over the USB Ethernet gadget link**, restricted to that wired interface. Proposed endpoints:

```http
GET  /health
POST /camera/iris/capture
POST /camera/photo/capture
GET  /camera/jobs/{job_id}
POST /camera/jobs/{job_id}/cancel
```

Support job status, bounded upload sizes, capture quality, timeouts, retries, and clear errors. Keep the camera client powered and idle between captures instead of shutting it down after each success; operating-system shutdown alone does not guarantee unattended restart.

---

## 13. Privacy, security, and clinical safeguards

- **Data minimization:** store only necessary biometric templates, clinical details, and appropriate evidence.
- **Encryption:** encrypt sensitive local data and backups at rest; protect encryption keys outside ordinary application tables.
- **Access control:** individual accounts, per-action/backend checks, scopes, privileged administrative approvals.
- **Audit:** log patient record access, edits, exports, emergency overrides, re-enrollment, archives and deletions without storing raw templates in logs.
- **Privacy policy:** define lawful basis, notice/consent where applicable, purpose limits, retention, export, correction and erasure handling according to applicable law and hospital policy.
- **Device security:** wipe temporary sensor slots after use and validate actual erase behavior; protect USB interfaces and camera API.
- **Clinical provenance:** identify source, author, verification status and age of medically relevant information.
- **Clinical decisions:** present allergy and medication warnings as source-backed information for trained personnel, not autonomous treatment instructions.
- **Patient-safety fallback:** enable approved manual lookup and temporary unidentified-patient records when sensors fail or an injury prevents capture.
- **No automatic identity assignment** from ambiguous or low-quality biometric matches.
- **Security review:** threat model, penetration testing, retention review, backup recovery drill, and independent validation before live clinical deployment.

---

## 14. Failure-handling requirements

| Scenario | Required behavior |
|---|---|
| Sensor disconnected | Surface error and allow controlled fallback; preserve pending workflow |
| Camera unusable | Mark capture unavailable; continue according to approved exception policy |
| Scan is low quality | Guided retry; never fabricate a valid template |
| Multiple patient candidates | Inconclusive status and enhanced confirmation |
| No match | Manual search or temporary identity flow; no false “not registered” assertion |
| Internet outage | Continue local authorized workflows; show stale/sync status |
| Power loss during registration | Transaction-safe local database; recover drafts; no false success |
| Two staff edit same record | Version conflict and review, not silent overwrite |
| Sync failure | Durable queue and retries with visible status |
| Unauthorized admin action | Reject server-side and audit attempted access |
| Deletion requested | Verify retention and approval requirements before any erasure |
| Offline authentication unavailable | Display explicit restriction and supported emergency protocol |

---

## 15. Phased implementation roadmap

### Phase 1 — Hardware and wired transport

- Verify sensor electrical interface and GT-521F32 protocol.
- Receive complete template bytes on ESP32 and forward intact to Pi 5 by USB.
- Configure Pi Zero W USB Ethernet and capture/transfer a photo.
- Verify touchscreen and independent power supplies.

**Acceptance:** Reproducible, checksum-valid transfers, stable camera operation, reconnect after cable removal, no Wi-Fi required.

### Phase 2 — Enrollment and local database

- Build ten-finger guided enrollment with exceptions.
- Build right/left iris capture and quality checks.
- Encrypt and store templates using a stable patient UUID.
- Test cancellation, cleanup, draft recovery and transaction rollback.

**Acceptance:** Repeatable enrollment and valid on-device template round trip; no unintended retained sensor templates.

### Phase 3 — Biometric verification and identity search

- Implement reliable 1:1 fingerprint verification.
- Validate iris camera/model pipeline and 1:1 matching.
- Design/test 1:N candidate search; benchmark 10, 100, 1,000+ references.
- Measure false match/rejection and failure-to-acquire rates; test ambiguous results.

**Acceptance:** Predefined measured identification quality and latency targets, with safe inconclusive outcomes. If this cannot be demonstrated, restrict the prototype to known-ID 1:1 verification and manual search.

### Phase 4 — Backend and synchronization

- Implement staff authentication and role/field permissions.
- Build PostgreSQL schemas and API transactions.
- Integrate Supabase through backend credentials and row-level policies as applicable.
- Implement outbox retry, conflict handling, backups, and audit events.

**Acceptance:** No unauthorized reads/edits in test suite; controlled offline operation; tested backup restore and sync-conflict handling.

### Phase 5 — GUI and Admin Dashboard

- Build three login entrances, staff dashboard and patient workflows.
- Build Admin Patient Management (view/edit/archive/deletion request).
- Add staff/role tools, audit search, device status and sync dashboard.
- Test touchscreen accessibility, guided scans, and error states.

**Acceptance:** End-to-end demonstration with fictional records and enforced authorization.

### Phase 6 — Reliability, privacy and clinical evaluation

- Hardware disconnection and power-loss drills.
- Usability and emergency fallback tests.
- Biometric accuracy and demographic performance assessment.
- Privacy/legal retention and security review.
- Clinical record accuracy/provenance and safety evaluation.

**Acceptance:** Documented evidence and appropriate organizational approvals before any real medical deployment.

---

## 16. Proposed quality metrics (to validate)

| Metric | Initial quality goal |
|---|---|
| Binary transfer | Detect and reject corrupt/incomplete templates |
| Hardware recovery | Recover gracefully after reconnect |
| Local transaction durability | No half-committed patient profile |
| Permission testing | No unauthorized access accepted in defined tests |
| Audit coverage | Every sensitive record access/change attributable |
| Biometric accuracy | Establish validated operating thresholds; no untested `0.84` default |
| 1:N performance | Benchmark on realistic gallery sizes |
| Offline operation | Verified without WAN connectivity |
| Database restore | Demonstrated recovery from usable backup |
| Sync conflicts | Detect and resolve; never silently overwrite critical medical updates |

---

## 17. Open decisions and dependencies

1. Exact ESP32 board, connection type (classic USB-UART or native CDC), and firmware environment.
2. Exact GT-521F32 module voltage specifications, firmware revision, and scratch-slot behavior.
3. Pi Zero W Camera Module 3 image quality at intended eye distance; alternative optics if needed.
4. Validated fingerprint and iris **1:N** search technique, scale, accuracy, and confidence logic.
5. Whether the deployment is one Pi 5 terminal, multiple terminals in one hospital, or multiple hospitals (affects sync, identifiers, consent, and access scopes).
6. Offline staff authentication and how emergency access is governed.
7. Local cache policy: which clinical data and how much history must be available offline.
8. Definition of authorized administrators and approval required for deletion, clinical corrections, and biometric re-enrollment.
9. Regulatory jurisdiction, hospital retention requirements, backup retention and incident reporting.
10. Operating system/image versions and installation tooling to be tested rather than assumed.

---

## 18. Suggested directory layout (proposed)

```text
LifeLink/
├── frontend/
│   ├── login/
│   ├── dashboard/
│   ├── registration/
│   ├── retrieval/
│   ├── update/
│   └── admin/
├── backend/
│   ├── app.py
│   ├── auth/
│   ├── patients/
│   ├── admin/
│   ├── biometrics/
│   ├── devices/
│   ├── sync/
│   └── audit/
├── fingerprint-device/
│   ├── fplibMicro.py
│   ├── firmware/
│   │   ├── main.py
│   │   ├── modes.py
│   │   └── usb_protocol.py
│   └── pi5/
│       └── fingerprint_serial.py
├── iris-module/
│   ├── camera-client/
│   ├── engine/
│   └── usb-config/
├── database/
│   ├── schema.sql
│   └── migrations/
└── docs/
    └── LifeLink_3.0_Revised_Technical_Specification.md
```

---

## 19. Recommended first end-to-end demonstration

With synthetic patient data and consented test biometrics:

1. Enroll one fingerprint and one iris for a test identity.
2. Transfer fingerprint over GT-521F32 → ESP32 UART → USB → Pi 5.
3. Transfer eye image over CSI → Pi Zero W → USB gadget → Pi 5.
4. Encrypt and store the templates locally.
5. Verify a fresh sample against the known test identity (1:1).
6. Retrieve a fictional patient record with the correct permissions.
7. Modify one permitted field, record its revision, and confirm it updates locally.
8. Request an archive/deletion workflow from Admin Dashboard (without unapproved hard deletion).
9. Turn off network access; repeat local retrieval and show pending Supabase sync.
10. Restore wired Ethernet/internet and demonstrate safe synchronization.

Expand to 1:N identification only after a tested and validated matching approach is available.

---

## 20. Source and status notes

- **Source basis:** User-provided LifeLink 2.0 `PROJECT_DOCUMENTATION.md` and subsequent LifeLink 3.0 design requirements discussed in this conversation.
- **Retained from the original specification:** ESP32 + GT-521Fx2 fingerprint device, Pi Zero W camera, Pi 5 Flask UI, fingerprint enrollment and 1:1 comparison concept, iris pipeline names, PostgreSQL local biometric storage, Supabase patient-record concept.
- **New proposals:** All-wired runtime, three login entrances, three primary staff workflows, dedicated Admin Dashboard, local-first cloud synchronization, controlled deletion workflow, explicit 1:N design and acceptance gates.
- **Unverified claims:** Sensor template layout and firmware quirks must be checked on actual hardware; iris model availability and accuracy must be demonstrated; database security and medical suitability require independent testing. This document is a plan, not a record of completed tests.

**Summary:** Build LifeLink 3.0 as a *wired, offline-first, role-based patient identification platform* with local encrypted biometrics, Supabase-backed centralized records, secure administrative management, and experimentally verified matching before clinical deployment.
