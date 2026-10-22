// ── Gestion des Paiements — onglet "Permis de conduire" ──

let lfpAllFines = [];       // flat fines for the current view (pending or archive)
let lfpAllLicenses = [];    // pending view only: grouped by license
let lfpFilteredLicenses = [];
let lfpFilteredArchive = [];
let lfpCurrentView = 'pending';
let lfpSelectedLicenseId = null;

document.addEventListener('DOMContentLoaded', function () {
    const permisTabBtn = document.getElementById('tab-payments-permis-btn');
    if (permisTabBtn) {
        let loadedOnce = false;
        permisTabBtn.addEventListener('shown.bs.tab', function () {
            if (!loadedOnce) {
                loadedOnce = true;
                lfpLoadPayments('pending');
            }
        });
    }

    const viewGroup = document.getElementById('lfp-view-group');
    if (viewGroup) {
        viewGroup.addEventListener('click', function (e) {
            const btn = e.target.closest('button[data-view]');
            if (!btn) return;
            viewGroup.querySelectorAll('button[data-view]').forEach(b => {
                b.classList.remove('btn-primary', 'active');
                b.classList.add('btn-outline-secondary');
            });
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-primary', 'active');
            lfpLoadPayments(btn.dataset.view);
        });
    }

    const searchInput = document.getElementById('lfp-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', function () { lfpFilterRows(this.value || ''); });
    }

    const openPayBtn = document.getElementById('lfp-open-pay-modal-btn');
    if (openPayBtn) {
        openPayBtn.addEventListener('click', function () {
            const detailsModal = bootstrap.Modal.getInstance(document.getElementById('lfpDetailsModal'));
            if (detailsModal) detailsModal.hide();
            if (lfpSelectedLicenseId) lfpOpenPayModal(lfpSelectedLicenseId);
        });
    }

    const confirmPayBtn = document.getElementById('lfp-confirm-pay-btn');
    if (confirmPayBtn) confirmPayBtn.addEventListener('click', lfpSubmitPayment);
});

