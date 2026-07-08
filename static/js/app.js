/**
 * Job Hunter — HR Data Command Center
 * Frontend Application Logic
 */

// ═══════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════

const state = {
  currentTab: 'dashboard',
  contacts: [],
  stats: null,
  currentPage: 1,
  perPage: 50,
  totalPages: 1,
  totalContacts: 0,
  selectedIds: new Set(),
  searchTimeout: null,
  charts: {},
  bulkPolling: null,
};


// ═══════════════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
  loadStats();
  loadContacts();
});

// Helper to refresh Lucide icons after dynamic DOM changes
function refreshIcons() {
  requestAnimationFrame(() => lucide.createIcons());
}


// ═══════════════════════════════════════════════════════════════════════
// TAB NAVIGATION
// ═══════════════════════════════════════════════════════════════════════

function switchTab(tab) {
  state.currentTab = tab;

  // Update nav items
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.tab === tab);
  });

  // Update tab content
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.toggle('active', content.id === `tab-${tab}`);
  });

  // Load tab-specific data
  if (tab === 'dashboard') loadStats();
  if (tab === 'contacts') loadContacts();
  if (tab === 'analytics') loadAnalytics();
}


// ═══════════════════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════════════════

async function api(url, options = {}) {
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Request failed');
    return data;
  } catch (err) {
    showToast(err.message, 'error');
    throw err;
  }
}


// ═══════════════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════════════

