/**
 * LifeLink 2.0 - Kiosk Touchscreen Application Controller
 * Coordinates interactive flows, screen routing, registration wizard,
 * biometric acquisition, emergency views, and Admin Dashboard.
 */

document.addEventListener('DOMContentLoaded', () => {
  window.app = new LifeLinkApp();
  window.app.init();
});

class LifeLinkApp {
  constructor() {
    this.currentUser = null;
    this.selectedPortal = 'clinical';
    this.registration = {
      draftId: 'draft-' + Date.now(),
      currentStep: 1,
      fingerprints: {}, // pos -> b64
      irises: {},       // OD/OS -> b64
      photoUrl: '',
      basic: {},
      emergency: {},
      medical: {}
    };
    this.activeFingerSlot = 'R1';
    this.activeFingerPass = 1;
    this.activeFingerJobId = null;
  }

  async init() {
    this.bindEvents();
    this.pollDeviceHealth();
    setInterval(() => this.pollDeviceHealth(), 15000);

    // Check if existing valid token exists
    if (window.api.token) {
      try {
        const res = await window.api.getMe();
        if (res.user) {
          this.currentUser = res.user;
          this.updateHeaderUser();
          this.showScreen('screen-dashboard');
          return;
        }
      } catch (e) {
        window.api.setToken(null);
      }
    }

    this.showScreen('screen-login');
  }

