/**
 * LifeLink 2.0 - REST API Client
 * Wraps backend endpoints, handles bearer token authorization,
 * error serialization, and request timeouts.
 */

const API_BASE = '/api/v1';

class ApiClient {
  constructor() {
    this.token = localStorage.getItem('lifelink_token') || null;
  }

  setToken(token) {
    this.token = token;
    if (token) {
      localStorage.setItem('lifelink_token', token);
    } else {
      localStorage.removeItem('lifelink_token');
    }
  }

  async request(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.message || `Request failed with HTTP ${response.status}`);
      }

      return data;
    } catch (err) {
      console.error(`[API Error] ${endpoint}:`, err);
      throw err;
    }
  }

  /* --- Auth Endpoints --- */
  async login(portal, usernameOrEmail, password) {
    const res = await this.request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ portal, username_or_email: usernameOrEmail, password })
    });
    if (res.token) {
      this.setToken(res.token);
    }
    return res;
  }

  async logout() {
    try {
      await this.request('/auth/logout', { method: 'POST' });
    } finally {
      this.setToken(null);
    }
  }

  async getMe() {
    return this.request('/auth/me');
  }

  /* --- Devices Endpoints --- */
  async getDeviceHealth() {
    return this.request('/devices/health');
  }

  async enrollFingerprintStep(fingerPosition, passNumber, jobId = null) {
    return this.request('/devices/fingerprint/enroll-step', {
      method: 'POST',
      body: JSON.stringify({ finger_position: fingerPosition, pass_number: passNumber, job_id: jobId })
    });
  }

  async captureIris(eyeSide = 'OD') {
    return this.request('/devices/camera/capture-iris', {
      method: 'POST',
      body: JSON.stringify({ eye_side: eyeSide })
    });
  }

  async capturePhoto() {
    return this.request('/devices/camera/capture-photo', {
      method: 'POST'
    });
  }

  async cancelJob(jobId) {
    return this.request(`/devices/jobs/${jobId}/cancel`, {
      method: 'POST'
    });
  }

  /* --- Patient Workflows --- */
  async saveRegistrationDraft(draftData) {
    return this.request('/patients/registration-drafts', {
      method: 'POST',
      body: JSON.stringify(draftData)
    });
  }

  async getRegistrationDraft(draftId) {
    return this.request(`/patients/registration-drafts/${draftId}`);
  }

  async duplicateCheck(fullName, dob) {
    return this.request('/patients/duplicate-check', {
      method: 'POST',
      body: JSON.stringify({ full_name: fullName, dob })
    });
  }

  async commitRegistration(draftId) {
    return this.request(`/patients/registration-drafts/${draftId}/commit`, {
      method: 'POST'
    });
  }

  async getPatient(patientId) {
    return this.request(`/patients/${patientId}`);
  }

  async getEmergencySummary(patientId) {
    return this.request(`/patients/${patientId}/emergency-summary`);
  }

  async searchPatients(query) {
    return this.request('/patients/search', {
      method: 'POST',
      body: JSON.stringify({ query })
    });
  }

  async createUnidentifiedPatient(gender, age, notes) {
    return this.request('/patients/unidentified', {
      method: 'POST',
      body: JSON.stringify({ estimated_gender: gender, apparent_age: age, clinical_notes: notes })
    });
  }

  async updatePatient(patientId, payload) {
    return this.request(`/patients/${patientId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    });
  }

  async getPatientRevisions(patientId) {
    return this.request(`/patients/${patientId}/revisions`);
  }

  /* --- Biometrics Endpoints --- */
  async identify(biometricType, probeB64) {
    return this.request('/identify', {
      method: 'POST',
      body: JSON.stringify({ biometric_type: biometricType, probe_b64: probeB64 })
    });
  }

  async verify(patientId, biometricType, probeB64, featurePosition = 'R1') {
    return this.request('/verify', {
      method: 'POST',
      body: JSON.stringify({
        patient_id: patientId,
        biometric_type: biometricType,
        probe_b64: probeB64,
        feature_position: featurePosition
      })
    });
  }

  /* --- Admin Endpoints --- */
  async getAdminOverview() {
    return this.request('/admin/overview');
  }

  async getAdminPatients(status = null, search = '') {
    let q = `/admin/patients?search=${encodeURIComponent(search)}`;
    if (status) q += `&status=${encodeURIComponent(status)}`;
    return this.request(q);
  }

  async archivePatient(patientId, reason) {
    return this.request(`/admin/patients/${patientId}/archive`, {
      method: 'POST',
      body: JSON.stringify({ reason })
    });
  }

  async requestDeletion(patientId, reason, legalHoldConfirmed) {
    return this.request(`/admin/patients/${patientId}/deletion-requests`, {
      method: 'POST',
      body: JSON.stringify({ reason, legal_hold_confirmed: legalHoldConfirmed })
    });
  }

  async getDeletionRequests() {
    return this.request('/admin/deletion-requests');
  }

  async approveDeletion(requestId) {
    return this.request(`/admin/deletion-requests/${requestId}/approve`, {
      method: 'POST'
    });
  }

  async getStaff() {
    return this.request('/admin/staff');
  }

  async createStaff(staffData) {
    return this.request('/admin/staff', {
      method: 'POST',
      body: JSON.stringify(staffData)
    });
  }

  async getAuditLogs(action = null) {
    let q = '/admin/audit';
    if (action) q += `?action=${encodeURIComponent(action)}`;
    return this.request(q);
  }

  async getSyncStatus() {
    return this.request('/admin/sync');
  }
}

window.api = new ApiClient();