async function loadStats() {
  try {
    const stats = await api('/api/stats');
    state.stats = stats;

    // Update stat cards
    animateNumber('statTotal', stats.total_contacts);
    animateNumber('statCompanies', stats.unique_companies);
    animateNumber('statCities', stats.unique_cities);
    animateNumber('statDuplicates', stats.duplicate_count);
    animateNumber('statPersonal', stats.email_types.personal || 0);

    // Update quality score
    const score = stats.quality_score;
    document.getElementById('qualityScoreValue').textContent = score;
    document.getElementById('sidebarQualityScore').textContent = score + '%';
    document.getElementById('sidebarQualityBar').style.width = score + '%';

    // Animate quality ring
    const ring = document.getElementById('qualityRing');
    const circumference = 2 * Math.PI * 42;
    ring.style.strokeDasharray = circumference;
    ring.style.strokeDashoffset = circumference - (score / 100) * circumference;

    // Update contacts badge
    document.getElementById('contactsBadge').textContent = stats.total_contacts;

    // Update dup change badge
    const dupChange = document.getElementById('dupChange');
    if (stats.duplicate_count > 0) {
      dupChange.textContent = 'Needs cleanup';
      dupChange.className = 'stat-change negative';
    } else {
      dupChange.textContent = 'All clean!';
      dupChange.className = 'stat-change positive';
    }

    // Populate city filter dropdown
    populateCityFilter(stats.all_cities);

    // Render charts
    renderDashboardCharts(stats);
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
}

function populateCityFilter(cities) {
  const select = document.getElementById('cityFilter');
  const currentValue = select.value;
  select.innerHTML = '<option value="">All Cities</option>';
  cities.forEach(city => {
    const opt = document.createElement('option');
    opt.value = city;
    opt.textContent = city;
    select.appendChild(opt);
  });
  select.value = currentValue;
}

function renderDashboardCharts(stats) {
  // Cities Bar Chart
  const citiesCtx = document.getElementById('citiesChart');
  if (state.charts.cities) state.charts.cities.destroy();

  const topCities = stats.top_cities.slice(0, 12);
  state.charts.cities = new Chart(citiesCtx, {
    type: 'bar',
    data: {
      labels: topCities.map(c => c[0]),
      datasets: [{
        label: 'Contacts',
        data: topCities.map(c => c[1]),
        backgroundColor: createGradientColors(topCities.length, citiesCtx),
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          grid: { color: 'rgba(148,163,184,0.06)' },
          ticks: { color: '#64748b', font: { size: 11 } },
        },
        y: {
          grid: { color: 'rgba(148,163,184,0.06)' },
          ticks: { color: '#64748b' },
        }
      }
    }
  });

  // Email Type Doughnut
  const typeCtx = document.getElementById('emailTypeChart');
  if (state.charts.emailType) state.charts.emailType.destroy();

  state.charts.emailType = new Chart(typeCtx, {
    type: 'doughnut',
    data: {
      labels: Object.keys(stats.email_types).map(k => k.charAt(0).toUpperCase() + k.slice(1)),
      datasets: [{
        data: Object.values(stats.email_types),
        backgroundColor: ['#06b6d4', '#f59e0b', '#ef4444'],
        borderColor: '#111827',
        borderWidth: 3,
        hoverBorderWidth: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#94a3b8', padding: 16, font: { size: 12 } }
        }
      }
    }
  });
}


// ═══════════════════════════════════════════════════════════════════════
// CONTACTS TABLE
// ═══════════════════════════════════════════════════════════════════════

async function loadContacts() {
  const search = document.getElementById('searchInput')?.value || '';
  const city = document.getElementById('cityFilter')?.value || '';
  const emailType = document.getElementById('typeFilter')?.value || '';
  const valStatus = document.getElementById('statusFilter')?.value || '';

  let url = `/api/contacts?page=${state.currentPage}&per_page=${state.perPage}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (city) url += `&city=${encodeURIComponent(city)}`;
  if (emailType) url += `&email_type=${encodeURIComponent(emailType)}`;
  if (valStatus) url += `&validation_status=${encodeURIComponent(valStatus)}`;

  try {
    const data = await api(url);
    state.contacts = data.contacts;
    state.totalContacts = data.total;
    state.totalPages = data.total_pages;
    state.currentPage = data.page;
    state.selectedIds.clear();
    document.getElementById('selectAll').checked = false;
    updateBulkDeleteBtn();

    renderContactsTable();
    renderPagination();
    document.getElementById('tableInfo').textContent =
      `Showing ${(data.page - 1) * data.per_page + 1}–${Math.min(data.page * data.per_page, data.total)} of ${data.total} contacts`;
  } catch (e) {
    console.error('Failed to load contacts:', e);
  }
}

function renderContactsTable() {
  const tbody = document.getElementById('contactsTable');
  if (!state.contacts.length) {
    tbody.innerHTML = `
      <tr><td colspan="7">
        <div class="empty-state">
          <div class="empty-icon"><i data-lucide="inbox" style="width:48px;height:48px;"></i></div>
          <div class="empty-title">No contacts found</div>
          <div class="empty-desc">Try adjusting your search or filters</div>
        </div>
      </td></tr>`;
    refreshIcons();
    return;
  }

  tbody.innerHTML = state.contacts.map(c => {
    const typeBadge = getTypeBadge(c.email_type);
    const statusBadge = getStatusBadge(c.validation?.status);
    const checked = state.selectedIds.has(c.id) ? 'checked' : '';

    return `
      <tr>
        <td class="checkbox-cell">
          <input type="checkbox" ${checked} onchange="toggleSelect(${c.id})">
        </td>
        <td title="${escapeHtml(c.company)}">${escapeHtml(c.company)}</td>
        <td title="${escapeHtml(c.location)}">${escapeHtml(c.location)}</td>
        <td style="font-family: monospace; font-size: 13px;" title="${escapeHtml(c.email)}">${escapeHtml(c.email)}</td>
        <td>${typeBadge}</td>
        <td>${statusBadge}</td>
        <td>
          <div class="action-cell">
            <button class="action-btn copy" title="Copy email" onclick="copyEmail('${escapeHtml(c.email)}')"><i data-lucide="clipboard-copy" style="width:14px;height:14px;"></i></button>
            <button class="action-btn edit" title="Edit" onclick='openEditModal(${JSON.stringify(c).replace(/'/g, "&#39;")})'><i data-lucide="pencil" style="width:14px;height:14px;"></i></button>
            <button class="action-btn validate" title="Validate" onclick="validateFromTable('${escapeHtml(c.email)}')"><i data-lucide="check-circle" style="width:14px;height:14px;"></i></button>
            <button class="action-btn delete" title="Delete" onclick="deleteContact(${c.id})"><i data-lucide="trash-2" style="width:14px;height:14px;"></i></button>
          </div>
        </td>
      </tr>`;
  }).join('');
  refreshIcons();
}

function getTypeBadge(type) {
  const badges = {
    corporate: '<span class="badge badge-corporate">Corporate</span>',
    personal: '<span class="badge badge-warning">Personal</span>',
    invalid: '<span class="badge badge-danger">Invalid</span>',
  };
  return badges[type] || '<span class="badge badge-neutral">Unknown</span>';
}

function getStatusBadge(status) {
  const badges = {
    verified: '<span class="badge badge-success"><i data-lucide="circle-check" style="width:12px;height:12px;"></i> Verified</span>',
    mx_valid: '<span class="badge badge-info"><i data-lucide="server" style="width:12px;height:12px;"></i> MX Valid</span>',
    valid_syntax: '<span class="badge badge-neutral"><i data-lucide="check" style="width:12px;height:12px;"></i> Syntax OK</span>',
    no_mx: '<span class="badge badge-warning"><i data-lucide="alert-triangle" style="width:12px;height:12px;"></i> No MX</span>',
    rejected: '<span class="badge badge-danger"><i data-lucide="x-circle" style="width:12px;height:12px;"></i> Rejected</span>',
    invalid_syntax: '<span class="badge badge-danger"><i data-lucide="x" style="width:12px;height:12px;"></i> Invalid</span>',
  };
  return badges[status] || '<span class="badge badge-neutral"><i data-lucide="clock" style="width:12px;height:12px;"></i> Pending</span>';
}


// ─── Pagination ──────────────────────────────────────────────────────

function renderPagination() {
  const container = document.getElementById('pagination');
  if (state.totalPages <= 1) {
    container.innerHTML = '';
    return;
  }

  let html = '';
  html += `<button class="page-btn" ${state.currentPage <= 1 ? 'disabled' : ''} onclick="goToPage(${state.currentPage - 1})">‹</button>`;

  const pages = getPaginationRange(state.currentPage, state.totalPages);
  pages.forEach(p => {
    if (p === '...') {
      html += `<span style="color: var(--text-muted); padding: 0 4px;">…</span>`;
    } else {
      html += `<button class="page-btn ${p === state.currentPage ? 'active' : ''}" onclick="goToPage(${p})">${p}</button>`;
    }
  });

  html += `<button class="page-btn" ${state.currentPage >= state.totalPages ? 'disabled' : ''} onclick="goToPage(${state.currentPage + 1})">›</button>`;
  container.innerHTML = html;
}

function getPaginationRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = [];
  if (current <= 3) {
    pages.push(1, 2, 3, 4, '...', total);
  } else if (current >= total - 2) {
    pages.push(1, '...', total - 3, total - 2, total - 1, total);
  } else {
    pages.push(1, '...', current - 1, current, current + 1, '...', total);
  }
  return pages;
}

function goToPage(page) {
  if (page < 1 || page > state.totalPages) return;
  state.currentPage = page;
  loadContacts();
}


// ─── Search (debounced) ──────────────────────────────────────────────

function debounceSearch() {
  clearTimeout(state.searchTimeout);
  state.searchTimeout = setTimeout(() => {
    state.currentPage = 1;
    loadContacts();
  }, 300);
}


// ─── Selection ───────────────────────────────────────────────────────

function toggleSelect(id) {
  if (state.selectedIds.has(id)) {
    state.selectedIds.delete(id);
  } else {
    state.selectedIds.add(id);
  }
  updateBulkDeleteBtn();
}

function toggleSelectAll() {
  const checked = document.getElementById('selectAll').checked;
  if (checked) {
    state.contacts.forEach(c => state.selectedIds.add(c.id));
  } else {
    state.selectedIds.clear();
  }
  renderContactsTable();
  updateBulkDeleteBtn();
}

function updateBulkDeleteBtn() {
  const btn = document.getElementById('bulkDeleteBtn');
  if (state.selectedIds.size > 0) {
    btn.style.display = 'inline-flex';
    btn.innerHTML = `<i data-lucide="trash-2" class="btn-lucide"></i> Delete Selected (${state.selectedIds.size})`;
    refreshIcons();
  } else {
    btn.style.display = 'none';
  }
}


// ═══════════════════════════════════════════════════════════════════════
// CRUD OPERATIONS
// ═══════════════════════════════════════════════════════════════════════

async function addContact(e) {
  e.preventDefault();
  const company = document.getElementById('addCompany').value.trim();
  const location = document.getElementById('addLocation').value.trim();
  const email = document.getElementById('addEmail').value.trim();

  try {
    await api('/api/contacts', {
      method: 'POST',
      body: JSON.stringify({ company, location, email }),
    });
    showToast(`Contact "${company}" added successfully!`, 'success');
    document.getElementById('addContactForm').reset();
    document.getElementById('liveValidationResult').style.display = 'none';
    document.getElementById('emailValidationHint').textContent = '';
    loadStats();
  } catch (e) {
    // Error already shown by api()
  }
}

function openEditModal(contact) {
  document.getElementById('editId').value = contact.id;
  document.getElementById('editCompany').value = contact.company;
  document.getElementById('editLocation').value = contact.location;
  document.getElementById('editEmail').value = contact.email;
  document.getElementById('editModal').classList.add('active');
}

function closeEditModal() {
  document.getElementById('editModal').classList.remove('active');
}

async function saveEdit() {
  const id = document.getElementById('editId').value;
  const company = document.getElementById('editCompany').value.trim();
  const location = document.getElementById('editLocation').value.trim();
  const email = document.getElementById('editEmail').value.trim();

  try {
    await api(`/api/contacts/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ company, location, email }),
    });
    showToast('Contact updated!', 'success');
    closeEditModal();
    loadContacts();
    loadStats();
  } catch (e) {}
}

