let archiveDataCache = { direct_paid_fines: [], vignette_archive: [], qr_archive: [], totals: {} };

document.addEventListener('DOMContentLoaded', function () {
    const startDateInput = document.getElementById('archive-start-date');
    const endDateInput = document.getElementById('archive-end-date');
    const refreshBtn = document.getElementById('archive-refresh-btn');
    const searchInput = document.getElementById('archive-search');

    const today = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);

    if (startDateInput) startDateInput.value = start.toISOString().split('T')[0];
    if (endDateInput) endDateInput.value = today.toISOString().split('T')[0];

    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadArchiveData);
    }

    if (searchInput) {
        searchInput.addEventListener('input', renderArchiveTables);
    }

    loadArchiveData();
});

function loadArchiveData() {
    const startDate = document.getElementById('archive-start-date').value;
    const endDate = document.getElementById('archive-end-date').value;

    const query = new URLSearchParams();
    if (startDate) query.set('start_date', startDate);
    if (endDate) query.set('end_date', endDate);

    const url = '/api/vehicles/mobile-money-archive?' + query.toString();
    const fineBody = document.getElementById('archive-fines-tbody');
    const vignetteBody = document.getElementById('archive-vignettes-tbody');
    const qrBody = document.getElementById('archive-qr-tbody');
    if (fineBody) fineBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (vignetteBody) vignetteBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (qrBody) qrBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Chargement...</td></tr>';

    fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
            if (!r.ok) throw new Error('Erreur de chargement');
            return r.json();
        })
        .then(function (data) {
            archiveDataCache = data || { direct_paid_fines: [], vignette_archive: [], qr_archive: [], totals: {} };
            renderArchiveTables();
            updateSummaryCards();
        })
        .catch(function (err) {
            console.error('Archive load error:', err);
            if (fineBody) fineBody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (vignetteBody) vignetteBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (qrBody) qrBody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
        });
}

function renderArchiveTables() {
    const search = (document.getElementById('archive-search').value || '').toLowerCase().trim();
    const fineBody = document.getElementById('archive-fines-tbody');
    const vignetteBody = document.getElementById('archive-vignettes-tbody');
    const qrBody = document.getElementById('archive-qr-tbody');

    const fines = (archiveDataCache.direct_paid_fines || []).filter(function (item) {
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.reason, item.receipt_number, item.paid_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    const vignettes = (archiveDataCache.vignette_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.receipt_number, item.approved_by, item.payment_method]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    const qrs = (archiveDataCache.qr_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.owner_island, item.recorded_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    if (fineBody) {
        if (!fines.length) {
            fineBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Aucune amende payée trouvée</td></tr>';
        } else {
            fineBody.innerHTML = fines.map(function (fine, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td>' + escapeHtml(fine.license_plate || '-') + '</td>' +
                    '<td>' + escapeHtml(fine.owner_name || '-') + '</td>' +
                    '<td>' + escapeHtml(fine.reason || '-') + '</td>' +
                    '<td>' + escapeHtml(fine.receipt_number || '-') + '</td>' +
                    '<td>' + formatDate(fine.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold">' + formatKMF(fine.amount) + '</td>' +
                    '<td>' + escapeHtml(fine.paid_by || '-') + '</td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (vignetteBody) {
        if (!vignettes.length) {
            vignetteBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucune vignette payée trouvée</td></tr>';
        } else {
            vignetteBody.innerHTML = vignettes.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td>' + escapeHtml(item.license_plate || '-') + '</td>' +
                    '<td>' + escapeHtml(item.owner_name || '-') + '</td>' +
                    '<td>' + formatDate(item.paid_at) + '</td>' +
                    '<td class="text-end">' + formatKMF(item.vignette_price) + '</td>' +
                    '<td class="text-end text-warning">' + formatKMF(item.penalty_amount) + '</td>' +
                    '<td class="text-end text-danger">' + formatKMF(item.fines_amount) + '</td>' +
                    '<td class="text-end fw-semibold text-success">' + formatKMF(item.total_amount) + '</td>' +
                    '<td>' + escapeHtml(item.approved_by || '-') + '</td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (qrBody) {
        if (!qrs.length) {
            qrBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Aucun renouvellement QR trouvé</td></tr>';
        } else {
            qrBody.innerHTML = qrs.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + escapeHtml(item.license_plate || '-') + '</strong></td>' +
                    '<td>' + escapeHtml(item.owner_name || '-') + '</td>' +
                    '<td>' + escapeHtml(item.owner_island || '-') + '</td>' +
                    '<td>' + formatDate(item.paid_at) + '</td>' +
                    '<td><span class="badge bg-success">' + escapeHtml(item.new_expiry || '-') + '</span></td>' +
                    '<td class="text-end fw-semibold text-primary">' + formatKMF(item.amount) + '</td>' +
                    '<td>' + escapeHtml(item.recorded_by || '-') + '</td>' +
                    '</tr>';
            }).join('');
        }
    }
}

function updateSummaryCards() {
    const totals = archiveDataCache.totals || {};
    document.getElementById('archive-direct-count').textContent = totals.direct_fines_count || 0;
    document.getElementById('archive-direct-total').textContent = formatKMF(totals.direct_fines_total);
    document.getElementById('archive-vignette-count').textContent = totals.vignettes_count || 0;
    document.getElementById('archive-vignette-total').textContent = formatKMF(totals.vignette_total);
    document.getElementById('archive-qr-count').textContent = totals.qr_renewals_count || 0;
    document.getElementById('archive-qr-total').textContent = formatKMF(totals.qr_renewals_total);
    document.getElementById('archive-penalty-total').textContent = formatKMF(totals.vignette_penalties_total);
    document.getElementById('archive-included-fines-total').textContent = formatKMF(totals.vignette_included_fines_total);
}

function formatKMF(amount) {
    if (amount === null || amount === undefined || amount === '') return '0 KMF';
    const num = parseFloat(amount) || 0;
    return num.toLocaleString('fr-KM') + ' KMF';
}

function formatDate(value) {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleDateString('fr-FR');
    } catch (e) {
        return '-';
    }
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
