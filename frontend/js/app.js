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
    this.staffList = [];
    this.singleImpressionMode = false;
    this.isIrisPreviewActive = false;
    this.isPhotoPreviewActive = false;
    this.isRetrievalIrisPreviewActive = false;
    this.isIrisLoopCancelled = false;
    this.isRetrievalIrisLoopCancelled = false;
  }

  async init() {
    this.bindEvents();
    this.pollDeviceHealth();
    setInterval(() => this.pollDeviceHealth(), 15000);

    // Query device feature configuration
    try {
      const cfg = await window.api.getFingerprintConfig();
      if (cfg && cfg.single_impression_enroll) {
        this.singleImpressionMode = true;
      }
    } catch (_) {}

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
    document.getElementById('btn-restore-fp')?.addEventListener('click', () => this.restoreFinger());
    document.getElementById('btn-cancel-fp-scan')?.addEventListener('click', () => this.cancelFingerScan());

    // Iris Capture & Preview Buttons
    document.getElementById('btn-toggle-iris-preview')?.addEventListener('click', () => this.toggleIrisPreview());
    document.getElementById('btn-capture-iris-od')?.addEventListener('click', () => this.captureIris('OD'));
    document.getElementById('btn-capture-iris-os')?.addEventListener('click', () => this.captureIris('OS'));
    document.getElementById('btn-cancel-iris-scan')?.addEventListener('click', () => this.cancelIrisLoop());
    document.getElementById('btn-mark-iris-unavailable')?.addEventListener('click', () => this.markIrisUnavailable());

    // Photo Capture & Preview Button
    document.getElementById('btn-toggle-photo-preview')?.addEventListener('click', () => this.togglePhotoPreview());
    document.getElementById('btn-capture-photo')?.addEventListener('click', () => this.capturePhoto());

    // Retrieval Biometric Triggers
    document.getElementById('btn-probe-fingerprint')?.addEventListener('click', () => this.probeBiometric('fingerprint'));
    document.getElementById('btn-probe-iris')?.addEventListener('click', () => this.probeBiometric('iris'));
    document.getElementById('btn-cancel-retrieval-iris-scan')?.addEventListener('click', () => this.cancelRetrievalIrisLoop());
    document.getElementById('btn-toggle-retrieval-iris-preview')?.addEventListener('click', () => this.toggleRetrievalIrisPreview());
    document.getElementById('btn-close-retrieval-iris')?.addEventListener('click', () => this.closeRetrievalIrisPanel());
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

    // Quick Login Demo Autofill Buttons
    document.querySelectorAll('.demo-fill-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const portal = btn.dataset.portal;
        const user = btn.dataset.user;
        const pass = btn.dataset.pass;

        // Select Portal Card
        document.querySelectorAll('.portal-card').forEach(c => c.classList.remove('selected'));
        const targetCard = document.querySelector(`.portal-card[data-portal="${portal}"]`);
        if (targetCard) {
          targetCard.classList.add('selected');
          this.selectedPortal = portal;
          const portalTitle = targetCard.querySelector('.portal-title')?.textContent || portal;
          const titleEl = document.getElementById('login-portal-title');
          if (titleEl) titleEl.textContent = portalTitle;
        }

        // Fill Inputs
        const userInput = document.getElementById('input-username');
        const passInput = document.getElementById('input-password');
        if (userInput) userInput.value = user;
        if (passInput) passInput.value = pass;

        this.showToast(`Selected ${portal.toUpperCase()} portal as ${user}`, 'info');
      });
    });

    // Registration Step Bar Direct Navigation
    document.querySelectorAll('.step-item').forEach(item => {
      item.addEventListener('click', () => {
        const targetStep = parseInt(item.dataset.step);
        if (targetStep) this.goToRegistrationStep(targetStep);
      });
    });

    // Retake Iris Buttons
    document.getElementById('btn-retake-iris-od')?.addEventListener('click', () => this.captureIris('OD'));
    document.getElementById('btn-retake-iris-os')?.addEventListener('click', () => this.captureIris('OS'));

    // Modals Close Buttons
    document.querySelectorAll('.modal-close').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.target.closest('.modal-overlay')?.classList.remove('active');
      });
    });
  }

  showScreen(screenId) {
    if (this.isRetrievalIrisPreviewActive && screenId !== 'screen-retrieve') {
      this.stopRetrievalIrisPreview();
    }
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
    // Gracefully stop active camera previews when leaving camera-intensive steps
    if (this.registration.currentStep === 2 && step !== 2 && this.isIrisPreviewActive) {
      this.toggleIrisPreview();
    }
    if (this.registration.currentStep === 3 && step !== 3 && this.isPhotoPreviewActive) {
      this.togglePhotoPreview();
    }

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

  goToRegistrationStep(targetStep) {
    if (targetStep < 1 || targetStep > 5 || targetStep === this.registration.currentStep) return;
    if (this.registration.currentStep === 4) {
      this.saveFormDetailsToState();
    }
    this.renderRegistrationStep(targetStep);
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

    const fpVal = this.registration.fingerprints[pos];
    const isUnavailable = (fpVal === 'UNAVAILABLE');
    const isEnrolled = (fpVal && !isUnavailable);

    document.getElementById('current-finger-title').textContent = `Finger ${pos}`;
    const btnRestore = document.getElementById('btn-restore-fp');
    const btnMark = document.getElementById('btn-mark-fp-unavailable');
    const btnScan = document.getElementById('btn-trigger-fp-scan');
    const btnCancel = document.getElementById('btn-cancel-fp-scan');
    const progressEl = document.getElementById('fp-scan-progress');
    const indicator = document.getElementById('fp-pass-indicator');
    const instruction = document.getElementById('current-finger-instruction');

    if (btnCancel) btnCancel.style.display = 'none';
    if (progressEl) progressEl.style.display = 'none';

    if (isUnavailable) {
      if (btnRestore) btnRestore.style.display = 'inline-flex';
      if (btnMark) btnMark.style.display = 'none';
      if (btnScan) {
        btnScan.disabled = true;
        btnScan.textContent = 'Capture Impression';
        btnScan.className = 'btn btn-primary';
      }
      indicator.textContent = 'Unavailable (Injured)';
      instruction.textContent = `${pos} is marked unavailable due to injury or absence. Click "Restore Finger" if digit is available.`;
    } else if (isEnrolled) {
      if (btnRestore) btnRestore.style.display = 'none';
      if (btnMark) btnMark.style.display = 'inline-flex';
      if (btnScan) {
        btnScan.disabled = false;
        btnScan.textContent = 'Retake Fingerprint';
        btnScan.className = 'btn btn-warning';
      }
      indicator.textContent = this.singleImpressionMode ? 'Enrolled (1/1) ✓' : 'Enrolled (3/3) ✓';
      instruction.textContent = `${pos} has been successfully captured. Click "Retake Fingerprint" to overwrite with a fresh scan if needed.`;
    } else {
      if (btnRestore) btnRestore.style.display = 'none';
      if (btnMark) btnMark.style.display = 'inline-flex';
      if (btnScan) {
        btnScan.disabled = false;
        btnScan.textContent = 'Capture Impression';
        btnScan.className = 'btn btn-primary';
      }
      indicator.textContent = this.singleImpressionMode ? 'Single Impression' : 'Pass 1 of 3';
      instruction.textContent = `Place ${pos} flat on the optical sensor (${this.singleImpressionMode ? 'single impression' : 'pass 1 of 3'})`;
    }
  }

  async advanceFingerScan() {
    const btn = document.getElementById('btn-trigger-fp-scan');
    const btnCancel = document.getElementById('btn-cancel-fp-scan');
    const progressEl = document.getElementById('fp-scan-progress');
    const statusText = document.getElementById('fp-scan-status-text');

    btn.disabled = true;
    if (btnCancel) btnCancel.style.display = 'inline-flex';
    if (progressEl) progressEl.style.display = 'block';
    if (statusText) statusText.textContent = `Sensor active — place ${this.activeFingerSlot} firmly on sensor...`;

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
        document.getElementById('fp-pass-indicator').textContent = `Pass ${sr.pass} of ${sr.max_passes || 3}`;
        this.showToast(`Pass ${sr.pass - 1} captured! Lift and place again.`, 'info');
      } else if (sr.status === 'completed') {
        this.registration.fingerprints[this.activeFingerSlot] = sr.template_b64;
        const slotEl = document.querySelector(`.finger-slot-card[data-pos="${this.activeFingerSlot}"]`);
        if (slotEl) {
          slotEl.classList.remove('active');
          slotEl.classList.add('enrolled', 'captured');
          const badge = slotEl.querySelector('.finger-status-badge');
          if (badge) {
            badge.className = 'finger-status-badge badge-enrolled';
            badge.textContent = '✓ Enrolled';
          }
        }
        this.showToast(`${this.activeFingerSlot} successfully enrolled!`, 'success');
        document.getElementById('current-finger-instruction').textContent = 'Enrolled successfully.';
        document.getElementById('fp-pass-indicator').textContent = sr.max_passes === 1 ? 'Enrolled (1/1) ✓' : 'Enrolled (3/3) ✓';

        // Automatic advance to the next unenrolled finger in sequence
        const fingerSeq = ['R1', 'R2', 'R3', 'R4', 'R5', 'L1', 'L2', 'L3', 'L4', 'L5'];
        const curIdx = fingerSeq.indexOf(this.activeFingerSlot);
        let nextPos = null;
        for (let i = 1; i <= fingerSeq.length; i++) {
          const candidate = fingerSeq[(curIdx + i) % fingerSeq.length];
          if (!this.registration.fingerprints[candidate]) {
            nextPos = candidate;
            break;
          }
        }

        if (nextPos) {
          this.showToast(`Auto-advancing to ${nextPos}...`, 'info');
          setTimeout(() => {
            this.selectFingerSlot(nextPos);
          }, 650);
        } else {
          this.showToast('All 10 fingers processed! Ready to proceed to Irises.', 'success');
          document.getElementById('current-finger-instruction').textContent = 'All fingerprints successfully enrolled. Proceed to Step 2 (Irises).';
        }
      } else if (sr.status === 'retry') {
        document.getElementById('current-finger-instruction').textContent = sr.instruction || 'Sensor timed out or finger moved. Try again.';
        this.showToast(sr.instruction || 'Scan failed, please retry.', 'error');
      }
    } catch (e) {
      this.showToast(e.message, 'error');
    } finally {
      btn.disabled = false;
      if (btnCancel) btnCancel.style.display = 'none';
      if (progressEl) progressEl.style.display = 'none';
    }
  }

  async cancelFingerScan() {
    try {
      await window.api.cancelFingerprint();
      this.showToast('Fingerprint scan cancelled, LED turned OFF', 'info');
    } catch (_) {}
    const btn = document.getElementById('btn-trigger-fp-scan');
    const btnCancel = document.getElementById('btn-cancel-fp-scan');
    const progressEl = document.getElementById('fp-scan-progress');
    if (btn) btn.disabled = false;
    if (btnCancel) btnCancel.style.display = 'none';
    if (progressEl) progressEl.style.display = 'none';
    document.getElementById('current-finger-instruction').textContent = 'Scan cancelled. Press Capture Impression to start again.';
  }

  markFingerUnavailable() {
    this.registration.fingerprints[this.activeFingerSlot] = 'UNAVAILABLE';
    const slotEl = document.querySelector(`.finger-slot-card[data-pos="${this.activeFingerSlot}"]`);
    if (slotEl) {
      slotEl.classList.remove('active', 'enrolled', 'captured');
      slotEl.classList.add('unavailable');
      const badge = slotEl.querySelector('.finger-status-badge');
      if (badge) {
        badge.className = 'finger-status-badge badge-unavailable';
        badge.textContent = '⚠ Injured';
      }
    }
    const btnRestore = document.getElementById('btn-restore-fp');
    const btnMark = document.getElementById('btn-mark-fp-unavailable');
    const btnScan = document.getElementById('btn-trigger-fp-scan');
    if (btnRestore) btnRestore.style.display = 'inline-flex';
    if (btnMark) btnMark.style.display = 'none';
    if (btnScan) btnScan.disabled = true;

    document.getElementById('fp-pass-indicator').textContent = 'Unavailable (Injured)';
    document.getElementById('current-finger-instruction').textContent = `${this.activeFingerSlot} marked unavailable. Select another finger or click "Restore Finger".`;
    this.showToast(`${this.activeFingerSlot} marked unavailable (injury/missing)`, 'info');

    // Auto-advance to next finger
    const fingerSeq = ['R1', 'R2', 'R3', 'R4', 'R5', 'L1', 'L2', 'L3', 'L4', 'L5'];
    const curIdx = fingerSeq.indexOf(this.activeFingerSlot);
    for (let i = 1; i <= fingerSeq.length; i++) {
      const candidate = fingerSeq[(curIdx + i) % fingerSeq.length];
      if (!this.registration.fingerprints[candidate]) {
        setTimeout(() => this.selectFingerSlot(candidate), 500);
        break;
      }
    }
  }

  restoreFinger() {
    delete this.registration.fingerprints[this.activeFingerSlot];
    const slotEl = document.querySelector(`.finger-slot-card[data-pos="${this.activeFingerSlot}"]`);
    if (slotEl) {
      slotEl.classList.remove('unavailable', 'enrolled', 'captured');
      slotEl.classList.add('active');
      const badge = slotEl.querySelector('.finger-status-badge');
      if (badge) {
        badge.className = 'finger-status-badge badge-pending';
        badge.textContent = 'Pending';
      }
    }
    const btnRestore = document.getElementById('btn-restore-fp');
    const btnMark = document.getElementById('btn-mark-fp-unavailable');
    const btnScan = document.getElementById('btn-trigger-fp-scan');
    if (btnRestore) btnRestore.style.display = 'none';
    if (btnMark) btnMark.style.display = 'inline-flex';
    if (btnScan) {
      btnScan.disabled = false;
      btnScan.textContent = 'Capture Impression';
      btnScan.className = 'btn btn-primary';
    }

    this.activeFingerPass = 1;
    this.activeFingerJobId = null;
    document.getElementById('fp-pass-indicator').textContent = this.singleImpressionMode ? 'Single Impression' : 'Pass 1 of 3';
    document.getElementById('current-finger-instruction').textContent = `Place ${this.activeFingerSlot} flat on the optical sensor (${this.singleImpressionMode ? 'single impression' : 'pass 1 of 3'})`;
    this.showToast(`${this.activeFingerSlot} restored to available`, 'success');
  }

  async toggleIrisPreview() {
    const streamImg = document.getElementById('iris-live-stream');
    const placeholder = document.getElementById('iris-placeholder-text');
    const btn = document.getElementById('btn-toggle-iris-preview');
    const previewOd = document.getElementById('iris-preview-od');
    const previewOs = document.getElementById('iris-preview-os');

    if (this.isIrisPreviewActive) {
      this.isIrisPreviewActive = false;
      if (streamImg) {
        streamImg.src = '';
        streamImg.style.display = 'none';
      }
      if (btn) btn.textContent = 'Start Live Preview';
      try {
        await window.api.stopCameraPreview();
      } catch (_) {}

      // If an eye was captured, show its thumbnail preview once stream is stopped
      if (this.registration.irises['OS'] && previewOs) {
        previewOs.style.display = 'block';
      } else if (this.registration.irises['OD'] && previewOd) {
        previewOd.style.display = 'block';
      } else if (placeholder) {
        placeholder.style.display = 'block';
      }
    } else {
      if (this.isPhotoPreviewActive) {
        await this.togglePhotoPreview();
      }
      this.isIrisPreviewActive = true;
      if (previewOd) previewOd.style.display = 'none';
      if (previewOs) previewOs.style.display = 'none';
      if (placeholder) placeholder.style.display = 'none';
      if (streamImg) {
        streamImg.src = `/api/v1/devices/camera/stream?mode=iris&t=${Date.now()}`;
        streamImg.style.display = 'block';
      }
      if (btn) btn.textContent = 'Stop Live Preview';
      this.showToast('Iris preview active (850nm IR LED ON)', 'info');
    }
  }

  async togglePhotoPreview() {
    const streamImg = document.getElementById('photo-live-stream');
    const placeholder = document.getElementById('photo-placeholder-text');
    const btn = document.getElementById('btn-toggle-photo-preview');
    const photoPreview = document.getElementById('patient-photo-preview');

    if (this.isPhotoPreviewActive) {
      this.isPhotoPreviewActive = false;
      if (streamImg) {
        streamImg.src = '';
        streamImg.style.display = 'none';
      }
      if (btn) btn.textContent = 'Start Live Preview';
      try {
        await window.api.stopCameraPreview();
      } catch (_) {}

      // If photo was captured, show preview thumbnail once stream is stopped
      if (this.registration.photoUrl && photoPreview) {
        photoPreview.style.display = 'block';
      } else if (placeholder) {
        placeholder.style.display = 'block';
      }
    } else {
      if (this.isIrisPreviewActive) {
        await this.toggleIrisPreview();
      }
      this.isPhotoPreviewActive = true;
      if (photoPreview) photoPreview.style.display = 'none';
      if (placeholder) placeholder.style.display = 'none';
      if (streamImg) {
        streamImg.src = `/api/v1/devices/camera/stream?mode=photo&t=${Date.now()}`;
        streamImg.style.display = 'block';
      }
      if (btn) btn.textContent = 'Stop Live Preview';
      this.showToast('Photo preview active (Visible light, IR LED strictly OFF)', 'info');
    }
  }

  cancelIrisLoop() {
    this.isIrisLoopCancelled = true;
    const btnCancel = document.getElementById('btn-cancel-iris-scan');
    if (btnCancel) btnCancel.style.display = 'none';
    const feedback = document.getElementById('iris-scan-feedback');
    if (feedback) feedback.style.display = 'none';
    this.showToast('Iris scanning cancelled by operator', 'info');
  }

  cancelRetrievalIrisLoop() {
    this.isRetrievalIrisLoopCancelled = true;
    const btnCancel = document.getElementById('btn-cancel-retrieval-iris-scan');
    if (btnCancel) btnCancel.style.display = 'none';
    this.showToast('Retrieval iris scanning cancelled by operator', 'info');
  }

  updateIrisQualityMeters(q) {
    if (!q) return;
    const sharpness = q.sharpness !== undefined ? q.sharpness : 0.0;
    const exposure = q.mean_intensity !== undefined ? q.mean_intensity : 0.0;
    const glare = q.glare_percentage !== undefined ? q.glare_percentage : (q.glare_ratio ? q.glare_ratio * 100 : 0.0);

    const sBar = document.getElementById('meter-sharpness');
    const sVal = document.getElementById('meter-sharpness-val');
    const eBar = document.getElementById('meter-exposure');
    const eVal = document.getElementById('meter-exposure-val');
    const gBar = document.getElementById('meter-glare');
    const gVal = document.getElementById('meter-glare-val');

    if (sBar) sBar.style.width = `${Math.min(100, sharpness)}%`;
    if (sVal) sVal.textContent = typeof sharpness === 'number' ? sharpness.toFixed(1) : sharpness;
    if (eBar) eBar.style.width = `${Math.min(100, exposure / 2)}%`;
    if (eVal) eVal.textContent = typeof exposure === 'number' ? exposure.toFixed(1) : exposure;
    if (gBar) gBar.style.width = `${Math.min(100, glare * 10)}%`;
    if (gVal) gVal.textContent = `${typeof glare === 'number' ? glare.toFixed(1) : glare}%`;
  }

  updateIrisSuccessUI(eyeSide, res) {
    const placeholder = document.getElementById('iris-placeholder-text');
    if (placeholder) placeholder.style.display = 'none';

    // Update Viewport Preview
    const preview = document.getElementById(`iris-preview-${eyeSide.toLowerCase()}`);
    if (preview && res.image_b64) {
      preview.src = `data:image/jpeg;base64,${res.image_b64}`;
      if (!this.isIrisPreviewActive) {
        preview.style.display = 'block';
      }
    }

    // Update Dual Review Card for this eye
    const sideLower = eyeSide.toLowerCase();
    const thumbImg = document.getElementById(`iris-thumb-${sideLower}`);
    const reticleOverlay = document.getElementById(`reticle-${sideLower}`);
    const emptySpan = document.getElementById(`iris-thumb-empty-${sideLower}`);
    const badgeStatus = document.getElementById(`badge-iris-status-${sideLower}`);
    const descStatus = document.getElementById(`desc-iris-status-${sideLower}`);
    const cardEl = document.getElementById(`card-iris-${sideLower}`);
    const retakeBtn = document.getElementById(`btn-retake-iris-${sideLower}`);

    if (thumbImg && res.image_b64) {
      thumbImg.src = `data:image/jpeg;base64,${res.image_b64}`;
      thumbImg.style.display = 'block';
    }
    if (reticleOverlay) reticleOverlay.style.display = 'flex';
    if (emptySpan) emptySpan.style.display = 'none';
    if (badgeStatus) {
      badgeStatus.className = 'status-pill status-ready';
      badgeStatus.textContent = 'Enrolled ✓';
    }
    const q = res.quality || {};
    const sharpness = q.sharpness !== undefined ? q.sharpness : 75.0;
    const exposure = q.mean_intensity !== undefined ? q.mean_intensity : 120.0;
    const glare = q.glare_percentage !== undefined ? q.glare_percentage : (q.glare_ratio || 0.5);

    if (descStatus) {
      descStatus.innerHTML = `Sharpness: <strong>${sharpness}</strong> • Glare: <strong>${glare}%</strong> • Template Extracted ✓`;
    }
    if (cardEl) cardEl.classList.add('enrolled');
    if (retakeBtn) retakeBtn.style.display = 'inline-flex';

    // Show Biometric Vault Confirmation Badge
    const bioBadge = document.getElementById('iris-biometric-badge');
    if (bioBadge) bioBadge.style.display = 'flex';

    this.updateIrisQualityMeters(q);
  }

  async captureIris(eyeSide) {
    const btn = document.getElementById(`btn-capture-iris-${eyeSide.toLowerCase()}`);
    const otherEye = eyeSide === 'OD' ? 'OS' : 'OD';
    const otherBtn = document.getElementById(`btn-capture-iris-${otherEye.toLowerCase()}`);
    const btnCancel = document.getElementById('btn-cancel-iris-scan');
    const feedback = document.getElementById('iris-scan-feedback');
    const originalText = btn ? btn.textContent : '';

    this.isIrisLoopCancelled = false;
    let attempt = 0;

    if (btn) btn.disabled = true;
    if (otherBtn) otherBtn.disabled = true;
    if (btnCancel) btnCancel.style.display = 'inline-flex';
    if (feedback) feedback.style.display = 'block';

    const eyeLabel = eyeSide === 'OD' ? 'Right Eye (OD)' : 'Left Eye (OS)';

    while (!this.isIrisLoopCancelled) {
      attempt++;
      if (btn) btn.textContent = `Attempt ${attempt}: Scanning 3s window...`;
      if (feedback) {
        feedback.innerHTML = `<strong>Attempt ${attempt} (${eyeLabel}):</strong> Camera scanning 3-second window for optimal eye frame. Hold steady and look directly at camera lens...`;
      }

      try {
        const res = await window.api.captureIris(eyeSide);

        if (this.isIrisLoopCancelled) break;

        // If frame yielded a valid template extraction: SUCCESS! STOP LOOP FOR THIS EYE!
        if (res.status === 'success' && res.template_extracted) {
          this.registration.irises[eyeSide] = res.image_b64;
          this.updateIrisSuccessUI(eyeSide, res);

          if (feedback) {
            feedback.innerHTML = `<span style="color:var(--success, #10b981); font-weight:700;">✓ Template Extracted Successfully!</span> Best frame accepted on attempt ${attempt}. Scanning complete for ${eyeLabel}.`;
          }

          if (btn) {
            btn.classList.remove('btn-secondary');
            btn.classList.add('btn-success');
            btn.textContent = `Capture ${eyeLabel} ✓`;
          }

          this.showToast(`[✓ TEMPLATE EXTRACTED] ${eyeLabel} captured & vaulted on attempt ${attempt}!`, 'success');
          break; // STOP SCANNING FOR THIS PARTICULAR EYE!
        } else {
          // Template was NOT extracted. Pi 5 sends signal to Pi 3 for rescanning!
          const reason = res.message || 'Iris features or pupil boundary not distinct';
          if (feedback) {
            feedback.innerHTML = `<span style="color:var(--warning, #f59e0b); font-weight:600;">⚠ Attempt ${attempt} Incomplete:</span> ${reason}. Rescanning in next 3s window... Keep eye open.`;
          }
          if (res.quality) {
            this.updateIrisQualityMeters(res.quality);
          }
          this.showToast(`Attempt ${attempt} did not yield template. Rescanning 3s window...`, 'warning');

          // Brief pause before triggering next 3-second cycle on Pi 3B+
          await new Promise(r => setTimeout(r, 350));
        }
      } catch (err) {
        if (this.isIrisLoopCancelled) break;

        const reason = err.data?.message || err.message || 'Acquisition incomplete';
        if (feedback) {
          feedback.innerHTML = `<span style="color:var(--warning, #f59e0b); font-weight:600;">⚠ Attempt ${attempt}:</span> ${reason}. Rescanning in next 3s window...`;
        }
        if (err.data?.quality) {
          this.updateIrisQualityMeters(err.data.quality);
        }
        this.showToast(`Attempt ${attempt} rescanning...`, 'warning');
        await new Promise(r => setTimeout(r, 400));
      }
    }

    if (btn) {
      btn.disabled = false;
      if (!this.registration.irises[eyeSide]) {
        btn.textContent = originalText || `Capture ${eyeLabel}`;
      }
    }
    if (otherBtn) otherBtn.disabled = false;
    if (btnCancel) btnCancel.style.display = 'none';
  }

  markIrisUnavailable() {
    this.registration.irises['OD'] = 'UNAVAILABLE';
    const badgeStatus = document.getElementById('badge-iris-status-od');
    const descStatus = document.getElementById('desc-iris-status-od');
    if (badgeStatus) {
      badgeStatus.className = 'status-pill status-warning';
      badgeStatus.textContent = 'Unavailable';
    }
    if (descStatus) descStatus.textContent = 'Marked unavailable by exception';
    this.showToast('Iris scan marked unavailable by exception', 'info');
  }

  async capturePhoto() {
    const btn = document.getElementById('btn-capture-photo');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Acquiring portrait...';
    }

    try {
      const res = await window.api.capturePhoto();
      if (res.status === 'success') {
        this.registration.photoUrl = `data:image/jpeg;base64,${res.image_b64}`;
        const placeholder = document.getElementById('photo-placeholder-text');
        if (placeholder) placeholder.style.display = 'none';
        const preview = document.getElementById('patient-photo-preview');
        if (preview) {
          preview.src = this.registration.photoUrl;
          if (!this.isPhotoPreviewActive) {
            preview.style.display = 'block';
          }
        }
        this.showToast('Patient photo acquired successfully', 'success');
      } else {
        this.showToast(res.message || 'Photo capture failed', 'error');
      }
    } catch (e) {
      this.showToast(`Photo capture error: ${e.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Capture Patient Photo';
      }
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
  async startRetrieval() {
    document.getElementById('retrieval-status-box').style.display = 'none';
    document.getElementById('retrieval-results-card').style.display = 'none';
    const irisPanel = document.getElementById('retrieval-iris-panel');
    if (irisPanel) irisPanel.style.display = 'none';
    await this.stopRetrievalIrisPreview();
    this.showScreen('screen-retrieve');
  }

  async toggleRetrievalIrisPreview() {
    const streamImg = document.getElementById('retrieval-iris-stream');
    const previewImg = document.getElementById('retrieval-iris-preview');
    const placeholder = document.getElementById('retrieval-iris-placeholder');
    const btn = document.getElementById('btn-toggle-retrieval-iris-preview');
    const feedback = document.getElementById('retrieval-iris-feedback');

    if (this.isRetrievalIrisPreviewActive) {
      await this.stopRetrievalIrisPreview();
    } else {
      if (this.isIrisPreviewActive) await this.toggleIrisPreview();
      if (this.isPhotoPreviewActive) await this.togglePhotoPreview();

      this.isRetrievalIrisPreviewActive = true;
      if (placeholder) placeholder.style.display = 'none';
      if (previewImg) previewImg.style.display = 'none';
      if (streamImg) {
        streamImg.src = `/api/v1/devices/camera/stream?mode=iris&t=${Date.now()}`;
        streamImg.style.display = 'block';
      }
      if (btn) btn.textContent = 'Stop Live Feed';
      if (feedback) feedback.innerHTML = '<strong>Live preview active:</strong> 850nm NIR illumination is ON. Align eye inside circular reticle.';
      this.showToast('Retrieval iris preview active (850nm IR LED ON)', 'info');
    }
  }

  async stopRetrievalIrisPreview() {
    const streamImg = document.getElementById('retrieval-iris-stream');
    const previewImg = document.getElementById('retrieval-iris-preview');
    const placeholder = document.getElementById('retrieval-iris-placeholder');
    const btn = document.getElementById('btn-toggle-retrieval-iris-preview');

    this.isRetrievalIrisPreviewActive = false;
    if (streamImg) {
      streamImg.src = '';
      streamImg.style.display = 'none';
    }
    if (btn) btn.textContent = 'Toggle Live Feed';
    try {
      await window.api.stopCameraPreview();
    } catch (_) {}

    if (previewImg && previewImg.src && !previewImg.src.endsWith('#') && previewImg.style.display !== 'none') {
      // Keep captured preview frame visible
    } else if (placeholder) {
      placeholder.style.display = 'block';
    }
  }

  async closeRetrievalIrisPanel() {
    await this.stopRetrievalIrisPreview();
    const panel = document.getElementById('retrieval-iris-panel');
    if (panel) panel.style.display = 'none';
  }

  resetRetrievalIrisMeters() {
    const sBar = document.getElementById('retrieval-meter-sharpness');
    const sVal = document.getElementById('retrieval-meter-sharpness-val');
    const eBar = document.getElementById('retrieval-meter-exposure');
    const eVal = document.getElementById('retrieval-meter-exposure-val');
    const gBar = document.getElementById('retrieval-meter-glare');
    const gVal = document.getElementById('retrieval-meter-glare-val');

    if (sBar) sBar.style.width = '0%';
    if (sVal) sVal.textContent = '0.0';
    if (eBar) eBar.style.width = '0%';
    if (eVal) eVal.textContent = '0.0';
    if (gBar) gBar.style.width = '0%';
    if (gVal) gVal.textContent = '0.0%';
  }

  updateRetrievalIrisMeters(sharpness, exposure, glare) {
    const sBar = document.getElementById('retrieval-meter-sharpness');
    const sVal = document.getElementById('retrieval-meter-sharpness-val');
    const eBar = document.getElementById('retrieval-meter-exposure');
    const eVal = document.getElementById('retrieval-meter-exposure-val');
    const gBar = document.getElementById('retrieval-meter-glare');
    const gVal = document.getElementById('retrieval-meter-glare-val');

    if (sBar) sBar.style.width = `${Math.min(100, Math.max(0, sharpness))}%`;
    if (sVal) sVal.textContent = typeof sharpness === 'number' ? sharpness.toFixed(1) : sharpness;
    if (eBar) eBar.style.width = `${Math.min(100, Math.max(0, exposure / 2))}%`;
    if (eVal) eVal.textContent = typeof exposure === 'number' ? exposure.toFixed(1) : exposure;
    if (gBar) gBar.style.width = `${Math.min(100, Math.max(0, glare * 10))}%`;
    if (gVal) gVal.textContent = `${typeof glare === 'number' ? glare.toFixed(1) : glare}%`;
  }

  async probeBiometric(type) {
    const statusBox = document.getElementById('retrieval-status-box');
    const resultsCard = document.getElementById('retrieval-results-card');
    const btnFp = document.getElementById('btn-probe-fingerprint');
    const btnIris = document.getElementById('btn-probe-iris');
    const selectEye = document.getElementById('select-probe-iris-eye');
    const retrievalIrisPanel = document.getElementById('retrieval-iris-panel');

    if (!statusBox) return;
    statusBox.style.display = 'block';
    if (resultsCard) resultsCard.style.display = 'none';

    // Disable capture buttons while scanning to prevent hardware race conditions
    if (btnFp) btnFp.disabled = true;
    if (btnIris) btnIris.disabled = true;
    if (selectEye) selectEye.disabled = true;

    try {
      let probeB64 = null;

      if (type === 'fingerprint') {
        // If iris preview is running, stop it so camera and USB peripherals are quiet
        if (this.isRetrievalIrisPreviewActive) {
          await this.stopRetrievalIrisPreview();
        }
        if (retrievalIrisPanel) retrievalIrisPanel.style.display = 'none';

        if (btnFp) btnFp.textContent = 'Scanning Fingerprint...';

        statusBox.innerHTML = `
          <div style="display:flex; align-items:center; gap:10px;">
            <span class="loading-spinner"></span>
            <div>
              <strong>[OPTICAL SENSOR ACTIVE]</strong> Fingerprint scanner backlight is ON.<br>
              <span style="color:var(--text-secondary);">Please place patient's finger flat and firm on the optical sensor prism...</span>
            </div>
          </div>
        `;

        const probeRes = await window.api.captureFingerprintProbe();
        probeB64 = probeRes.template_b64;

        statusBox.innerHTML = `
          <div style="display:flex; align-items:center; gap:10px;">
            <span class="loading-spinner"></span>
            <div>
              <strong>[PROBE ACQUIRED]</strong> Hardware template (${probeRes.template_size || 498} bytes) extracted.<br>
              <span style="color:var(--text-secondary);">Searching 1:N local database gallery for matching biometric candidate...</span>
            </div>
          </div>
        `;
      } else {
        const eyeSide = selectEye ? selectEye.value : 'OD';
        const eyeLabel = eyeSide === 'OS' ? 'Left Eye (OS)' : 'Right Eye (OD)';
        if (btnIris) btnIris.textContent = `Scanning ${eyeSide}...`;

        // Display iris scanning & screening panel with live alignment preview (same workflow as registration)
        if (retrievalIrisPanel) retrievalIrisPanel.style.display = 'grid';

        const streamImg = document.getElementById('retrieval-iris-stream');
        const previewImg = document.getElementById('retrieval-iris-preview');
        const placeholder = document.getElementById('retrieval-iris-placeholder');
        const feedback = document.getElementById('retrieval-iris-feedback');
        const btnCancel = document.getElementById('btn-cancel-retrieval-iris-scan');

        if (placeholder) placeholder.style.display = 'none';
        if (previewImg) previewImg.style.display = 'none';
        if (streamImg) {
          streamImg.src = `/api/v1/devices/camera/stream?mode=iris&t=${Date.now()}`;
          streamImg.style.display = 'block';
        }
        this.isRetrievalIrisPreviewActive = true;
        this.isRetrievalIrisLoopCancelled = false;
        if (btnCancel) btnCancel.style.display = 'inline-flex';

        // Reset ISO screening meters
        this.resetRetrievalIrisMeters();

        let attempt = 0;
        while (!this.isRetrievalIrisLoopCancelled) {
          attempt++;
          if (btnIris) btnIris.textContent = `Attempt ${attempt}: Scanning 3s...`;
          if (feedback) {
            feedback.innerHTML = `<strong>Attempt ${attempt} (${eyeLabel}):</strong> Camera scanning 3-second window for optimal frame. Align eye inside circular reticle...`;
          }

          statusBox.innerHTML = `
            <div style="display:flex; align-items:center; gap:10px;">
              <span class="loading-spinner"></span>
              <div>
                <strong>[CAMERA ACTIVE]</strong> Attempt ${attempt}: Scanning 3-second window for ${eyeLabel}.<br>
                <span style="color:var(--text-secondary);">Align patient's eye with camera reticle in the live preview viewport above...</span>
              </div>
            </div>
          `;

          try {
            // Acquire 3-second best frame and evaluate template extraction on Pi 5
            const probeRes = await window.api.captureIrisProbe(eyeSide);

            if (this.isRetrievalIrisLoopCancelled) break;

            if (probeRes.status === 'success' && probeRes.template_extracted) {
              probeB64 = probeRes.image_b64;

              // Freeze captured frame in viewport and stop live stream
              this.isRetrievalIrisPreviewActive = false;
              if (streamImg) {
                streamImg.src = '';
                streamImg.style.display = 'none';
              }
              if (previewImg && probeB64) {
                previewImg.src = `data:image/jpeg;base64,${probeB64}`;
                previewImg.style.display = 'block';
              }

              // Update ISO/IEC 29794-6 quality screening meters
              const q = probeRes.quality || {};
              const sharpness = q.sharpness !== undefined ? q.sharpness : 75.0;
              const exposure = q.mean_intensity !== undefined ? q.mean_intensity : 120.0;
              const glare = q.glare_percentage !== undefined ? q.glare_percentage : (q.glare_ratio || 0.5);

              this.updateRetrievalIrisMeters(sharpness, exposure, glare);

              if (feedback) {
                feedback.innerHTML = `<span style="color:var(--success, #10b981); font-weight:700;">✓ Template Extracted Successfully:</span> Attempt ${attempt} accepted! Sharpness: <strong>${sharpness}</strong> &bull; Glare: <strong>${glare}%</strong>`;
              }

              statusBox.innerHTML = `
                <div style="display:flex; align-items:center; gap:10px;">
                  <span class="loading-spinner"></span>
                  <div>
                    <strong>[PROBE ACQUIRED]</strong> Template extracted on attempt ${attempt}.<br>
                    <span style="color:var(--text-secondary);">Extracting 512-d Vis-IrisFormer embedding & searching 1:N local database gallery...</span>
                  </div>
                </div>
              `;
              break; // TEMPLATE EXTRACTED! EXIT LOOP!
            } else {
              // Template not extracted: update status, preview current frame, and rescan!
              const reason = probeRes.message || 'Template extraction incomplete';
              if (feedback) {
                feedback.innerHTML = `<span style="color:var(--warning, #f59e0b); font-weight:600;">⚠ Attempt ${attempt}:</span> ${reason}. Rescanning automatically...`;
              }
              if (probeRes.quality) {
                const q = probeRes.quality;
                this.updateRetrievalIrisMeters(q.sharpness, q.mean_intensity, q.glare_percentage);
              }
              this.showToast(`Attempt ${attempt} frame not optimal. Rescanning 3s window...`, 'warning');
              await new Promise(r => setTimeout(r, 350));
            }
          } catch (err) {
            if (this.isRetrievalIrisLoopCancelled) break;
            const reason = err.data?.message || err.message || 'Frame not optimal';
            if (feedback) {
              feedback.innerHTML = `<span style="color:var(--warning, #f59e0b); font-weight:600;">⚠ Attempt ${attempt}:</span> ${reason}. Rescanning in next 3s window...`;
            }
            if (err.data?.quality) {
              const q = err.data.quality;
              this.updateRetrievalIrisMeters(q.sharpness, q.mean_intensity, q.glare_percentage);
            }
            this.showToast(`Attempt ${attempt} rescanning...`, 'warning');
            await new Promise(r => setTimeout(r, 400));
          }
        }

        if (btnCancel) btnCancel.style.display = 'none';

        if (!probeB64 && this.isRetrievalIrisLoopCancelled) {
          statusBox.innerHTML = `
            <div style="padding:4px 0;">
              <strong style="color:var(--warning, #f59e0b);">[SCAN CANCELLED]</strong> Iris probe acquisition was cancelled by operator.
            </div>
          `;
          return;
        }
      }

      if (!probeB64) {
        throw new Error('Biometric probe acquisition returned an empty template.');
      }

      // Execute 1:N gallery identification against local database
      const res = await window.api.identify(type, probeB64);
      const ident = res.identification;

      if (ident && ident.outcome === 'MATCH' && ident.candidates && ident.candidates.length) {
        const top = ident.candidates[0];
        const modalityLabel = type === 'fingerprint' ? 'Optical Fingerprint' : `Iris Biometric (${selectEye?.value || 'OD'})`;
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--success, #10b981);">[✓ MATCH CONFIRMED]</strong> Candidate: <strong>${top.full_name}</strong> (${top.lifelink_id}) &bull; Confidence: ${(top.score * 100).toFixed(1)}% &bull; Modality: ${modalityLabel}
          </div>
        `;
        this.showToast(`Biometric match confirmed for ${top.full_name}`, 'success');
        await this.loadPatientEmergencyRecord(top.patient_id);
      } else if (ident && ident.outcome === 'INCONCLUSIVE' && ident.candidates && ident.candidates.length) {
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--warning, #f59e0b);">[⚠️ AMBIGUOUS MATCH]</strong> Multiple candidate profiles detected within tolerance threshold. Please select a verified record below.
          </div>
        `;
        this.renderCandidateList(ident.candidates);
      } else {
        const thresholdPct = type === 'fingerprint' ? '60%' : '62%';
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--danger, #ef4444);">[✕ NO MATCH IN GALLERY]</strong> A valid biometric probe was captured and verified, but no matching patient was found in the local gallery (Threshold: ${thresholdPct}). Please verify enrollment status or use manual lookup below.
          </div>
        `;
      }
    } catch (e) {
      console.error(`[Biometric Retrieval Error] ${type}:`, e);
      const errType = e.data?.error_type;

      if (type === 'iris') {
        await this.stopRetrievalIrisPreview();
        if (e.data?.quality) {
          const q = e.data.quality;
          const sharpness = q.sharpness !== undefined ? q.sharpness : 0;
          const exposure = q.mean_intensity !== undefined ? q.mean_intensity : 0;
          const glare = q.glare_percentage !== undefined ? q.glare_percentage : 0;
          this.updateRetrievalIrisMeters(sharpness, exposure, glare);
          const feedback = document.getElementById('retrieval-iris-feedback');
          if (feedback) {
            feedback.innerHTML = `<span style="color:var(--warning, #f59e0b); font-weight:700;">⚠ Quality Rejected:</span> Sharpness: <strong>${sharpness}</strong> &bull; Exposure: <strong>${exposure}</strong> &bull; Glare: <strong>${glare}%</strong>. Frame did not meet ISO/IEC 29794-6 criteria.`;
          }
        }
      }

      if (errType === 'NO_FINGER_DETECTED' || (e.status === 422 && type === 'fingerprint')) {
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--warning, #f59e0b);">[⚠️ NO FINGER DETECTED / TIMEOUT]</strong> ${e.message}<br>
            <span style="font-size:12px; color:var(--text-secondary);">Ensure the patient presses their finger flat and firm against the optical prism. Click "Capture Fingerprint Probe" to retry.</span>
          </div>
        `;
      } else if (errType === 'QUALITY_REJECTED' || (e.status === 422 && type === 'iris')) {
        const reasons = e.data?.quality?.rejection_reasons?.join(', ') || '';
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--warning, #f59e0b);">[⚠️ QUALITY REJECTED]</strong> ${e.message} ${reasons ? `(${reasons})` : ''}<br>
            <span style="font-size:12px; color:var(--text-secondary);">Align the eye 12–15 cm from lens with wide open eyelids and hold still. Click "Capture Iris Probe" to retry.</span>
          </div>
        `;
      } else if (errType === 'HARDWARE_DISCONNECTED' || errType === 'HARDWARE_UNAVAILABLE' || e.status === 503) {
        const devName = type === 'fingerprint' ? 'ESP32 Optical Fingerprint Sensor' : 'Pi 3B+ Camera Substation (192.168.50.2)';
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--danger, #ef4444);">[⚠️ HARDWARE DISCONNECTED]</strong> ${e.message}<br>
            <span style="font-size:12px; color:var(--text-secondary);">Please verify the physical cable connection to the ${devName}.</span>
          </div>
        `;
      } else if (errType === 'CAPTURE_TIMEOUT' || e.status === 504) {
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--danger, #ef4444);">[⚠️ SCAN TIMEOUT]</strong> ${e.message}<br>
            <span style="font-size:12px; color:var(--text-secondary);">The sensor or camera timed out waiting for a valid biometric subject. Click to retry.</span>
          </div>
        `;
      } else if (errType === 'DEVICE_BUSY' || e.status === 409) {
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--warning, #f59e0b);">[⚠️ DEVICE BUSY]</strong> ${e.message}<br>
            <span style="font-size:12px; color:var(--text-secondary);">Another hardware capture operation is currently in progress. Please wait a moment and retry.</span>
          </div>
        `;
      } else {
        statusBox.innerHTML = `
          <div style="padding:4px 0;">
            <strong style="color:var(--danger, #ef4444);">[⚠️ RETRIEVAL ERROR]</strong> ${e.message}
          </div>
        `;
      }
    } finally {
      if (btnFp) {
        btnFp.disabled = false;
        btnFp.textContent = 'Capture Fingerprint Probe';
      }
      if (btnIris) {
        btnIris.disabled = false;
        btnIris.textContent = 'Capture Iris Probe';
      }
      if (selectEye) selectEye.disabled = false;
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
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async loadPatientEmergencyRecord(patientId) {
    try {
      const res = await window.api.getEmergencySummary(patientId);
      const s = res.emergency_summary;
      const card = document.getElementById('retrieval-results-card');
      if (!card) return;
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
                LifeLink ID: <strong>${s.lifelink_id}</strong> &bull; DOB: ${s.dob} &bull; Blood Group: <strong>${s.blood_type}</strong> &bull; Sex: <strong>${s.gender || 'Unknown'}</strong>
              </div>
            </div>

            <div class="allergy-alert-box">
              <div class="allergy-alert-title">Severe Allergies & Critical Contraindications</div>
              <div class="allergy-badge-list">
                ${s.critical_allergies && s.critical_allergies.length ? s.critical_allergies.map(a => `<span class="allergy-badge">⚠️ ${a}</span>`).join('') : '<span style="font-weight:600; color:var(--text-secondary);">No Known Drug Allergies Reported</span>'}
              </div>
            </div>

            <div class="clinical-details-grid">
              <div class="detail-section">
                <div class="detail-section-title">Chronic Conditions</div>
                ${s.chronic_conditions && s.chronic_conditions.length ? `<ul style="padding-left:18px; color:var(--text-primary); font-size:13px;">${s.chronic_conditions.map(c => `<li style="margin-bottom:4px;"><strong>${c}</strong></li>`).join('')}</ul>` : '<p style="color:var(--text-muted); font-size:13px;">None reported.</p>'}
              </div>
              <div class="detail-section">
                <div class="detail-section-title">Active Medications & Dosages</div>
                ${s.current_medications && s.current_medications.length ? `<ul style="padding-left:18px; color:var(--text-primary); font-size:13px;">${s.current_medications.map(m => `<li style="margin-bottom:4px;"><strong>${m.name || m}</strong>: ${m.dosage || ''} (${m.frequency || ''})</li>`).join('')}</ul>` : '<p style="color:var(--text-muted); font-size:13px;">None reported.</p>'}
              </div>
              <div class="detail-section">
                <div class="detail-section-title">Implants & Devices</div>
                <div style="font-size:13px;">
                  <span style="color:var(--text-secondary);">${(s.implanted_devices && s.implanted_devices.length) ? s.implanted_devices.join(', ') : 'None'}</span>
                </div>
              </div>
              <div class="detail-section">
                <div class="detail-section-title">Primary Emergency Contact</div>
                <div style="font-size:13px;">
                  ${s.primary_contact ? `<span style="color:var(--text-secondary);">${s.primary_contact.contact_name} (${s.primary_contact.relationship}): <strong>${s.primary_contact.phone_number}</strong></span>` : '<span style="color:var(--text-muted);">No contact on file</span>'}
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
    const fingerPos = document.getElementById('update-modal-finger-pos')?.value;
    const fingerStatus = document.getElementById('update-modal-finger-status')?.value;

    if (!reason) {
      this.showToast('Documented reason is mandatory for record changes', 'error');
      return;
    }

    const payload = { reason, demographics: {}, medical: {} };
    if (phone) payload.demographics.phone = phone;
    if (clinicalNotes) payload.medical.clinical_notes = clinicalNotes;
    if (fingerPos && fingerPos !== 'none') {
      payload.finger_exception = {
        position: fingerPos,
        status: fingerStatus
      };
    }

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
    this.loadAdminStaff();
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

  async loadAdminStaff() {
    const tbody = document.getElementById('admin-staff-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7">Loading staff accounts...</td></tr>';
    try {
      const res = await window.api.getStaff();
      this.staffList = res.staff || [];
      tbody.innerHTML = '';
      if (this.staffList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-secondary);">No staff accounts found.</td></tr>';
        return;
      }
      this.staffList.forEach(s => {
        const isSelf = this.currentUser && (this.currentUser.staff_id === s.id || this.currentUser.username === s.username);
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${s.username}</strong> ${isSelf ? '<span class="tag tag-active" style="font-size:10px; margin-left:4px;">YOU</span>' : ''}</td>
          <td>${s.full_name}</td>
          <td>${s.email}</td>
          <td><span class="tag">${s.role}</span></td>
          <td><span class="tag ${s.is_active ? 'tag-active' : ''}">${s.is_active ? 'ACTIVE' : 'INACTIVE'}</span></td>
          <td>${s.created_at ? s.created_at.substring(0, 10) : '-'}</td>
          <td>
            <button class="btn btn-sm btn-secondary" onclick="app.openStaffModal('${s.id}')">Edit</button>
            ${isSelf 
              ? '<button class="btn btn-sm btn-ghost" disabled title="Cannot delete active session" style="opacity:0.4;">Delete</button>'
              : `<button class="btn btn-sm btn-danger" onclick="app.deleteStaffUser('${s.id}', '${s.username}')">Delete</button>`
            }
          </td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7">Error loading staff: ${e.message}</td></tr>`;
    }
  }

  openStaffModal(staffId = null) {
    const modal = document.getElementById('modal-staff');
    if (!modal) return;

    if (staffId) {
      const staff = (this.staffList || []).find(s => s.id === staffId);
      if (!staff) {
        this.showToast('Staff account record not found', 'error');
        return;
      }
      document.getElementById('staff-modal-title').textContent = 'Edit Staff Account & Login';
      document.getElementById('staff-modal-id').value = staff.id;
      document.getElementById('staff-modal-name').value = staff.full_name || '';
      document.getElementById('staff-modal-username').value = staff.username || '';
      document.getElementById('staff-modal-email').value = staff.email || '';
      document.getElementById('staff-modal-role').value = staff.role || 'clinician';
      document.getElementById('staff-modal-password').value = '';
      document.getElementById('staff-modal-password-hint').textContent = '(Leave blank to keep password unchanged)';
      document.getElementById('staff-modal-active').checked = Boolean(staff.is_active);
    } else {
      document.getElementById('staff-modal-title').textContent = 'Add New Staff Account';
      document.getElementById('staff-modal-id').value = '';
      document.getElementById('staff-modal-name').value = '';
      document.getElementById('staff-modal-username').value = '';
      document.getElementById('staff-modal-email').value = '';
      document.getElementById('staff-modal-role').value = 'clinician';
      document.getElementById('staff-modal-password').value = '';
      document.getElementById('staff-modal-password-hint').textContent = '(Required for new account)';
      document.getElementById('staff-modal-active').checked = true;
    }

    modal.classList.add('active');
  }

  closeStaffModal() {
    document.getElementById('modal-staff')?.classList.remove('active');
  }

  async saveStaffUser() {
    const staffId = document.getElementById('staff-modal-id').value.trim();
    const fullName = document.getElementById('staff-modal-name').value.trim();
    const username = document.getElementById('staff-modal-username').value.trim();
    const email = document.getElementById('staff-modal-email').value.trim();
    const role = document.getElementById('staff-modal-role').value;
    const password = document.getElementById('staff-modal-password').value;
    const isActive = document.getElementById('staff-modal-active').checked ? 1 : 0;

    if (!fullName || !username || !email) {
      this.showToast('Full name, username, and email are required', 'error');
      return;
    }

    if (!staffId && (!password || password.trim().length === 0)) {
      this.showToast('Password is required when creating a new staff account', 'error');
      return;
    }

    if (password && password.trim().length > 0 && password.trim().length < 6) {
      this.showToast('Password must be at least 6 characters long', 'error');
      return;
    }

    const payload = {
      full_name: fullName,
      username: username,
      email: email,
      role: role,
      is_active: isActive
    };
    if (password && password.trim()) {
      payload.password = password.trim();
    }

    const saveBtn = document.getElementById('btn-save-staff');
    if (saveBtn) saveBtn.disabled = true;

    try {
      if (staffId) {
        await window.api.updateStaff(staffId, payload);
        this.showToast(`Staff account '${username}' updated successfully`, 'success');
      } else {
        await window.api.createStaff(payload);
        this.showToast(`Staff account '${username}' created successfully`, 'success');
      }
      this.closeStaffModal();
      this.loadAdminStaff();
      this.loadAdminOverview();
    } catch (e) {
      this.showToast(e.message, 'error');
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async deleteStaffUser(staffId, username) {
    if (!confirm(`Are you sure you want to remove staff account "${username}"?\nThis action permanently deletes login credentials.`)) {
      return;
    }

    try {
      await window.api.deleteStaff(staffId);
      this.showToast(`Staff account "${username}" removed successfully`, 'success');
      this.loadAdminStaff();
      this.loadAdminOverview();
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }
}