async function deleteContact(id) {
  if (!confirm('Are you sure you want to delete this contact?')) return;
  try {
    await api(`/api/contacts/${id}`, { method: 'DELETE' });
    showToast('Contact deleted', 'success');
    loadContacts();
    loadStats();
  } catch (e) {}
}

async function bulkDelete() {
  if (!confirm(`Delete ${state.selectedIds.size} selected contacts?`)) return;
  try {
    await api('/api/contacts/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids: Array.from(state.selectedIds) }),
    });
    showToast(`${state.selectedIds.size} contacts deleted`, 'success');
    state.selectedIds.clear();
    loadContacts();
    loadStats();
  } catch (e) {}
}


// ═══════════════════════════════════════════════════════════════════════
// EMAIL VALIDATION
// ═══════════════════════════════════════════════════════════════════════

function liveValidateEmail() {
  const email = document.getElementById('addEmail').value.trim();
  const hint = document.getElementById('emailValidationHint');
  const input = document.getElementById('addEmail');

  if (!email) {
    hint.textContent = '';
    input.classList.remove('is-valid', 'is-invalid');
    return;
  }

  const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  if (emailRegex.test(email)) {
    const domain = email.split('@')[1];
    const personalDomains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com'];
    if (personalDomains.includes(domain.toLowerCase())) {
      hint.textContent = '⚠️ This is a personal email domain';
      hint.className = 'form-hint';
      hint.style.color = 'var(--warning)';
    } else {
      hint.textContent = '✓ Valid email format (corporate domain)';
      hint.className = 'form-hint';
      hint.style.color = 'var(--success)';
    }
    input.classList.add('is-valid');
    input.classList.remove('is-invalid');
  } else {
    hint.textContent = '✕ Invalid email format';
    hint.className = 'form-error';
    hint.style.color = '';
    input.classList.add('is-invalid');
    input.classList.remove('is-valid');
  }
}

