/* ── Archive paiements DGRTR (Cartes grises / Visite Technique / Licence Pro / Dossiers Permis) ── */
let dsDataCache = { cg_archive: [], vt_archive: [], licence_pro_archive: [], dossier_permis_archive: [], totals: {} };

function dsApplyPeriod(period) {
    // Période gérée uniquement via les query params au fetch — pas de champs date visibles ici.
}

document.addEventListener('DOMContentLoaded', function () {
    var periodSelect = document.getElementById('ds-period');
    var refreshBtn = document.getElementById('ds-refresh-btn');
    var exportBtn = document.getElementById('ds-export-btn');
    var searchInput = document.getElementById('ds-search');
    var islandSelect = document.getElementById('ds-island');
    var payerSelect = document.getElementById('ds-payer');
    var dateFrom = document.getElementById('ds-date-from');
    var dateTo = document.getElementById('ds-date-to');

    if (periodSelect) periodSelect.addEventListener('change', function () {
        var isCustom = periodSelect.value === 'custom';
        document.getElementById('ds-date-from-wrap').classList.toggle('d-none', !isCustom);
        document.getElementById('ds-date-to-wrap').classList.toggle('d-none', !isCustom);
        if (!isCustom) dsLoadData();
    });
    if (dateFrom) dateFrom.addEventListener('change', dsLoadData);
    if (dateTo) dateTo.addEventListener('change', dsLoadData);
    if (refreshBtn) refreshBtn.addEventListener('click', dsLoadData);
    if (exportBtn) exportBtn.addEventListener('click', dsExportCsv);
    if (searchInput) searchInput.addEventListener('input', dsRenderTables);
    if (islandSelect) islandSelect.addEventListener('change', dsRenderTables);
    if (payerSelect) payerSelect.addEventListener('change', dsRenderTables);

    dsLoadData();
});

function dsLoadData() {
    var period = (document.getElementById('ds-period') || {}).value || '30';
    var query = new URLSearchParams();
    if (period === 'custom') {
        var fromVal = (document.getElementById('ds-date-from') || {}).value;
        var toVal = (document.getElementById('ds-date-to') || {}).value;
        if (!fromVal || !toVal) return; // attendre que les deux dates soient renseignées
        query.set('start_date', fromVal);
        query.set('end_date', toVal);
    } else if (period === 'all') {
        query.set('all', 'true');
    } else if (period === 'today') {
        var today = new Date().toLocaleDateString('en-CA');
        query.set('start_date', today);
        query.set('end_date', today);
    } else if (period === 'month') {
        var now = new Date();
        var start = new Date(now.getFullYear(), now.getMonth(), 1);
        query.set('start_date', start.toLocaleDateString('en-CA'));
        query.set('end_date', now.toLocaleDateString('en-CA'));
    } else if (period === 'year') {
        var now2 = new Date();
        var start2 = new Date(now2.getFullYear(), 0, 1);
        query.set('start_date', start2.toLocaleDateString('en-CA'));
        query.set('end_date', now2.toLocaleDateString('en-CA'));
    } else {
        var now3 = new Date();
        var start3 = new Date(now3); start3.setDate(start3.getDate() - parseInt(period, 10));
        query.set('start_date', start3.toLocaleDateString('en-CA'));
        query.set('end_date', now3.toLocaleDateString('en-CA'));
    }

    var cgBody = document.getElementById('ds-cg-tbody');
    var vtBody = document.getElementById('ds-vt-tbody');
    var lpBody = document.getElementById('ds-lp-tbody');
    var dpBody = document.getElementById('ds-dp-tbody');
    if (cgBody) cgBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (vtBody) vtBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (lpBody) lpBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Chargement...</td></tr>';
    if (dpBody) dpBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Chargement...</td></tr>';

    fetch('/api/vehicles/mobile-money-archive?' + query.toString(), { credentials: 'same-origin' })
        .then(function (r) {
            if (!r.ok) throw new Error('Erreur de chargement');
            return r.json();
        })
        .then(function (data) {
            dsDataCache = data || { cg_archive: [], vt_archive: [], licence_pro_archive: [], dossier_permis_archive: [], totals: {} };
            dsPopulatePayerOptions();
            dsRenderTables();
        })
        .catch(function (err) {
            console.error('DGRTR stats load error:', err);
            if (cgBody) cgBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (vtBody) vtBody.innerHTML = '<tr><td colspan="10" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (lpBody) lpBody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
            if (dpBody) dpBody.innerHTML = '<tr><td colspan="10" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
        });
}

var dsFilteredCgs = [], dsFilteredVts = [], dsFilteredLicencePros = [], dsFilteredDossierPermis = [];

