let archiveDataCache = { direct_paid_fines: [], vignette_archive: [], cg_archive: [], vt_archive: [], license_fine_archive: [], licence_pro_archive: [], dossier_permis_archive: [], totals: {} };

function applyPeriod(period) {
    const startInput = document.getElementById('archive-start-date');
    const endInput = document.getElementById('archive-end-date');
    const startCol = document.getElementById('custom-start-col');
    const endCol = document.getElementById('custom-end-col');
    const today = new Date();
    const fmt = d => d.toLocaleDateString('en-CA');

    // Show/hide the date inputs depending on the period
    const isCustom = (period === 'custom');
    if (startCol) startCol.style.display = isCustom ? '' : 'none';
    if (endCol) endCol.style.display = isCustom ? '' : 'none';

    if (period === 'all') {
        if (startInput) startInput.value = '';
        if (endInput) endInput.value = '';
    } else if (period === 'today') {
        if (startInput) startInput.value = fmt(today);
        if (endInput) endInput.value = fmt(today);
    } else if (period === '7') {
        const s = new Date(today); s.setDate(s.getDate() - 7);
        if (startInput) startInput.value = fmt(s);
        if (endInput) endInput.value = fmt(today);
    } else if (period === '30') {
        const s = new Date(today); s.setDate(s.getDate() - 30);
        if (startInput) startInput.value = fmt(s);
        if (endInput) endInput.value = fmt(today);
    } else if (period === 'month') {
        const s = new Date(today.getFullYear(), today.getMonth(), 1);
        if (startInput) startInput.value = fmt(s);
        if (endInput) endInput.value = fmt(today);
    } else if (period === 'year') {
        const s = new Date(today.getFullYear(), 0, 1);
        if (startInput) startInput.value = fmt(s);
        if (endInput) endInput.value = fmt(today);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const periodSelect = document.getElementById('archive-period');
    const refreshBtn = document.getElementById('archive-refresh-btn');
    const searchInput = document.getElementById('archive-search');

    // Initialize with default period (30 days), hide date inputs
    applyPeriod('30');

    if (periodSelect) {
        periodSelect.addEventListener('change', function () {
            applyPeriod(this.value);
            loadArchiveData();
        });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadArchiveData);
    }

    if (searchInput) {
        searchInput.addEventListener('input', renderArchiveTables);
    }

    const islandScopeEl = document.getElementById('mm-island-scope');
    if (islandScopeEl) {
        islandScopeEl.addEventListener('change', loadArchiveData);
    }

    loadArchiveData();
});

function mmIslandScope() {
    const el = document.getElementById('mm-island-scope');
    return el ? el.value : 'mine';
}

function loadArchiveData() {
    const startDate = (document.getElementById('archive-start-date') || {}).value || '';
    const endDate = (document.getElementById('archive-end-date') || {}).value || '';
    const period = (document.getElementById('archive-period') || {}).value || '30';

    const query = new URLSearchParams();
    query.set('island_scope', mmIslandScope());
    if (period === 'all') {
        query.set('all', 'true');
    } else {
        if (startDate) query.set('start_date', startDate);
        if (endDate) query.set('end_date', endDate);
    }

    const url = '/api/vehicles/mobile-money-archive?' + query.toString();
    const fineBody = document.getElementById('archive-fines-tbody');
    const vignetteBody = document.getElementById('archive-vignettes-tbody');
    const cgBody = document.getElementById('archive-cg-tbody');
    const vtBody = document.getElementById('archive-vt-tbody');
    const lfBody = document.getElementById('archive-lf-tbody');
    const lpBody = document.getElementById('archive-lp-tbody');
    const dpBody = document.getElementById('archive-dp-tbody');
    if (fineBody) fineBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (vignetteBody) vignetteBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (cgBody) cgBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (vtBody) vtBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (lfBody) lfBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (lpBody) lpBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (dpBody) dpBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Chargement...</td></tr>';

    fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
            if (!r.ok) throw new Error('Erreur de chargement');
            return r.json();
        })
        .then(function (data) {
            archiveDataCache = data || { direct_paid_fines: [], vignette_archive: [], cg_archive: [], vt_archive: [], license_fine_archive: [], licence_pro_archive: [], dossier_permis_archive: [], totals: {} };
            renderArchiveTables();
            updateSummaryCards();
        })
        .catch(function (err) {
            console.error('Archive load error:', err);
            if (fineBody) fineBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (vignetteBody) vignetteBody.innerHTML = '<tr><td colspan="10" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (cgBody) cgBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (vtBody) vtBody.innerHTML = '<tr><td colspan="10" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (lfBody) lfBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (lpBody) lpBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (dpBody) dpBody.innerHTML = '<tr><td colspan="10" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
        });
}