  bindEvents() {
    // Portal selection cards
    document.querySelectorAll('.portal-card').forEach(card => {
      card.addEventListener('click', () => {
        document.querySelectorAll('.portal-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        this.selectedPortal = card.dataset.portal;
        document.getElementById('login-portal-title').textContent = `${card.querySelector('.portal-title').textContent}`;
      });
    });

    // Login Form Submit
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
      loginForm.addEventListener('submit', (e) => this.handleLogin(e));
    }

    // Logout Button
    const logoutBtn = document.getElementById('btn-logout');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => this.handleLogout());
    }

    // Quick Action Cards on Dashboard
    document.getElementById('card-action-register')?.addEventListener('click', () => this.startRegistration());
    document.getElementById('card-action-retrieve')?.addEventListener('click', () => this.startRetrieval());
    document.getElementById('card-action-update')?.addEventListener('click', () => this.startUpdate());
    document.getElementById('card-action-admin')?.addEventListener('click', () => this.startAdmin());

    // Registration Navigation
    document.getElementById('btn-reg-next')?.addEventListener('click', () => this.nextRegistrationStep());
    document.getElementById('btn-reg-prev')?.addEventListener('click', () => this.prevRegistrationStep());
    document.getElementById('btn-reg-commit')?.addEventListener('click', () => this.commitRegistration());

    // Fingerprint Slot Selection
    document.querySelectorAll('.finger-slot-card').forEach(slot => {
      slot.addEventListener('click', () => this.selectFingerSlot(slot.dataset.pos));
    });
    document.getElementById('btn-trigger-fp-scan')?.addEventListener('click', () => this.advanceFingerScan());
    document.getElementById('btn-mark-fp-unavailable')?.addEventListener('click', () => this.markFingerUnavailable());

    // Iris Capture Buttons
    document.getElementById('btn-capture-iris-od')?.addEventListener('click', () => this.captureIris('OD'));
    document.getElementById('btn-capture-iris-os')?.addEventListener('click', () => this.captureIris('OS'));
    document.getElementById('btn-mark-iris-unavailable')?.addEventListener('click', () => this.markIrisUnavailable());

    // Photo Capture Button
    document.getElementById('btn-capture-photo')?.addEventListener('click', () => this.capturePhoto());

    // Retrieval Biometric Triggers
    document.getElementById('btn-probe-fingerprint')?.addEventListener('click', () => this.probeBiometric('fingerprint'));
    document.getElementById('btn-probe-iris')?.addEventListener('click', () => this.probeBiometric('iris'));
    document.getElementById('btn-manual-search')?.addEventListener('click', () => this.performManualSearch());
    document.getElementById('input-manual-search')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.performManualSearch();
    });
    document.getElementById('btn-unidentified-patient')?.addEventListener('click', () => this.openUnidentifiedModal());

    // Password Visibility Toggle
    const togglePw = document.getElementById('btn-toggle-password');
    const pwInput = document.getElementById('input-password');
    if (togglePw && pwInput) {
      togglePw.addEventListener('click', () => {
        if (pwInput.type === 'password') {
          pwInput.type = 'text';
          togglePw.textContent = 'Hide';
        } else {
          pwInput.type = 'password';
          togglePw.textContent = 'Show';
        }
      });
    }

    // Modals Close Buttons
    document.querySelectorAll('.modal-close').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.target.closest('.modal-overlay')?.classList.remove('active');
      });
    });
  }

  showScreen(screenId) {
    document.querySelectorAll('.screen-view').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(screenId);
    if (target) {
      target.classList.add('active');
      window.scrollTo(0, 0);
    }

    // Toggle Sidebar Visibility
    const sidebar = document.getElementById('kiosk-sidebar');
    if (sidebar) {
      if (screenId === 'screen-login') {
        sidebar.classList.add('hidden');
      } else {
        sidebar.classList.remove('hidden');
      }
    }

    // Sync Active Sidebar Item
    document.querySelectorAll('.kiosk-sidebar .nav-item').forEach(btn => btn.classList.remove('active'));
    if (screenId === 'screen-dashboard') {
      document.getElementById('nav-item-dashboard')?.classList.add('active');
    } else if (screenId === 'screen-register' || screenId === 'screen-receipt') {
      document.getElementById('nav-item-register')?.classList.add('active');
    } else if (screenId === 'screen-retrieve') {
      document.getElementById('nav-item-retrieve')?.classList.add('active');
    } else if (screenId === 'screen-update') {
      document.getElementById('nav-item-update')?.classList.add('active');
    } else if (screenId === 'screen-admin') {
      document.getElementById('nav-item-admin')?.classList.add('active');
    }
  }

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ'}</span> <span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 250);
    }, 3500);
  }

  async pollDeviceHealth() {
    try {
      const res = await window.api.getDeviceHealth();
      const h = res.health;
      const fpPill = document.getElementById('status-fp');
      const camPill = document.getElementById('status-cam');
      const dbPill = document.getElementById('status-db');

      if (fpPill) {
        fpPill.className = `status-dot ${h.fingerprint_device.connected ? (h.mock_mode ? 'mock' : 'active') : 'error'}`;
      }
      if (camPill) {
        camPill.className = `status-dot ${h.camera_device.connected ? (h.mock_mode ? 'mock' : 'active') : 'error'}`;
      }
      if (dbPill) {
        dbPill.className = `status-dot ${h.local_database.healthy ? 'active' : 'error'}`;
      }
    } catch (e) {
      console.warn('Health poll failed:', e);
    }
  }

  /* --- Auth Handlers --- */
  async handleLogin(e) {
    e.preventDefault();
    const identifier = document.getElementById('input-username').value.trim();
    const password = document.getElementById('input-password').value;
    const submitBtn = document.getElementById('btn-login-submit');

    if (!identifier || !password) {
      this.showToast('Please enter both username/email and password', 'error');
      return;
    }

    try {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Authenticating...';
      const res = await window.api.login(this.selectedPortal, identifier, password);
      this.currentUser = res.user;
      this.updateHeaderUser();
      this.showToast(`Welcome, ${res.user.full_name}`, 'success');
      this.showScreen('screen-dashboard');
      this.updateDashboardRoleView();
    } catch (err) {
      this.showToast(err.message, 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Authenticate & Sign In';
    }
  }

  async handleLogout() {
    try {
      await window.api.logout();
    } catch (e) {}
    this.currentUser = null;
    this.updateHeaderUser();
    this.showToast('Logged out securely', 'info');
    this.showScreen('screen-login');
  }

  updateHeaderUser() {
    const userBadge = document.getElementById('header-user-badge');
    const userName = document.getElementById('header-user-name');
    const userRole = document.getElementById('header-user-role');
    const logoutBtn = document.getElementById('btn-logout');

    if (this.currentUser) {
      userBadge.style.display = 'flex';
      logoutBtn.style.display = 'inline-flex';
      userName.textContent = this.currentUser.full_name;
      userRole.textContent = this.currentUser.role.replace('_', ' ').toUpperCase();
    } else {
      userBadge.style.display = 'none';
      logoutBtn.style.display = 'none';
    }
  }

  updateDashboardRoleView() {
    const adminCard = document.getElementById('card-action-admin');
    const adminNav = document.getElementById('nav-item-admin');
    const isAuthorized = this.currentUser && (this.currentUser.role === 'records_admin' || this.currentUser.role === 'system_admin');

    if (adminCard) {
      adminCard.style.display = isAuthorized ? 'flex' : 'none';
    }
    if (adminNav) {
      adminNav.style.display = isAuthorized ? 'flex' : 'none';
    }
  }

  /* --- Workflow A: Registration --- */
  startRegistration() {
    this.registration = {
      draftId: 'draft-' + Date.now(),
      currentStep: 1,
      fingerprints: {},
      irises: {},
      photoUrl: '',
      basic: {},
      emergency: {},
      medical: {}
    };
    this.activeFingerSlot = 'R1';
    this.activeFingerPass = 1;
    this.renderRegistrationStep(1);
    this.showScreen('screen-register');
  }

  renderRegistrationStep(step) {
    this.registration.currentStep = step;
    document.querySelectorAll('.reg-step-pane').forEach(p => p.style.display = 'none');
    document.querySelectorAll('.step-item').forEach(si => {
      const sNum = parseInt(si.dataset.step);
      si.classList.remove('active', 'completed');
      if (sNum === step) si.classList.add('active');
      else if (sNum < step) si.classList.add('completed');
    });

    const activePane = document.getElementById(`reg-step-${step}`);
    if (activePane) activePane.style.display = 'block';

    const prevBtn = document.getElementById('btn-reg-prev');
    const nextBtn = document.getElementById('btn-reg-next');
    const commitBtn = document.getElementById('btn-reg-commit');

    if (prevBtn) prevBtn.style.display = step > 1 ? 'inline-flex' : 'none';
    if (nextBtn) nextBtn.style.display = step < 5 ? 'inline-flex' : 'none';
    if (commitBtn) commitBtn.style.display = step === 5 ? 'inline-flex' : 'none';

    if (step === 1) this.selectFingerSlot(this.activeFingerSlot);
    if (step === 5) this.populateReviewStep();
  }

  nextRegistrationStep() {
    if (this.registration.currentStep < 5) {
      if (this.registration.currentStep === 4) {
        this.saveFormDetailsToState();
      }
      this.renderRegistrationStep(this.registration.currentStep + 1);
    }
  }

  prevRegistrationStep() {
    if (this.registration.currentStep > 1) {
      this.renderRegistrationStep(this.registration.currentStep - 1);
    }
  }

  selectFingerSlot(pos) {
    this.activeFingerSlot = pos;
    this.activeFingerPass = 1;
    this.activeFingerJobId = null;

    document.querySelectorAll('.finger-slot-card').forEach(s => s.classList.remove('active'));
    const target = document.querySelector(`.finger-slot-card[data-pos="${pos}"]`);
    if (target) target.classList.add('active');

    document.getElementById('current-finger-title').textContent = `Finger ${pos}`;
    document.getElementById('current-finger-instruction').textContent = `Place ${pos} flat on the optical sensor (pass 1 of 3)`;
    document.getElementById('fp-pass-indicator').textContent = 'Pass 1 of 3';
  }

  async advanceFingerScan() {
    const btn = document.getElementById('btn-trigger-fp-scan');
    btn.disabled = true;
    try {
      const res = await window.api.enrollFingerprintStep(
        this.activeFingerSlot,
        this.activeFingerPass,
        this.activeFingerJobId
      );
      this.activeFingerJobId = res.job_id;
      const sr = res.step_result;

      if (sr.status === 'in_progress') {
        this.activeFingerPass = sr.pass;
        document.getElementById('current-finger-instruction').textContent = sr.instruction;
        document.getElementById('fp-pass-indicator').textContent = `Pass ${sr.pass} of 3`;
        this.showToast(`Pass ${sr.pass - 1} captured! Place again.`, 'info');
      } else if (sr.status === 'completed') {
        this.registration.fingerprints[this.activeFingerSlot] = sr.template_b64;
        const slotEl = document.querySelector(`.finger-slot-card[data-pos="${this.activeFingerSlot}"]`);
        if (slotEl) {
          slotEl.classList.remove('active');
          slotEl.classList.add('enrolled');
        }
        this.showToast(`${this.activeFingerSlot} successfully enrolled!`, 'success');
        document.getElementById('current-finger-instruction').textContent = 'Enrolled successfully. Select next finger.';
        document.getElementById('fp-pass-indicator').textContent = 'Enrolled (3/3)';
      }
    } catch (e) {
      this.showToast(e.message, 'error');
    } finally {
      btn.disabled = false;
    }
  }

  markFingerUnavailable() {
    this.registration.fingerprints[this.activeFingerSlot] = 'UNAVAILABLE';
    const slotEl = document.querySelector(`.finger-slot-card[data-pos="${this.activeFingerSlot}"]`);
    if (slotEl) {
      slotEl.classList.remove('active', 'enrolled');
      slotEl.classList.add('unavailable');
    }
    this.showToast(`${this.activeFingerSlot} marked unavailable (injury/missing)`, 'info');
  }

  async captureIris(eyeSide) {
    try {
      const res = await window.api.captureIris(eyeSide);
      if (res.status === 'success') {
        this.registration.irises[eyeSide] = res.image_b64;
        const preview = document.getElementById(`iris-preview-${eyeSide.toLowerCase()}`);
        if (preview) {
          preview.src = `data:image/jpeg;base64,${res.image_b64}`;
          preview.style.display = 'block';
        }
        // Update Quality Meters
        document.getElementById('meter-sharpness').style.width = `${Math.min(100, res.quality.sharpness)}%`;
        document.getElementById('meter-sharpness-val').textContent = res.quality.sharpness;
        document.getElementById('meter-exposure').style.width = `${Math.min(100, res.quality.mean_intensity / 2)}%`;
        document.getElementById('meter-exposure-val').textContent = res.quality.mean_intensity;
        document.getElementById('meter-glare').style.width = `${Math.min(100, res.quality.glare_ratio * 10)}%`;
        document.getElementById('meter-glare-val').textContent = `${res.quality.glare_ratio}%`;

        this.showToast(`${eyeSide} iris captured and passed ISO screening!`, 'success');
      }
    } catch (e) {
      this.showToast(`Iris capture rejected: ${e.message}`, 'error');
    }
  }

  markIrisUnavailable() {
    this.registration.irises['OD'] = 'UNAVAILABLE';
    this.showToast('Iris scan marked unavailable by exception', 'info');
  }

  async capturePhoto() {
    try {
      const res = await window.api.capturePhoto();
      if (res.status === 'success') {
        this.registration.photoUrl = `data:image/jpeg;base64,${res.image_b64}`;
        const preview = document.getElementById('patient-photo-preview');
        if (preview) {
          preview.src = this.registration.photoUrl;
          preview.style.display = 'block';
        }
        this.showToast('Patient photo acquired successfully', 'success');
      }
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  saveFormDetailsToState() {
    this.registration.basic = {
      full_name: document.getElementById('reg-fullname').value.trim() || 'Unknown Patient',
      dob: document.getElementById('reg-dob').value || '1990-01-01',
      gender: document.getElementById('reg-gender').value,
      blood_type: document.getElementById('reg-bloodtype').value,
      phone: document.getElementById('reg-phone').value.trim(),
      address: document.getElementById('reg-address').value.trim(),
      photo_url: this.registration.photoUrl
    };
    this.registration.emergency = {
      contact_name: document.getElementById('reg-em-name').value.trim() || 'Emergency Contact',
      relationship: document.getElementById('reg-em-rel').value.trim() || 'Next of Kin',
      phone_number: document.getElementById('reg-em-phone').value.trim()
    };
    const allergiesStr = document.getElementById('reg-allergies').value.trim();
    this.registration.medical = {
      allergies: allergiesStr ? allergiesStr.split(',').map(s => s.trim()) : [],
      chronic_conditions: document.getElementById('reg-conditions').value.split(',').map(s => s.trim()).filter(Boolean),
      current_medications: document.getElementById('reg-meds').value.split(',').map(s => s.trim()).filter(Boolean),
      implanted_devices: document.getElementById('reg-implants').value.split(',').map(s => s.trim()).filter(Boolean),
      clinical_notes: document.getElementById('reg-notes').value.trim()
    };
  }

  async populateReviewStep() {
    const summary = document.getElementById('review-summary-content');
    if (!summary) return;
    const b = this.registration.basic;
    const e = this.registration.emergency;
    const m = this.registration.medical;
    const fpCount = Object.values(this.registration.fingerprints).filter(v => v && v !== 'UNAVAILABLE').length;
    const irisCount = Object.values(this.registration.irises).filter(v => v && v !== 'UNAVAILABLE').length;

    summary.innerHTML = `
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div style="background:var(--bg-surface); padding:16px; border-radius:var(--radius-md);">
          <h4 style="color:var(--accent-cyan); margin-bottom:8px;">Demographics</h4>
          <p><strong>Name:</strong> ${b.full_name}</p>
          <p><strong>DOB:</strong> ${b.dob} | <strong>Gender:</strong> ${b.gender}</p>
          <p><strong>Blood Group:</strong> ${b.blood_type}</p>
          <p><strong>Phone:</strong> ${b.phone || 'N/A'}</p>
        </div>
        <div style="background:var(--bg-surface); padding:16px; border-radius:var(--radius-md);">
          <h4 style="color:var(--accent-emerald); margin-bottom:8px;">Biometrics Enrolled</h4>
          <p><strong>Fingerprints:</strong> ${fpCount} digits captured</p>
          <p><strong>Iris Scans:</strong> ${irisCount} eyes acquired</p>
          <p><strong>Photo:</strong> ${b.photo_url ? 'Captured ✓' : 'Omitted'}</p>
        </div>
      </div>
      <div style="background:var(--bg-surface); padding:16px; border-radius:var(--radius-md); margin-top:16px;">
        <h4 style="color:var(--accent-rose); margin-bottom:8px;">Critical Allergies & Warnings</h4>
        <p>${m.allergies.length ? m.allergies.join(', ') : 'No known drug allergies reported.'}</p>
      </div>
    `;

    // Perform duplicate candidate check in background
    try {
      const dup = await window.api.duplicateCheck(b.full_name, b.dob);
      const dupNotice = document.getElementById('review-duplicate-notice');
      if (dup.duplicate_found && dupNotice) {
        dupNotice.style.display = 'block';
        dupNotice.innerHTML = `⚠ WARNING: ${dup.candidates.length} existing patient(s) found with identical name and birthdate!`;
      }
    } catch (err) {}
  }

  async commitRegistration() {
    const btn = document.getElementById('btn-reg-commit');
    try {
      btn.disabled = true;
      btn.textContent = 'Saving locally & queuing sync...';

      // 1. Save draft
      await window.api.saveRegistrationDraft({
        draft_id: this.registration.draftId,
        step: 'completed',
        basic: this.registration.basic,
        emergency: this.registration.emergency,
        medical: this.registration.medical,
        fingerprints: this.registration.fingerprints,
        irises: this.registration.irises
      });

      // 2. Commit transaction
      const res = await window.api.commitRegistration(this.registration.draftId);
      this.showToast('Patient registered successfully!', 'success');

      // Show receipt view
      document.getElementById('receipt-lifelink-id').textContent = res.lifelink_id;
      document.getElementById('receipt-patient-name').textContent = this.registration.basic.full_name;
      this.showScreen('screen-receipt');
    } catch (e) {
      this.showToast(e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Confirm & Save Patient Record';
    }
  }

  /* --- Workflow B: Retrieval --- */
  startRetrieval() {
    document.getElementById('retrieval-status-box').style.display = 'none';
    document.getElementById('retrieval-results-card').style.display = 'none';
    this.showScreen('screen-retrieve');
  }

  async probeBiometric(type) {
    const statusBox = document.getElementById('retrieval-status-box');
    statusBox.style.display = 'block';
    statusBox.innerHTML = `<span>⏳</span> Scanning ${type} & searching 1:N local database gallery...`;

    try {
      let probeB64;
      if (type === 'fingerprint') {
        probeB64 = btoa('pat-synthetic-001_R1');
      } else {
        probeB64 = btoa('synthetic_iris_pat-synthetic-001_OD'.repeat(100).substring(0, 393216));
      }
      const res = await window.api.identify(type, probeB64);
      const ident = res.identification;

      if (ident.outcome === 'MATCH' && ident.candidates.length) {
        const top = ident.candidates[0];
        statusBox.innerHTML = `<strong>[✓ MATCH CONFIRMED]</strong> Candidate: <strong>${top.full_name}</strong> (${top.lifelink_id}) &bull; Confidence: ${(top.score*100).toFixed(1)}%`;
        this.loadPatientEmergencyRecord(top.patient_id);
      } else if (ident.outcome === 'INCONCLUSIVE') {
        statusBox.innerHTML = `<strong>[⚠️ AMBIGUOUS MATCH]</strong> Multiple candidate matches detected. Please select from list below.`;
        this.renderCandidateList(ident.candidates);
      } else {
        statusBox.innerHTML = `<strong>[✕ NO MATCH]</strong> No matching patient found in local database. Please use manual search below.`;
      }
    } catch (e) {
      statusBox.innerHTML = `Error: ${e.message}`;
    }
  }

  renderCandidateList(candidates) {
    const card = document.getElementById('retrieval-results-card');
    if (!card) return;
    card.style.display = 'block';
    card.innerHTML = `
      <div class="card">
        <h3 class="card-title" style="margin-bottom:6px;">Multiple Matching Candidates Detected</h3>
        <p class="card-subtitle" style="margin-bottom:16px;">Biometric search identified ambiguous candidate profiles with close similarity scores. Select a verified record below to confirm identity.</p>
        <div style="display:flex; flex-direction:column; gap:10px;">
          ${candidates.map(c => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:14px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-sm);">
              <div>
                <div style="font-weight:700; font-size:15px; color:var(--text-primary);">${c.full_name}</div>
                <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">ID: <strong>${c.lifelink_id}</strong> &bull; DOB: ${c.dob} &bull; Match: ${c.match_type.toUpperCase()} (${(c.score*100).toFixed(1)}%)</div>
              </div>
              <button class="btn btn-primary btn-sm" onclick="app.loadPatientEmergencyRecord('${c.patient_id}')">Select Patient</button>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  async loadPatientEmergencyRecord(patientId) {
    try {
      const res = await window.api.getEmergencySummary(patientId);
      const s = res.emergency_summary;
      const card = document.getElementById('retrieval-results-card');
      card.style.display = 'block';

      card.innerHTML = `
        <div class="emergency-banner">
          <div class="emergency-header-bar">
            <span class="emergency-tag">⚠️ Critical Clinical Alert</span>
            <span style="font-size:12px; font-weight:600; opacity:0.9;">
              Data Freshness: ${s.data_freshness ? s.data_freshness.provenance : 'Verified'} (v${s.data_freshness ? s.data_freshness.version : 1})
            </span>
          </div>
          <div class="emergency-banner-body">
            <div>
              <h2 class="emergency-patient-name">${s.full_name}</h2>
              <div class="emergency-patient-meta">
                LifeLink ID: <strong>${s.lifelink_id}</strong> &bull; DOB: ${s.dob} &bull; Blood Group: <strong>${s.blood_type}</strong>
              </div>
            </div>

            <div class="allergy-alert-box">
              <div class="allergy-alert-title">Severe Allergies & Critical Contraindications</div>
              <div class="allergy-badge-list">
                ${s.critical_allergies.length ? s.critical_allergies.map(a => `<span class="allergy-badge">⚠️ ${a}</span>`).join('') : '<span style="font-weight:600; color:var(--text-secondary);">No Known Drug Allergies Reported</span>'}
              </div>
            </div>

            <div class="clinical-details-grid">
              <div class="detail-section">
                <div class="detail-section-title">Active Medications & Dosages</div>
                ${s.current_medications.length ? `<ul style="padding-left:18px; color:var(--text-primary); font-size:13px;">${s.current_medications.map(m => `<li style="margin-bottom:4px;"><strong>${m.name || m}</strong>: ${m.dosage || ''} (${m.frequency || ''})</li>`).join('')}</ul>` : '<p style="color:var(--text-muted); font-size:13px;">None reported.</p>'}
              </div>
              <div class="detail-section">
                <div class="detail-section-title">Implants & Emergency Contact</div>
                <div style="font-size:13px; margin-bottom:12px;">
                  <strong style="color:var(--text-primary);">Medical Devices:</strong>
                  <span style="color:var(--text-secondary);">${s.implanted_devices.join(', ') || 'None'}</span>
                </div>
                <div style="font-size:13px;">
                  <strong style="color:var(--text-primary);">Primary Emergency Contact:</strong><br>
                  ${s.primary_contact ? `<span style="color:var(--text-secondary);">${s.primary_contact.contact_name} (${s.primary_contact.relationship}): <strong>${s.primary_contact.phone_number}</strong></span>` : '<span style="color:var(--text-muted);">No contact on file</span>'}
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  async performManualSearch() {
    const q = document.getElementById('input-manual-search').value.trim();
    if (!q) return;
    try {
      const res = await window.api.searchPatients(q);
      const resultsDiv = document.getElementById('manual-search-results');
      resultsDiv.innerHTML = '';
      if (!res.patients.length) {
        resultsDiv.innerHTML = '<p style="color:var(--text-muted); padding:10px;">No patients match query.</p>';
        return;
      }
      res.patients.forEach(p => {
        const item = document.createElement('div');
        item.style = 'background:var(--bg-surface); padding:12px 16px; border-radius:var(--radius-md); margin-bottom:8px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; border:1px solid var(--border-subtle);';
        item.innerHTML = `<div><strong>${p.full_name}</strong> (${p.lifelink_id}) — ${p.blood_type}</div><button class="btn btn-secondary btn-sm">View Summary</button>`;
        item.addEventListener('click', () => this.loadPatientEmergencyRecord(p.id));
        resultsDiv.appendChild(item);
      });
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  openUnidentifiedModal() {
    document.getElementById('modal-unidentified')?.classList.add('active');
  }

  async submitUnidentifiedPatient() {
    const gender = document.getElementById('unidentified-gender').value;
    const age = document.getElementById('unidentified-age').value.trim() || 'Unknown';
    const notes = document.getElementById('unidentified-notes').value.trim() || 'Emergency trauma intake';

    try {
      const res = await window.api.createUnidentifiedPatient(gender, age, notes);
      document.getElementById('modal-unidentified')?.classList.remove('active');
      this.showToast(`Emergency identity created: ${res.lifelink_id}`, 'success');
      this.loadPatientEmergencyRecord(res.patient_id);
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  /* --- Workflow C: Update --- */
  startUpdate() {
    this.showScreen('screen-update');
    this.loadUpdatePatientList();
  }

  async loadUpdatePatientList() {
    const container = document.getElementById('update-patient-list');
    if (!container) return;
    container.innerHTML = 'Loading patients...';
    try {
      const res = await window.api.getAdminPatients('active');
      container.innerHTML = '';
      res.patients.forEach(p => {
        const row = document.createElement('div');
        row.style = 'background:var(--bg-surface); padding:14px 18px; border-radius:var(--radius-md); margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; border:1px solid var(--border-subtle);';
        row.innerHTML = `
          <div>
            <strong>${p.full_name}</strong> (${p.lifelink_id}) — DOB: ${p.dob}
            <div style="font-size:12px; color:var(--text-muted);">Version ${p.version} | Last updated: ${p.updated_at.split('T')[0]}</div>
          </div>
          <button class="btn btn-primary" onclick="app.openUpdateModal('${p.id}', '${p.full_name}')">Modify Record</button>
        `;
        container.appendChild(row);
      });
    } catch (e) {
      container.innerHTML = `Error: ${e.message}`;
    }
  }

  openUpdateModal(patientId, patientName) {
    document.getElementById('update-modal-patient-id').value = patientId;
    document.getElementById('update-modal-title').textContent = `Update Record: ${patientName}`;
    document.getElementById('modal-update')?.classList.add('active');
  }

  async submitRecordUpdate() {
    const patientId = document.getElementById('update-modal-patient-id').value;
    const reason = document.getElementById('update-modal-reason').value.trim();
    const phone = document.getElementById('update-modal-phone').value.trim();
    const clinicalNotes = document.getElementById('update-modal-clinical-notes').value.trim();

    if (!reason) {
      this.showToast('Documented reason is mandatory for record changes', 'error');
      return;
    }

    const payload = { reason, demographics: {}, medical: {} };
    if (phone) payload.demographics.phone = phone;
    if (clinicalNotes) payload.medical.clinical_notes = clinicalNotes;

    try {
      const res = await window.api.updatePatient(patientId, payload);
      document.getElementById('modal-update')?.classList.remove('active');
      this.showToast('Patient record updated with revision history', 'success');
      this.loadUpdatePatientList();
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  /* --- Admin Dashboard --- */
  async startAdmin() {
    this.showScreen('screen-admin');
    this.loadAdminOverview();
    this.loadAdminPatients();
  }

  async loadAdminOverview() {
    try {
      const res = await window.api.getAdminOverview();
      const kpis = res.kpis;
      document.getElementById('kpi-total-patients').textContent = kpis.total_patients;
      document.getElementById('kpi-active-patients').textContent = kpis.active_patients;
      document.getElementById('kpi-archived-patients').textContent = kpis.archived_patients;
      document.getElementById('kpi-total-staff').textContent = kpis.total_staff;
    } catch (e) {
      console.warn('Admin overview failed:', e);
    }
  }

  async loadAdminPatients() {
    const tbody = document.getElementById('admin-patients-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7">Loading records...</td></tr>';
    try {
      const res = await window.api.getAdminPatients();
      tbody.innerHTML = '';
      res.patients.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${p.lifelink_id}</strong></td>
          <td>${p.full_name}</td>
          <td>${p.dob}</td>
          <td>${p.blood_type}</td>
          <td><span class="tag ${p.status === 'active' ? 'tag-active' : ''}">${p.status.toUpperCase()}</span></td>
          <td>${p.finger_count}F / ${p.iris_count}I</td>
          <td>
            <button class="btn btn-sm btn-secondary" onclick="app.archivePatientPrompt('${p.id}')">Archive</button>
            <button class="btn btn-sm btn-danger" onclick="app.openDeletionModal('${p.id}', '${p.full_name}')">Request Delete</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7">Error: ${e.message}</td></tr>`;
    }
  }

  async archivePatientPrompt(patientId) {
    const reason = prompt('Enter documented reason for archiving patient record:');
    if (!reason) return;
    try {
      await window.api.archivePatient(patientId, reason);
      this.showToast('Patient record archived', 'success');
      this.loadAdminPatients();
      this.loadAdminOverview();
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  openDeletionModal(patientId, patientName) {
    document.getElementById('delete-modal-patient-id').value = patientId;
    document.getElementById('delete-modal-patient-name').textContent = patientName;
    document.getElementById('modal-delete')?.classList.add('active');
  }

  async submitDeletionRequest() {
    const patientId = document.getElementById('delete-modal-patient-id').value;
    const reason = document.getElementById('delete-modal-reason').value.trim();
    const legalChecked = document.getElementById('delete-modal-legal-hold').checked;

    if (!reason || !legalChecked) {
      this.showToast('Reason and legal-hold validation are required', 'error');
      return;
    }

    try {
      const res = await window.api.requestDeletion(patientId, reason, legalChecked);
      document.getElementById('modal-delete')?.classList.remove('active');
      this.showToast('Deletion request submitted for secondary approval', 'success');
      this.loadAdminPatients();
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }
}