function dsMatchIsland(islandValue, selected) {
    if (!selected) return true;
    return (islandValue || '') === selected;
}

function dsMatchPayer(paidBy, selected) {
    if (!selected) return true;
    return (paidBy || '') === selected;
}

function dsPopulatePayerOptions() {
    var select = document.getElementById('ds-payer');
    if (!select) return;
    var previous = select.value;
    var all = [].concat(
        dsDataCache.cg_archive || [],
        dsDataCache.vt_archive || [],
        dsDataCache.licence_pro_archive || [],
        dsDataCache.dossier_permis_archive || []
    );
    var names = Array.from(new Set(all.map(function (item) { return item.paid_by; })
        .filter(function (p) { return p && p !== '-'; })
    )).sort(function (a, b) { return a.localeCompare(b); });

    select.innerHTML = '<option value="">Tous les agents</option>' +
        names.map(function (name) { return '<option value="' + dsEsc(name) + '">' + dsEsc(name) + '</option>'; }).join('');
    if (names.indexOf(previous) !== -1) select.value = previous;
}

function dsRenderTables() {
    var search = (document.getElementById('ds-search').value || '').toLowerCase().trim();
    var island = (document.getElementById('ds-island') || {}).value || '';
    var payer = (document.getElementById('ds-payer') || {}).value || '';
    var cgBody = document.getElementById('ds-cg-tbody');
    var vtBody = document.getElementById('ds-vt-tbody');
    var lpBody = document.getElementById('ds-lp-tbody');
    var dpBody = document.getElementById('ds-dp-tbody');

    var cgs = (dsDataCache.cg_archive || []).filter(function (item) {
        if (!dsMatchIsland(item.owner_island, island)) return false;
        if (!dsMatchPayer(item.paid_by, payer)) return false;
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.owner_island, item.receipt_number, item.paid_by]
            .some(function (f) { return String(f || '').toLowerCase().includes(search); });
    });
    var vts = (dsDataCache.vt_archive || []).filter(function (item) {
        if (!dsMatchIsland(item.owner_island, island)) return false;
        if (!dsMatchPayer(item.paid_by, payer)) return false;
        if (!search) return true;
        return [item.license_plate, item.owner_name, item.owner_island, item.paid_by]
            .some(function (f) { return String(f || '').toLowerCase().includes(search); });
    });
    var licencePros = (dsDataCache.licence_pro_archive || []).filter(function (item) {
        if (!dsMatchIsland(item.holder_island, island)) return false;
        if (!dsMatchPayer(item.paid_by, payer)) return false;
        if (!search) return true;
        return [item.lp_number, item.holder_name, item.activite_label, item.receipt_number, item.paid_by]
            .some(function (f) { return String(f || '').toLowerCase().includes(search); });
    });
    var dossierPermis = (dsDataCache.dossier_permis_archive || []).filter(function (item) {
        if (!dsMatchIsland(item.country, island)) return false;
        if (!dsMatchPayer(item.paid_by, payer)) return false;
        if (!search) return true;
        return [item.dossier_number, item.nin, item.telephone, item.country, item.receipt_number, item.paid_by]
            .some(function (f) { return String(f || '').toLowerCase().includes(search); });
    });

    dsFilteredCgs = cgs;
    dsFilteredVts = vts;
    dsFilteredLicencePros = licencePros;
    dsFilteredDossierPermis = dossierPermis;
    dsUpdateSummaryCards();

    if (cgBody) {
        if (!cgs.length) {
            cgBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucune carte grise trouvée</td></tr>';
        } else {
            cgBody.innerHTML = cgs.map(function (item, idx) {
                return '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><strong>' + dsEsc(item.license_plate || '-') + '</strong></td>' +
                    '<td>' + dsEsc(item.owner_name || '-') + '</td>' +
                    '<td>' + dsEsc(item.owner_island || '-') + '</td>' +
                    '<td>' + dsEsc(item.receipt_number || '-') + '</td>' +
                    '<td>' + dsDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold text-primary">' + dsKMF(item.amount) + '</td>' +
                    '<td>' + dsEsc(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="dsPrintCgReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
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
                    '<td><strong>' + dsEsc(item.license_plate || '-') + '</strong></td>' +
                    '<td>' + dsEsc(item.owner_name || '-') + '</td>' +
                    '<td>' + dsEsc(item.owner_island || '-') + '</td>' +
                    '<td>' + dsEsc(item.appointment_date || '-') + '</td>' +
                    '<td>' + dsEsc(item.appointment_time || '-') + '</td>' +
                    '<td class="text-end fw-semibold text-info">' + dsKMF(item.amount) + '</td>' +
                    '<td>' + channelBadge + '</td>' +
                    '<td>' + dsEsc(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="dsPrintVtReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
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
                    '<td><strong>' + dsEsc(item.lp_number || '-') + '</strong></td>' +
                    '<td>' + dsEsc(item.holder_name || '-') + '</td>' +
                    '<td>' + dsEsc(item.activite_label || '-') + '</td>' +
                    '<td>' + dsEsc(item.receipt_number || '-') + '</td>' +
                    '<td>' + dsDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold">' + dsKMF(item.amount) + '</td>' +
                    '<td>' + dsEsc(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="dsPrintLicenceProReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
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
                    '<td><strong>' + dsEsc(item.dossier_number || '-') + '</strong></td>' +
                    '<td>' + dsEsc(item.nin || '-') + '</td>' +
                    '<td>' + dsEsc(item.telephone || '-') + '</td>' +
                    '<td>' + dsEsc(item.country || '-') + '</td>' +
                    '<td>' + dsEsc(item.receipt_number || '-') + '</td>' +
                    '<td>' + dsDate(item.paid_at) + '</td>' +
                    '<td class="text-end fw-semibold">' + dsKMF(item.amount) + '</td>' +
                    '<td>' + dsEsc(item.paid_by || '-') + '</td>' +
                    '<td><button class="btn btn-sm btn-outline-secondary" onclick="dsPrintDossierPermisReceipt(' + item.id + ')" title="Imprimer le reçu"><i class="fas fa-print"></i></button></td>' +
                    '</tr>';
            }).join('');
        }
    }
}

function dsSum(items) {
    return items.reduce(function (sum, item) { return sum + (parseFloat(item.amount) || 0); }, 0);
}

function dsUpdateSummaryCards() {
    // Recalculées à partir des données filtrées (recherche + île) pour que les
    // cartes restent cohérentes avec ce qui est affiché dans les tableaux.
    document.getElementById('ds-cg-count').textContent = dsFilteredCgs.length;
    document.getElementById('ds-cg-total').textContent = dsKMF(dsSum(dsFilteredCgs));
    document.getElementById('ds-vt-count').textContent = dsFilteredVts.length;
    document.getElementById('ds-vt-total').textContent = dsKMF(dsSum(dsFilteredVts));
    document.getElementById('ds-lp-count').textContent = dsFilteredLicencePros.length;
    document.getElementById('ds-lp-total').textContent = dsKMF(dsSum(dsFilteredLicencePros));
    document.getElementById('ds-dp-count').textContent = dsFilteredDossierPermis.length;
    document.getElementById('ds-dp-total').textContent = dsKMF(dsSum(dsFilteredDossierPermis));
}

function dsExportCsv() {
    var activePane = document.querySelector('#dsTabsContent .tab-pane.active');
    if (!activePane) return;

    var config = {
        'ds-cg-pane': {
            filename: 'cartes_grises',
            headers: ['Immatriculation', 'Propriétaire', 'Île', 'Reçu', 'Date de paiement', 'Montant (KMF)', 'Payé par'],
            rows: dsFilteredCgs.map(function (item) {
                return [item.license_plate, item.owner_name, item.owner_island, item.receipt_number, dsDate(item.paid_at), item.amount, item.paid_by];
            }),
        },
        'ds-vt-pane': {
            filename: 'visites_techniques',
            headers: ['Immatriculation', 'Propriétaire', 'Île', 'Date RDV', 'Heure', 'Montant (KMF)', 'Canal', 'Payé par'],
            rows: dsFilteredVts.map(function (item) {
                return [item.license_plate, item.owner_name, item.owner_island, item.appointment_date, item.appointment_time, item.amount,
                    item.channel === 'app_citoyen' ? 'App Citoyen' : 'Agent Huri Money', item.paid_by];
            }),
        },
        'ds-lp-pane': {
            filename: 'licences_pro',
            headers: ['N° LP', 'Titulaire', 'Activité', 'Reçu', 'Date de paiement', 'Montant (KMF)', 'Payé par'],
            rows: dsFilteredLicencePros.map(function (item) {
                return [item.lp_number, item.holder_name, item.activite_label, item.receipt_number, dsDate(item.paid_at), item.amount, item.paid_by];
            }),
        },
        'ds-dp-pane': {
            filename: 'dossiers_permis',
            headers: ['N° Dossier', 'NIN', 'Téléphone', 'Île', 'Reçu', 'Date de paiement', 'Montant (KMF)', 'Payé par'],
            rows: dsFilteredDossierPermis.map(function (item) {
                return [item.dossier_number, item.nin, item.telephone, item.country, item.receipt_number, dsDate(item.paid_at), item.amount, item.paid_by];
            }),
        },
    };

    var cfg = config[activePane.id];
    if (!cfg) return;
    if (!cfg.rows.length) { alert('Aucune donnée à exporter pour cet onglet.'); return; }

    var csvEscape = function (value) {
        var str = String(value === null || value === undefined ? '' : value);
        if (/[",;\n]/.test(str)) return '"' + str.replace(/"/g, '""') + '"';
        return str;
    };
    var lines = [cfg.headers.map(csvEscape).join(';')]
        .concat(cfg.rows.map(function (row) { return row.map(csvEscape).join(';'); }));
    var csvContent = '﻿' + lines.join('\r\n'); // BOM pour une ouverture correcte dans Excel

    var blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = cfg.filename + '_' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function dsKMF(amount) {
    if (amount === null || amount === undefined || amount === '') return '0 KMF';
    var num = parseFloat(amount) || 0;
    return num.toLocaleString('fr-KM') + ' KMF';
}

function dsDate(value) {
    if (!value) return '-';
    try { return new Date(value).toLocaleDateString('fr-FR'); } catch (e) { return '-'; }
}

function dsEsc(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function dsOpenReceipt(opts) {
    document.getElementById('ds-receipt-title').textContent = opts.title || 'REÇU DE PAIEMENT';
    document.getElementById('ds-receipt-number').textContent = opts.receiptNumber || '-';
    document.getElementById('ds-receipt-rows').innerHTML = (opts.rows || []).map(function (row, idx, arr) {
        var isLast = idx === arr.length - 1;
        return '<tr' + (isLast ? ' class="receipt-total-row"' : '') + '>' +
            '<td>' + dsEsc(row[0]) + '</td><td>' + dsEsc(row[1]) + '</td></tr>';
    }).join('');
    document.getElementById('ds-receipt-agent').textContent = opts.agent || '-';
    new bootstrap.Modal(document.getElementById('dsReceiptModal')).show();
}

function dsPrintCgReceipt(id) {
    var item = (dsDataCache.cg_archive || []).find(function (c) { return c.id === id; });
    if (!item) return;
    dsOpenReceipt({
        title: 'REÇU DE PAIEMENT — CARTE GRISE',
        receiptNumber: item.receipt_number,
        rows: [
            ['Immatriculation', item.license_plate || '-'],
            ['Propriétaire', item.owner_name || '-'],
            ['Île', item.owner_island || '-'],
            ['Payé le', dsDate(item.paid_at)],
            ['Montant payé', dsKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function dsPrintVtReceipt(id) {
    var item = (dsDataCache.vt_archive || []).find(function (v) { return v.id === id; });
    if (!item) return;
    dsOpenReceipt({
        title: 'REÇU DE PAIEMENT — VISITE TECHNIQUE',
        receiptNumber: item.receipt_number || ('VT-' + id + '-' + Math.floor(new Date(item.paid_at).getTime() / 1000)),
        rows: [
            ['Immatriculation', item.license_plate || '-'],
            ['Propriétaire', item.owner_name || '-'],
            ['Île', item.owner_island || '-'],
            ['Payé le', dsDate(item.paid_at)],
            ['Montant payé', dsKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function dsPrintLicenceProReceipt(id) {
    var item = (dsDataCache.licence_pro_archive || []).find(function (l) { return l.id === id; });
    if (!item) return;
    dsOpenReceipt({
        title: 'REÇU DE PAIEMENT — LICENCE PROFESSIONNELLE',
        receiptNumber: item.receipt_number,
        rows: [
            ['N° LP', item.lp_number || '-'],
            ['Titulaire', item.holder_name || '-'],
            ['Activité', item.activite_label || '-'],
            ['Payé le', dsDate(item.paid_at)],
            ['Montant payé', dsKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}

function dsPrintDossierPermisReceipt(id) {
    var item = (dsDataCache.dossier_permis_archive || []).find(function (d) { return d.id === id; });
    if (!item) return;
    dsOpenReceipt({
        title: 'REÇU DE PAIEMENT — FRAIS DE DOSSIER',
        receiptNumber: item.receipt_number,
        rows: [
            ['NIN', item.nin || '-'],
            ['Téléphone', item.telephone || '-'],
            ['Île', item.country || '-'],
            ['Payé le', dsDate(item.paid_at)],
            ['Montant payé', dsKMF(item.amount)],
        ],
        agent: item.paid_by,
    });
}