async function validateSingleEmail() {
  const email = document.getElementById('validateEmailInput').value.trim();
  if (!email) {
    showToast('Please enter an email to validate', 'warning');
    return;
  }

  const container = document.getElementById('singleValidationResult');
  container.innerHTML = '<div class="loading-overlay"><div class="spinner"></div> Validating...</div>';

  try {
    const result = await api('/api/validate-email', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });

    container.innerHTML = renderValidationResult(result);
  } catch (e) {
    container.innerHTML = '';
  }
}

async function validateFromTable(email) {
  showToast(`Validating ${email}...`, 'info');
  try {
    const result = await api('/api/validate-email', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
    showToast(`${email}: ${formatStatus(result.status)}`, 
      result.status === 'verified' ? 'success' : 
      result.status === 'rejected' ? 'error' : 'info');
    loadContacts();
  } catch (e) {}
}

function renderValidationResult(result) {
  const html = `
    <div class="validation-result">
      <h4 style="margin-bottom: 12px; font-size: 14px; color: var(--text-secondary);">
        Results for <span style="color: var(--accent-primary); font-family: monospace;">${escapeHtml(result.email)}</span>
      </h4>
      <div class="validation-steps">
        <div class="validation-step">
          <div class="step-icon ${result.syntax ? 'pass' : 'fail'}"><i data-lucide="${result.syntax ? 'check' : 'x'}" style="width:16px;height:16px;"></i></div>
          <div>
            <div class="step-label">Syntax Validation</div>
            <div class="step-detail">${result.syntax ? 'Email format is valid' : 'Invalid email format'}</div>
          </div>
        </div>
        <div class="validation-step">
          <div class="step-icon ${result.mx === true ? 'pass' : result.mx === false ? 'fail' : 'pending'}">
            <i data-lucide="${result.mx === true ? 'check' : result.mx === false ? 'x' : 'minus'}" style="width:16px;height:16px;"></i>
          </div>
          <div>
            <div class="step-label">MX Record Check</div>
            <div class="step-detail">${
              result.mx === true ? `Domain has valid mail servers (${result.mx_hosts?.length || 0} MX records)` :
              result.mx === false ? 'No mail servers found for this domain' : 'Not checked'
            }</div>
          </div>
        </div>
        <div class="validation-step">
          <div class="step-icon ${result.smtp === true ? 'pass' : result.smtp === false ? 'fail' : 'pending'}">
            <i data-lucide="${result.smtp === true ? 'check' : result.smtp === false ? 'x' : 'minus'}" style="width:16px;height:16px;"></i>
          </div>
          <div>
            <div class="step-label">SMTP Verification</div>
            <div class="step-detail">${
              result.smtp === true ? 'Mailbox exists and accepts mail' :
              result.smtp === false ? 'Mailbox does not exist (rejected)' : 'Inconclusive or not checked'
            }</div>
          </div>
        </div>
      </div>
      <div class="mt-16 flex-between">
        <span class="text-sm text-muted">Overall Status:</span>
        ${getStatusBadge(result.status)}
      </div>
    </div>`;
  setTimeout(refreshIcons, 50);
  return html;
}


// ─── Bulk Validation ────────────────────────────────────────────────

async function startBulkValidation() {
  try {
    await api('/api/validate-bulk', { method: 'POST' });
    document.getElementById('bulkValidationProgress').style.display = 'block';
    document.getElementById('startBulkBtn').disabled = true;
    document.getElementById('startBulkBtn').innerHTML = '<i data-lucide="loader" class="btn-lucide spin"></i> Running...';
    refreshIcons();
    pollBulkStatus();
  } catch (e) {}
}

function pollBulkStatus() {
  state.bulkPolling = setInterval(async () => {
    try {
      const status = await api('/api/validate-bulk/status');
      const percent = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;

      document.getElementById('bulkProgressBar').style.width = percent + '%';
      document.getElementById('bulkProgressText').textContent = `${status.processed} / ${status.total}`;
      document.getElementById('bulkProgressPercent').textContent = percent + '%';

      document.getElementById('bulkVerified').textContent = status.results.verified || 0;
      document.getElementById('bulkMxValid').textContent = status.results.mx_valid || 0;
      document.getElementById('bulkNoMx').textContent = status.results.no_mx || 0;
      document.getElementById('bulkRejected').textContent = status.results.rejected || 0;

      if (!status.running) {
        clearInterval(state.bulkPolling);
        document.getElementById('startBulkBtn').disabled = false;
        document.getElementById('startBulkBtn').innerHTML = '<i data-lucide="rocket" class="btn-lucide"></i> Start Bulk Validation';
        refreshIcons();
        showToast('Bulk validation completed!', 'success');
        loadStats();
      }
    } catch (e) {
      clearInterval(state.bulkPolling);
    }
  }, 2000);
}

async function stopBulkValidation() {
  try {
    await api('/api/validate-bulk/stop', { method: 'POST' });
    clearInterval(state.bulkPolling);
    document.getElementById('startBulkBtn').disabled = false;
    document.getElementById('startBulkBtn').innerHTML = '<i data-lucide="rocket" class="btn-lucide"></i> Start Bulk Validation';
    refreshIcons();
    showToast('Bulk validation stopped', 'warning');
  } catch (e) {}
}


// ═══════════════════════════════════════════════════════════════════════
// DATA CLEANING
// ═══════════════════════════════════════════════════════════════════════

async function runCleanOperation(operation) {
  try {
    const result = await api('/api/clean', {
      method: 'POST',
      body: JSON.stringify({ operation }),
    });

    showToast(`${result.message} — ${result.changes_count} changes`, 'success');

    // Show results
    const resultsDiv = document.getElementById('cleanerResults');
    resultsDiv.style.display = 'block';
    document.getElementById('cleanerResultTitle').textContent =
      formatOperationName(operation) + ' Results';
    document.getElementById('cleanerResultCount').textContent =
      result.changes_count + ' changes';

    const body = document.getElementById('cleanerResultBody');
    if (result.changes_count === 0) {
      body.innerHTML = '<p class="text-muted text-center" style="padding: 20px;">No changes needed — data is already clean!</p>';
    } else {
      body.innerHTML = `
        <div class="changes-list">
          ${result.changes.map(ch => renderChange(ch)).join('')}
          ${result.changes_count > 100 ? `<p class="text-sm text-muted text-center mt-8">...and ${result.changes_count - 100} more</p>` : ''}
        </div>`;
    }

    loadStats();
  } catch (e) {}
}

async function previewDedup() {
  try {
    const result = await api('/api/dedup', {
      method: 'POST',
      body: JSON.stringify({ preview: true }),
    });

    const resultsDiv = document.getElementById('cleanerResults');
    resultsDiv.style.display = 'block';
    document.getElementById('cleanerResultTitle').textContent = 'Duplicate Preview';
    document.getElementById('cleanerResultCount').textContent =
      result.duplicates_found + ' duplicates';

    const body = document.getElementById('cleanerResultBody');
    if (result.duplicates_found === 0) {
      body.innerHTML = '<p class="text-muted text-center" style="padding: 20px;">No duplicates found!</p>';
    } else {
      body.innerHTML = `
        <p class="text-sm mb-16">Found <strong>${result.duplicates_found}</strong> duplicate emails. Preview:</p>
        <div class="changes-list">
          ${result.duplicates.map(d => `
            <div class="change-item">
              <span class="badge badge-danger">DUP</span>
              <span style="flex:1">${escapeHtml(d.duplicate.company)}</span>
              <span style="font-family:monospace; font-size:12px; color:var(--text-muted)">${escapeHtml(d.duplicate.email)}</span>
            </div>
          `).join('')}
        </div>`;
    }
  } catch (e) {}
}

async function applyDedup() {
  if (!confirm('This will permanently remove all duplicate entries. Continue?')) return;
  try {
    const result = await api('/api/dedup', {
      method: 'POST',
      body: JSON.stringify({ preview: false }),
    });
    showToast(`Removed ${result.duplicates_found} duplicates! ${result.records_after} records remaining.`, 'success');
    loadStats();
    loadContacts();

    // Update results panel
    const body = document.getElementById('cleanerResultBody');
    body.innerHTML = `<p class="text-center" style="padding: 20px; color: var(--success);">
      ✓ ${result.duplicates_found} duplicates removed. ${result.records_after} clean records remaining.</p>`;
  } catch (e) {}
}

function renderChange(change) {
  if (change.action === 'removed') {
    return `<div class="change-item">
      <span class="badge badge-danger">Removed</span>
      <span style="flex:1">${escapeHtml(change.email || change.company || '')}</span>
      <span class="text-sm text-muted">${change.reason}</span>
    </div>`;
  }
  return `<div class="change-item">
    <span class="text-sm text-muted">#${change.id}</span>
    <span class="change-old">${escapeHtml(Array.isArray(change.old) ? change.old.join(', ') : change.old)}</span>
    <span class="change-arrow">→</span>
    <span class="change-new">${escapeHtml(Array.isArray(change.new) ? change.new.join(', ') : change.new)}</span>
  </div>`;
}

function formatOperationName(op) {
  return op.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}


// ═══════════════════════════════════════════════════════════════════════
// ANALYTICS
// ═══════════════════════════════════════════════════════════════════════

async function loadAnalytics() {
  if (!state.stats) await loadStats();
  const stats = state.stats;

  // Top Cities horizontal bar
  const citiesCtx = document.getElementById('analyticsCitiesChart');
  if (state.charts.analyticsCities) state.charts.analyticsCities.destroy();

  const topCities = stats.top_cities.slice(0, 15);
  state.charts.analyticsCities = new Chart(citiesCtx, {
    type: 'bar',
    data: {
      labels: topCities.map(c => c[0]),
      datasets: [{
        label: 'Contacts',
        data: topCities.map(c => c[1]),
        backgroundColor: topCities.map((_, i) =>
          `hsla(${180 + i * 12}, 70%, 55%, 0.8)`),
        borderRadius: 4,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(148,163,184,0.06)' }, ticks: { color: '#64748b' } },
        y: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 12 } } }
      }
    }
  });

  // Top Domains horizontal bar
  const domainsCtx = document.getElementById('analyticsDomainsChart');
  if (state.charts.analyticsDomains) state.charts.analyticsDomains.destroy();

  const topDomains = stats.top_domains.slice(0, 15);
  state.charts.analyticsDomains = new Chart(domainsCtx, {
    type: 'bar',
    data: {
      labels: topDomains.map(d => d[0]),
      datasets: [{
        label: 'Contacts',
        data: topDomains.map(d => d[1]),
        backgroundColor: topDomains.map((_, i) =>
          `hsla(${260 + i * 8}, 65%, 60%, 0.8)`),
        borderRadius: 4,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(148,163,184,0.06)' }, ticks: { color: '#64748b' } },
        y: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 11 } } }
      }
    }
  });

  // Validation Status Pie
  const valCtx = document.getElementById('analyticsValidationChart');
  if (state.charts.analyticsVal) state.charts.analyticsVal.destroy();

  const valLabels = Object.keys(stats.validation_statuses).map(formatStatus);
  const valColors = Object.keys(stats.validation_statuses).map(getStatusColor);

  state.charts.analyticsVal = new Chart(valCtx, {
    type: 'pie',
    data: {
      labels: valLabels,
      datasets: [{
        data: Object.values(stats.validation_statuses),
        backgroundColor: valColors,
        borderColor: '#111827',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { color: '#94a3b8', padding: 12, font: { size: 12 } } }
      }
    }
  });

  // Email Type Pie
  const typeCtx = document.getElementById('analyticsTypeChart');
  if (state.charts.analyticsType) state.charts.analyticsType.destroy();

  state.charts.analyticsType = new Chart(typeCtx, {
    type: 'pie',
    data: {
      labels: Object.keys(stats.email_types).map(k => k.charAt(0).toUpperCase() + k.slice(1)),
      datasets: [{
        data: Object.values(stats.email_types),
        backgroundColor: ['#06b6d4', '#f59e0b', '#ef4444', '#64748b'],
        borderColor: '#111827',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { color: '#94a3b8', padding: 12, font: { size: 12 } } }
      }
    }
  });
}