function lfpLoadPayments(view) {
    lfpCurrentView = view;
    const tbody = document.getElementById('lfp-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Chargement...</td></tr>';

    const reasonCol = document.getElementById('lfp-reason-col');
    const dateCol = document.getElementById('lfp-date-column-header');
    const paidDateCol = document.getElementById('lfp-paid-date-column-header');
    const searchBar = document.getElementById('lfp-search-bar');
    const searchInput = document.getElementById('lfp-search-input');
    if (searchInput) searchInput.value = '';
    if (searchBar) searchBar.style.display = '';

    if (view === 'archive') {
        if (reasonCol) reasonCol.textContent = 'Motif';
        if (dateCol) { dateCol.textContent = 'Émise le'; dateCol.style.display = ''; }
        if (paidDateCol) paidDateCol.style.display = '';

        fetch('/api/licenses/fines?paid=true')
            .then(r => r.json())
            .then(data => {
                lfpAllFines = (Array.isArray(data) ? data : []).sort((a, b) => {
                    const da = a.paid_at ? new Date(a.paid_at) : new Date(0);
                    const db = b.paid_at ? new Date(b.paid_at) : new Date(0);
                    return db - da;
                });
                lfpFilteredArchive = lfpAllFines.slice();
                lfpRenderArchiveTable(lfpFilteredArchive);
            })
            .catch(() => { if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Erreur</td></tr>'; });
    } else {
        if (reasonCol) reasonCol.textContent = 'Infractions';
        if (dateCol) { dateCol.textContent = 'Dernière infraction'; dateCol.style.display = ''; }
        if (paidDateCol) paidDateCol.style.display = 'none';

        fetch('/api/licenses/fines?paid=false')
            .then(r => r.json())
            .then(data => {
                lfpAllFines = Array.isArray(data) ? data : [];
                lfpAllLicenses = lfpGroupByLicense(lfpAllFines);
                lfpFilteredLicenses = lfpAllLicenses.slice();
                lfpRenderPendingTable(lfpFilteredLicenses);
            })
            .catch(() => { if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Erreur</td></tr>'; });
    }
}

function lfpGroupByLicense(fines) {
    const groups = new Map();
    (fines || []).forEach(fine => {
        const key = String(fine.license_id);
        if (!groups.has(key)) {
            groups.set(key, {
                license_id: fine.license_id,
                license_number: fine.license_number || '',
                holder_name: [fine.holder_firstname, fine.holder_name].filter(Boolean).join(' '),
                total_amount: 0,
                count: 0,
                last_issued_at: null,
                fines: [],
            });
        }
        const group = groups.get(key);
        group.total_amount += Number(fine.amount || 0);
        group.count += 1;
        group.fines.push(fine);
        const d = fine.issued_at ? new Date(fine.issued_at) : null;
        if (d && (!group.last_issued_at || d > group.last_issued_at)) group.last_issued_at = d;
    });
    return Array.from(groups.values()).sort((a, b) => {
        const da = a.last_issued_at ? a.last_issued_at.getTime() : 0;
        const db = b.last_issued_at ? b.last_issued_at.getTime() : 0;
        return db - da;
    });
}

function lfpFilterRows(query) {
    const q = (query || '').toLowerCase().trim();
    if (lfpCurrentView === 'archive') {
        lfpFilteredArchive = !q ? lfpAllFines.slice() : lfpAllFines.filter(f =>
            (f.license_number || '').toLowerCase().includes(q) ||
            (f.holder_name || '').toLowerCase().includes(q) ||
            (f.reason_label || '').toLowerCase().includes(q) ||
            (f.receipt_number || '').toLowerCase().includes(q)
        );
        lfpRenderArchiveTable(lfpFilteredArchive);
    } else {
        lfpFilteredLicenses = !q ? lfpAllLicenses.slice() : lfpAllLicenses.filter(lic =>
            (lic.license_number || '').toLowerCase().includes(q) ||
            (lic.holder_name || '').toLowerCase().includes(q) ||
            lic.fines.some(f => (f.reason_label || '').toLowerCase().includes(q))
        );
        lfpRenderPendingTable(lfpFilteredLicenses);
    }
}

function lfpFormatDate(dt) {
    if (!dt) return '-';
    try {
        const d = new Date(dt);
        if (isNaN(d)) return dt;
        return d.toLocaleDateString('fr-FR');
    } catch (e) { return dt; }
}

function lfpRenderPendingTable(items) {
    const tbody = document.getElementById('lfp-tbody');
    if (!tbody) return;
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Aucun permis avec amende impayée.</td></tr>';
        return;
    }
    tbody.innerHTML = items.map((lic, idx) => `<tr>
        <td>${idx + 1}</td>
        <td><strong>${lic.license_number}</strong></td>
        <td>${lic.holder_name}</td>
        <td><span class="badge bg-primary">${lic.count}</span></td>
        <td>${Math.round(lic.total_amount)} KMF</td>
        <td>${lfpFormatDate(lic.last_issued_at)}</td>
        <td><span class="status-badge-unpaid">Impayée</span></td>
        <td class="d-flex gap-1 flex-wrap">
          <button class="btn btn-sm btn-outline-secondary" data-lfp-details-id="${lic.license_id}"><i class="fas fa-eye me-1"></i>Détails</button>
          <button class="btn btn-sm btn-success" data-lfp-pay-id="${lic.license_id}"><i class="fas fa-check me-1"></i>Accepter Paiement</button>
        </td>
    </tr>`).join('');

    tbody.querySelectorAll('[data-lfp-details-id]').forEach(btn => {
        btn.addEventListener('click', function () { lfpOpenDetailsModal(this.getAttribute('data-lfp-details-id')); });
    });
    tbody.querySelectorAll('[data-lfp-pay-id]').forEach(btn => {
        btn.addEventListener('click', function () { lfpOpenPayModal(this.getAttribute('data-lfp-pay-id')); });
    });
}

function lfpRenderArchiveTable(items) {
    const tbody = document.getElementById('lfp-tbody');
    if (!tbody) return;
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Aucune amende archivée.</td></tr>';
        return;
    }
    tbody.innerHTML = items.map((f, idx) => `<tr>
        <td>${idx + 1}</td>
        <td><strong>${f.license_number || f.license_id}</strong></td>
        <td>${[f.holder_firstname, f.holder_name].filter(Boolean).join(' ')}</td>
        <td>${f.reason_label}</td>
        <td>${Math.round(f.amount)} KMF</td>
        <td>${lfpFormatDate(f.issued_at)}</td>
        <td>${lfpFormatDate(f.paid_at)}</td>
        <td><span class="status-badge-paid">Payée</span></td>
        <td class="text-muted small">${f.paid_by || ''}</td>
    </tr>`).join('');
}

function lfpOpenDetailsModal(licenseId) {
    const lic = lfpAllLicenses.find(item => String(item.license_id) === String(licenseId));
    if (!lic) return;

    lfpSelectedLicenseId = licenseId;

    document.getElementById('lfp-details-title').textContent = 'Permis ' + (lic.license_number || '');
    document.getElementById('lfp-details-subtitle').textContent =
        (lic.holder_name || '-') + ' • ' + lic.count + ' infraction(s) • ' + Math.round(lic.total_amount || 0) + ' KMF';

    document.getElementById('lfp-details-tbody').innerHTML = lic.fines.map((fine, index) => `<tr>
        <td>${index + 1}</td>
        <td>${fine.reason_label || ''}</td>
        <td>${Math.round(fine.amount || 0)} KMF</td>
        <td>${fine.issued_at_str || lfpFormatDate(fine.issued_at)}</td>
    </tr>`).join('');

    new bootstrap.Modal(document.getElementById('lfpDetailsModal')).show();
}

function lfpOpenPayModal(licenseId) {
    lfpSelectedLicenseId = licenseId;
    const lic = lfpAllLicenses.find(item => String(item.license_id) === String(licenseId));
    const text = document.getElementById('lfp-pay-text');
    if (text && lic) {
        text.textContent = 'Confirmer le paiement groupé du permis ' + (lic.license_number || '') + ' pour ' + lic.count + ' infraction(s) et ' + Math.round(lic.total_amount || 0) + ' KMF ?';
    }
    new bootstrap.Modal(document.getElementById('lfpPayModal')).show();
}

function lfpSubmitPayment() {
    if (!lfpSelectedLicenseId) return;
    const method = document.getElementById('lfp-pay-method').value || 'cash';

    fetch(`/api/licenses/${lfpSelectedLicenseId}/fines/pay-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_method: method }),
    })
        .then(r => { if (!r.ok) return r.json().then(x => { throw new Error(x.error || 'Erreur de paiement'); }); return r.json(); })
        .then(() => {
            const modal = bootstrap.Modal.getInstance(document.getElementById('lfpPayModal'));
            if (modal) modal.hide();
            if (window.showSuccess) window.showSuccess('Paiement groupé confirmé');
            else alert('Paiement groupé confirmé');
            lfpLoadPayments('pending');
        })
        .catch(err => alert(err.message || 'Erreur lors de la confirmation du paiement'));
}