function renderArchiveTables() {
    const search = (document.getElementById('archive-search').value || '').toLowerCase().trim();
    const fineBody = document.getElementById('archive-fines-tbody');
    const vignetteBody = document.getElementById('archive-vignettes-tbody');
    const cgBody = document.getElementById('archive-cg-tbody');
    const vtBody = document.getElementById('archive-vt-tbody');
    const lfBody = document.getElementById('archive-lf-tbody');
    const lpBody = document.getElementById('archive-lp-tbody');
    const dpBody = document.getElementById('archive-dp-tbody');

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

    const cgs = (archiveDataCache.cg_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.owner_island, item.receipt_number, item.paid_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    const vts = (archiveDataCache.vt_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.owner_island, item.paid_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    const licenseFines = (archiveDataCache.license_fine_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.license_number, item.holder_name, item.reason_label, item.receipt_number, item.paid_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    const licencePros = (archiveDataCache.licence_pro_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.lp_number, item.holder_name, item.activite_label, item.receipt_number, item.paid_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    const dossierPermis = (archiveDataCache.dossier_permis_archive || []).filter(function (item) {
        if (!search) return true;
        return [item.dossier_number, item.nin, item.telephone, item.country, item.receipt_number, item.paid_by]
            .some(function (field) { return String(field || '').toLowerCase().includes(search); });
    });

    if (fineBody) {
        if (!fines.length) {
            fineBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucune amende payée trouvée</td></tr>';
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
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printFineReceipt(' + fine.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (vignetteBody) {
        if (!vignettes.length) {
            vignetteBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Aucune vignette payée trouvée</td></tr>';
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
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printVignetteReceipt(' + item.vehicle_id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (cgBody) {
        if (!cgs.length) {
            cgBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucune carte grise trouvée</td></tr>';
        } else {
            cgBody.innerHTML = cgs.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + escapeHtml(item.license_plate || '-') + '</strong></td>' +
                    '<td>' + escapeHtml(item.owner_name || '-') + '</td>' +
                    '<td>' + escapeHtml(item.owner_island || '-') + '</td>' +
                    '<td>' + escapeHtml(item.receipt_number || '-') + '</td>' +
                    '<td>' + formatDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold text-primary">' + formatKMF(item.amount) + '</td>' +
                    '<td>' + escapeHtml(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printCgReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (vtBody) {
        if (!vts.length) {
            vtBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Aucune visite technique payée trouvée</td></tr>';
        } else {
            vtBody.innerHTML = vts.map(function (item, idx) {
                var channelBadge = item.channel === 'app_citoyen'
                    ? '<span class="badge bg-primary-subtle text-primary">App Citoyen</span>'
                    : '<span class="badge bg-secondary-subtle text-secondary">Agent Huri Money</span>';
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + escapeHtml(item.license_plate || '-') + '</strong></td>' +
                    '<td>' + escapeHtml(item.owner_name || '-') + '</td>' +
                    '<td>' + escapeHtml(item.owner_island || '-') + '</td>' +
                    '<td>' + escapeHtml(item.appointment_date || '-') + '</td>' +
                    '<td>' + escapeHtml(item.appointment_time || '-') + '</td>' +
                    '<td class="text-end fw-semibold text-info">' + formatKMF(item.amount) + '</td>' +
                    '<td>' + channelBadge + '</td>' +
                    '<td>' + escapeHtml(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printVtReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (lfBody) {
        if (!licenseFines.length) {
            lfBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucune amende de permis payée trouvée</td></tr>';
        } else {
            lfBody.innerHTML = licenseFines.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + escapeHtml(item.license_number || '-') + '</strong></td>' +
                    '<td>' + escapeHtml(item.holder_name || '-') + '</td>' +
                    '<td>' + escapeHtml(item.reason_label || '-') + '</td>' +
                    '<td>' + escapeHtml(item.receipt_number || '-') + '</td>' +
                    '<td>' + formatDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold text-danger">' + formatKMF(item.amount) + '</td>' +
                    '<td>' + escapeHtml(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printLicenseFineReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (lpBody) {
        if (!licencePros.length) {
            lpBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucune licence professionnelle payée trouvée</td></tr>';
        } else {
            lpBody.innerHTML = licencePros.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + escapeHtml(item.lp_number || '-') + '</strong></td>' +
                    '<td>' + escapeHtml(item.holder_name || '-') + '</td>' +
                    '<td>' + escapeHtml(item.activite_label || '-') + '</td>' +
                    '<td>' + escapeHtml(item.receipt_number || '-') + '</td>' +
                    '<td>' + formatDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold">' + formatKMF(item.amount) + '</td>' +
                    '<td>' + escapeHtml(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printLicenceProReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }

    if (dpBody) {
        if (!dossierPermis.length) {
            dpBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Aucun dossier permis payé trouvé</td></tr>';
        } else {
            dpBody.innerHTML = dossierPermis.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + escapeHtml(item.dossier_number || '-') + '</strong></td>' +
                    '<td>' + escapeHtml(item.nin || '-') + '</td>' +
                    '<td>' + escapeHtml(item.telephone || '-') + '</td>' +
                    '<td>' + escapeHtml(item.country || '-') + '</td>' +
                    '<td>' + escapeHtml(item.receipt_number || '-') + '</td>' +
                    '<td>' + formatDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold">' + formatKMF(item.amount) + '</td>' +
                    '<td>' + escapeHtml(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="printDossierPermisReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
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
    document.getElementById('archive-cg-count').textContent = totals.cg_count || 0;
    document.getElementById('archive-cg-total').textContent = formatKMF(totals.cg_total);
    document.getElementById('archive-penalty-total').textContent = formatKMF(totals.vignette_penalties_total);
    document.getElementById('archive-included-fines-total').textContent = formatKMF(totals.vignette_included_fines_total);
    document.getElementById('archive-vt-count').textContent = totals.vt_count || 0;
    document.getElementById('archive-vt-total').textContent = formatKMF(totals.vt_total);
    document.getElementById('archive-lf-count').textContent = totals.license_fines_count || 0;
    document.getElementById('archive-lf-total').textContent = formatKMF(totals.license_fines_total);
    document.getElementById('archive-lp-count').textContent = totals.licence_pro_count || 0;
    document.getElementById('archive-lp-total').textContent = formatKMF(totals.licence_pro_total);
    document.getElementById('archive-dp-count').textContent = totals.dossier_permis_count || 0;
    document.getElementById('archive-dp-total').textContent = formatKMF(totals.dossier_permis_total);
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

function openArchiveReceipt(opts) {
    document.getElementById('ar-receipt-title').textContent = opts.title || 'REÇU DE PAIEMENT';
    document.getElementById('ar-receipt-number').textContent = opts.receiptNumber || '-';
    document.getElementById('ar-receipt-rows').innerHTML = (opts.rows || []).map(function (row, idx, arr) {
        var isLast = idx === arr.length - 1;
        return '<tr' + (isLast ? ' class="receipt-total-row"' : '') + '>' +
            '<td>' + escapeHtml(row[0]) + '</td><td>' + escapeHtml(row[1]) + '</td></tr>';
    }).join('');
    document.getElementById('ar-receipt-agent').textContent = opts.agent || '-';
    new bootstrap.Modal(document.getElementById('arReceiptModal')).show();
}

function printFineReceipt(id) {
    const item = (archiveDataCache.direct_paid_fines || []).find(f => f.id === id);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — AMENDE',
        receiptNumber: item.receipt_number,
        rows: [
            ['Immatriculation', item.license_plate || '-'],
            ['Propriétaire', item.owner_name || '-'],
            ['Motif', item.reason || '-'],
            ['Payé le', formatDate(item.paid_at)],
            ['Montant payé', formatKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function printVignetteReceipt(vehicleId) {
    const item = (archiveDataCache.vignette_archive || []).find(v => v.vehicle_id === vehicleId);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — VIGNETTE',
        receiptNumber: item.receipt_number || ('VIGN-' + vehicleId + '-' + Math.floor(new Date(item.paid_at).getTime() / 1000)),
        rows: [
            ['Immatriculation', item.license_plate || '-'],
            ['Propriétaire', item.owner_name || '-'],
            ['Prix vignette', formatKMF(item.vignette_price)],
            ['Pénalité', formatKMF(item.penalty_amount)],
            ['Amendes incluses', formatKMF(item.fines_amount)],
            ['Payé le', formatDate(item.paid_at)],
            ['Total payé', formatKMF(item.total_amount)],
        ],
        agent: item.approved_by,
    });
}

function printCgReceipt(id) {
    const item = (archiveDataCache.cg_archive || []).find(c => c.id === id);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — CARTE GRISE',
        receiptNumber: item.receipt_number,
        rows: [
            ['Immatriculation', item.license_plate || '-'],
            ['Propriétaire', item.owner_name || '-'],
            ['Île', item.owner_island || '-'],
            ['Payé le', formatDate(item.paid_at)],
            ['Montant payé', formatKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function printVtReceipt(id) {
    const item = (archiveDataCache.vt_archive || []).find(v => v.id === id);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — VISITE TECHNIQUE',
        receiptNumber: item.receipt_number || ('VT-' + id + '-' + Math.floor(new Date(item.paid_at).getTime() / 1000)),
        rows: [
            ['Immatriculation', item.license_plate || '-'],
            ['Propriétaire', item.owner_name || '-'],
            ['Île', item.owner_island || '-'],
            ['Payé le', formatDate(item.paid_at)],
            ['Montant payé', formatKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function printLicenseFineReceipt(id) {
    const item = (archiveDataCache.license_fine_archive || []).find(f => f.id === id);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — AMENDE PERMIS',
        receiptNumber: item.receipt_number,
        rows: [
            ['N° Permis', item.license_number || '-'],
            ['Titulaire', item.holder_name || '-'],
            ['Motif', item.reason_label || '-'],
            ['Payé le', formatDate(item.paid_at)],
            ['Montant payé', formatKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function printLicenceProReceipt(id) {
    const item = (archiveDataCache.licence_pro_archive || []).find(l => l.id === id);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — LICENCE PROFESSIONNELLE',
        receiptNumber: item.receipt_number,
        rows: [
            ['N° LP', item.lp_number || '-'],
            ['Titulaire', item.holder_name || '-'],
            ['Activité', item.activite_label || '-'],
            ['Payé le', formatDate(item.paid_at)],
            ['Montant payé', formatKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function printDossierPermisReceipt(id) {
    const item = (archiveDataCache.dossier_permis_archive || []).find(d => d.id === id);
    if (!item) return;
    openArchiveReceipt({
        title: 'REÇU DE PAIEMENT — FRAIS DE DOSSIER',
        receiptNumber: item.receipt_number,
        rows: [
            ['NIN', item.nin || '-'],
            ['Téléphone', item.telephone || '-'],
            ['Île', item.country || '-'],
            ['Payé le', formatDate(item.paid_at)],
            ['Montant payé', formatKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}