// ═══════════════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════════════

function exportData(format) {
  window.location.href = `/api/export?format=${format}`;
  showToast('Export started!', 'success');
}


// ═══════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════

function copyEmail(email) {
  navigator.clipboard.writeText(email).then(() => {
    showToast(`Copied: ${email}`, 'success');
  }).catch(() => {
    // Fallback
    const input = document.createElement('input');
    input.value = email;
    document.body.appendChild(input);
    input.select();
    document.execCommand('copy');
    document.body.removeChild(input);
    showToast(`Copied: ${email}`, 'success');
  });
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatStatus(status) {
  const map = {
    verified: 'Verified',
    mx_valid: 'MX Valid',
    valid_syntax: 'Syntax OK',
    no_mx: 'No MX',
    rejected: 'Rejected',
    invalid_syntax: 'Invalid',
  };
  return map[status] || status;
}

function getStatusColor(status) {
  const map = {
    verified: '#10b981',
    mx_valid: '#3b82f6',
    valid_syntax: '#94a3b8',
    no_mx: '#f59e0b',
    rejected: '#ef4444',
    invalid_syntax: '#dc2626',
  };
  return map[status] || '#64748b';
}

function animateNumber(elementId, target) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const duration = 800;
  const start = parseInt(el.textContent) || 0;
  const diff = target - start;
  const startTime = performance.now();

  function step(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
    el.textContent = Math.round(start + diff * eased).toLocaleString();
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function createGradientColors(count, ctx) {
  const colors = [];
  for (let i = 0; i < count; i++) {
    const hue = 180 + (i * (120 / count)); // cyan to purple
    colors.push(`hsla(${hue}, 70%, 55%, 0.8)`);
  }
  return colors;
}

function resetAddForm() {
  document.getElementById('liveValidationResult').style.display = 'none';
  document.getElementById('emailValidationHint').textContent = '';
  document.getElementById('addEmail').classList.remove('is-valid', 'is-invalid');
}


// ─── Toast Notifications ────────────────────────────────────────────

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const icons = {
    success: 'circle-check',
    error: 'circle-x',
    warning: 'triangle-alert',
    info: 'info'
  };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon"><i data-lucide="${icons[type]}" style="width:18px;height:18px;"></i></span>
    <span class="toast-message">${message}</span>
    <button class="toast-close" onclick="this.parentElement.remove()"><i data-lucide="x" style="width:14px;height:14px;"></i></button>
  `;
  refreshIcons();

  container.appendChild(toast);

  // Auto-remove after 4 seconds
  setTimeout(() => {
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
