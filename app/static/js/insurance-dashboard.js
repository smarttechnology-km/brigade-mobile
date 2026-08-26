/**
 * Insurance Dashboard Script
 * Allows insurance accounts to view and update their assigned vehicles
 */

let vehiclesCache = [];
let currentEditVehicle = null;
let editLicenseNumbers = [];


async function editAddLicense() {
    const input = document.getElementById('edit-license-num-input');
    const val = (input.value || '').trim().toUpperCase();
    if (!val) return;
    if (editLicenseNumbers.includes(val)) { input.value = ''; return; }

    input.disabled = true;
    try {
        const r = await fetch(`/api/vehicles/check-driver-license?number=${encodeURIComponent(val)}`, { credentials: 'same-origin' });
        const data = await r.json();
        if (!data.exists) {
            alert(`Numéro de permis "${val}" introuvable dans la base de données.`);
            return;
        }
        editLicenseNumbers.push(val);
        input.value = '';
        renderEditLicenseTags();
    } catch(e) {
        alert('Erreur lors de la vérification du permis.');
    } finally {
        input.disabled = false;
        input.focus();
    }
}

function editRemoveLicense(num) {
    editLicenseNumbers = editLicenseNumbers.filter(n => n !== num);
    renderEditLicenseTags();
}

function renderEditLicenseTags() {
    const container = document.getElementById('edit-license-tags');
    if (!container) return;
    container.innerHTML = editLicenseNumbers.map(n => `
        <span class="badge bg-primary d-flex align-items-center gap-1" style="font-size:0.85rem;">
            <i class="fas fa-id-card me-1"></i>${n}
            <button type="button" class="btn-close btn-close-white ms-1" style="font-size:0.6rem;" onclick="editRemoveLicense('${n}')"></button>
        </span>`).join('');
}

document.addEventListener('DOMContentLoaded', function() {
    console.log('Insurance dashboard loaded');
    loadDashboardData();
    setupEventListeners();
});

function setupEventListeners() {
    const searchInput = document.getElementById('vehicle-search');
    const filterSelect = document.getElementById('insurance-filter');
    
    if (searchInput) {
        searchInput.addEventListener('input', filterVehicles);
    }
    if (filterSelect) {
        filterSelect.addEventListener('change', filterVehicles);
    }
}

function loadDashboardData() {
    console.log('Loading dashboard data...');

    Promise.all([
        loadCompanyInfo(),
        loadAssignedVehicles(),
        loadInsuranceAlerts()
    ])
    .then(() => {
        updateStatistics();
        renderVehiclesTable();
    })
    .catch(err => console.error('Error loading dashboard:', err));
}

function loadCompanyInfo() {
    return fetch('/api/vehicles/insurance-accounts/me', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to load company info');
        return r.json();
    })
    .then(data => {
        const companyName = document.getElementById('company-name');
        if (companyName) {
            companyName.textContent = data.insurance_name || 'Assurance';
        }
        window.currentInsuranceAccountId = data.id;
        window._hasMaquette = !!data.has_attestation_template;
    })
    .catch(err => {
        console.error('Error loading company info:', err);
        // Redirect to login if not authenticated as insurance account
        window.location.href = '/auth/login';
    });
}

function loadAssignedVehicles() {
    return fetch('/api/vehicles/insurance-vehicles', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to load vehicles');
        return r.json();
    })
    .then(data => {
        vehiclesCache = data.vehicles || [];
        console.log('Loaded ' + vehiclesCache.length + ' vehicles');
    })
    .catch(err => console.error('Error loading vehicles:', err));
}

function updateStatistics() {
    const today = new Date();
    const thirtyDaysFromNow = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000);
    
    let totalVehicles = 0;
    let expiringSoon = 0;
    let expiredCount = 0;
    let activeCount = 0;
    
    vehiclesCache.forEach(vehicle => {
        totalVehicles++;
        
        const insuranceExpiry = vehicle.insurance_expiry ? new Date(vehicle.insurance_expiry) : null;
        
        if (!insuranceExpiry) {
            // No expiry date set
        } else if (insuranceExpiry < today) {
            expiredCount++;
        } else if (insuranceExpiry < thirtyDaysFromNow) {
            expiringSoon++;
        } else {
            activeCount++;
        }
    });
    
    document.getElementById('total-vehicles').textContent = totalVehicles;
    document.getElementById('expiring-soon').textContent = expiringSoon;
    document.getElementById('expired-count').textContent = expiredCount;
    document.getElementById('active-count').textContent = activeCount;
}

function renderVehiclesTable() {
    const tbody = document.getElementById('vehicles-tbody');
    if (!tbody) return;
    
    if (vehiclesCache.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Aucun véhicule assigné</td></tr>';
        return;
    }
    
    const today = new Date();
    const thirtyDaysFromNow = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000);
    
    tbody.innerHTML = vehiclesCache.map(vehicle => {
        const insuranceExpiry = vehicle.insurance_expiry ? new Date(vehicle.insurance_expiry) : null;
        const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
        const registrationExpiry = vehicle.registration_expiry ? new Date(vehicle.registration_expiry) : null;
        const statusBadge = getVehicleStatusBadge(vehicle.status);
        
        let insuranceBadge = '-';
        if (insuranceExpiry) {
            if (insuranceExpiry < today) {
                insuranceBadge = `<span class="badge bg-danger">${formatDate(insuranceExpiry)}</span>`;
            } else if (insuranceExpiry < thirtyDaysFromNow) {
                insuranceBadge = `<span class="badge bg-warning">${formatDate(insuranceExpiry)}</span>`;
            } else {
                insuranceBadge = `<span class="badge bg-success">${formatDate(insuranceExpiry)}</span>`;
            }
        }
        
        // Determine if vehicle is inactive (status != active) or QR code expired
        let isInactive = false;
        try {
            const now = new Date();
            const qrExpiry = vehicle.qr_code_expiry ? new Date(vehicle.qr_code_expiry) : null;
            if (vehicle.status === 'inactive') isInactive = true;
            if (qrExpiry && qrExpiry < now) isInactive = true;
        } catch (e) {
            isInactive = false;
        }

        const editBtn = vehicle.has_unpaid_fines
            ? `<button class="btn btn-sm btn-outline-secondary" type="button" onclick="openEditDatesModal(${vehicle.id})" title="Amende non payée — permis modifiables">
                    <i class="fas fa-lock"></i>
                </button>`
            : (isInactive
                ? `<button class="btn btn-sm btn-outline-warning" onclick="openEditDatesModal(${vehicle.id})" title="Véhicule inactif - attention">
                        <i class="fas fa-exclamation-triangle"></i>
                    </button>`
                : `<button class="btn btn-sm btn-outline-primary" onclick="openEditDatesModal(${vehicle.id})" title="Modifier">
                        <i class="fas fa-edit"></i>
                    </button>`
              );

        const drivers = Array.isArray(vehicle.driver_license_numbers) ? vehicle.driver_license_numbers : [];
        const viewBtn = drivers.length === 0 ? '' :
            drivers.length === 1
                ? `<button class="btn btn-sm btn-outline-info ms-1" onclick="showLicensePreview('${drivers[0]}')" title="Voir le permis">
                        <i class="fas fa-eye"></i>
                    </button>`
                : `<div class="btn-group ms-1">
                        <button class="btn btn-sm btn-outline-info dropdown-toggle" data-bs-toggle="dropdown" title="Voir un permis">
                            <i class="fas fa-eye"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            ${drivers.map(n => `<li><button class="dropdown-item" onclick="showLicensePreview('${n}')"><i class="fas fa-id-card me-2"></i>${n}</button></li>`).join('')}
                        </ul>
                    </div>`;

        const attestBtn = window._hasMaquette
            ? `<button class="btn btn-sm btn-outline-success ms-1" onclick="window.open('/insurance-attestation/${vehicle.id}/print','_blank')" title="Imprimer l'attestation"><i class="fas fa-file-contract"></i></button>`
            : '';

        const actionButton = editBtn + viewBtn + attestBtn;

        return `
            <tr>
                <td><strong>${vehicle.license_plate}</strong></td>
                <td>${vehicle.owner_name || '-'}</td>
                <td>${vehicle.vehicle_type || '-'}</td>
                <td>${vehicle.owner_island || '-'}</td>
                <td>${vehicle.owner_phone || '-'}</td>
                <td>${vehicle.usage_type || '-'}</td>
                <td>${statusBadge}</td>
                <td>${insuranceBadge}</td>
                <td>
                    ${actionButton}
                </td>
            </tr>
        `;
    }).join('');
}

function getVehicleStatusBadge(status) {
    const normalized = String(status || '').toLowerCase();

    if (normalized === 'active') {
        return '<span class="badge bg-success">Actif</span>';
    }

    if (normalized === 'suspended') {
        return '<span class="badge bg-warning text-dark">Suspendu</span>';
    }

    if (normalized === 'inactive') {
        return '<span class="badge bg-danger">Inactif</span>';
    }

    return '<span class="badge bg-secondary">' + (status || 'Inconnu') + '</span>';
}

function filterVehicles() {
    const searchTerm = document.getElementById('vehicle-search').value.toLowerCase();
    const filterValue = document.getElementById('insurance-filter').value;
    const tbody = document.getElementById('vehicles-tbody');
    const rows = tbody.querySelectorAll('tr');
    
    const today = new Date();
    const thirtyDaysFromNow = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000);
    
    rows.forEach(row => {
        const licensePlate = row.cells[0]?.textContent.toLowerCase() || '';
        const owner = row.cells[1]?.textContent.toLowerCase() || '';
        const vehicleType = row.cells[2]?.textContent.toLowerCase() || '';
        
        let matchesSearch = !searchTerm || licensePlate.includes(searchTerm) || owner.includes(searchTerm) || vehicleType.includes(searchTerm);
        
        let matchesFilter = true;
        if (filterValue) {
            const insuranceBadge = row.cells[6];
            const badgeText = insuranceBadge?.textContent || '';
            
            if (filterValue === 'active') {
                matchesFilter = insuranceBadge?.querySelector('.bg-success') !== null;
            } else if (filterValue === 'expiring') {
                matchesFilter = insuranceBadge?.querySelector('.bg-warning') !== null;
            } else if (filterValue === 'expired') {
                matchesFilter = insuranceBadge?.querySelector('.bg-danger') !== null;
            }
        }
        
        row.style.display = (matchesSearch && matchesFilter) ? '' : 'none';
    });
}

function openEditDatesModal(vehicleId) {
    const vehicle = vehiclesCache.find(v => v.id === vehicleId);
    if (!vehicle) return;

    currentEditVehicle = vehicle;

    document.getElementById('edit-vehicle-id').value = vehicle.id;
    document.getElementById('edit-license-plate').value = vehicle.license_plate;
    document.getElementById('edit-owner-name').value = vehicle.owner_name || '';
    document.getElementById('edit-vehicle-type').value = vehicle.vehicle_type || '';
    document.getElementById('edit-owner-island').value = vehicle.owner_island || '';
    document.getElementById('edit-owner-phone').value = vehicle.owner_phone || '';
    document.getElementById('edit-usage-type').value = vehicle.usage_type || '';
    document.getElementById('edit-insurance-expiry').value = vehicle.insurance_expiry ? vehicle.insurance_expiry.split('T')[0] : '';

    const wzRow     = document.getElementById('edit-work-zone-row');
    const wzDisplay = document.getElementById('edit-work-zone-display');
    const hasZone   = !!(vehicle.work_zone && vehicle.work_zone.trim());
    if (wzRow && wzDisplay) {
        if (hasZone) {
            wzDisplay.value = vehicle.work_zone;
            wzRow.classList.remove('d-none');
        } else {
            wzRow.classList.add('d-none');
            wzDisplay.value = '';
        }
    }

    const insuranceInput = document.getElementById('edit-insurance-expiry');
    const saveBtn        = document.getElementById('save-dates-btn');
    const alertEl        = document.getElementById('edit-dates-alert');
    const alertText      = document.getElementById('edit-dates-alert-text');

    let blockReason = null;
    const now = new Date();
    const qrExpiry        = vehicle.qr_code_expiry  ? new Date(vehicle.qr_code_expiry)  : null;
    const insuranceExpiry = vehicle.insurance_expiry ? new Date(vehicle.insurance_expiry) : null;

    if (vehicle.has_unpaid_fines) {
        blockReason = vehicle.block_reason || 'Ce véhicule a une amende non payée. La date d\'assurance ne peut pas être modifiée.';
    } else if (vehicle.status === 'inactive') {
        blockReason = 'Le véhicule est inactif.';
    } else if (qrExpiry && qrExpiry < now) {
        blockReason = 'QR code expiré le ' + qrExpiry.toLocaleDateString('fr-FR') + '.';
    } else if (insuranceExpiry && insuranceExpiry > now) {
        blockReason = "L'assurance est encore active jusqu'au "
            + insuranceExpiry.toLocaleDateString('fr-FR', {day:'2-digit', month:'2-digit', year:'numeric'})
            + '. La date ne peut être modifiée qu\'après expiration.';
    }

    if (blockReason) {
        if (insuranceInput) insuranceInput.disabled = true;
        if (alertEl && alertText) { alertText.textContent = blockReason; alertEl.style.display = ''; }
    } else {
        if (insuranceInput) insuranceInput.disabled = false;
        if (alertEl) alertEl.style.display = 'none';
    }

    const todayStr = now.toLocaleDateString('en-CA');
    const insuranceActive = vehicle.insurance_expiry && vehicle.insurance_expiry.split('T')[0] >= todayStr;
    const durationBtns = document.getElementById('edit-duration-btns');
    if (durationBtns) durationBtns.style.display = insuranceActive ? 'none' : 'flex';

    // Save button always enabled — license numbers can always be updated
    if (saveBtn) { saveBtn.disabled = false; saveBtn.title = ''; }

    // Populate existing driver license numbers
    editLicenseNumbers = Array.isArray(vehicle.driver_license_numbers) ? [...vehicle.driver_license_numbers] : [];
    renderEditLicenseTags();
    const licInput = document.getElementById('edit-license-num-input');
    if (licInput) {
        licInput.value = '';
        licInput.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); editAddLicense(); } };
    }

    const modal = new bootstrap.Modal(document.getElementById('editDatesModal'));
    modal.show();
}

function showFineDetails(vehicleId) {
    const vehicle = vehiclesCache.find(v => v.id === vehicleId);
    if (!vehicle) return;

    const fine = vehicle.unpaid_fine;
    if (!fine) {
        const modal = document.getElementById('fineDetailsModal');
        const licensePlate = document.getElementById('fine-modal-license-plate');
        const reason = document.getElementById('fine-modal-reason');
        const fineAmount = document.getElementById('fine-modal-amount');
        const fineDate = document.getElementById('fine-modal-date');
        const fineReference = document.getElementById('fine-modal-reference');
        const message = document.getElementById('fine-modal-message');
        if (modal && message && licensePlate && reason && fineAmount && fineDate && fineReference) {
            licensePlate.value = vehicle.license_plate || '-';
            reason.value = '-';
            fineAmount.value = '-';
            fineDate.value = '-';
            fineReference.value = '-';
            message.textContent = vehicle.block_reason || 'Ce véhicule est bloqué.';
            new bootstrap.Modal(modal).show();
            return;
        }
        alert(vehicle.block_reason || 'Ce véhicule est bloqué.');
        return;
    }

    const details = `Amende #${fine.id} - ${fine.reason || 'Type inconnu'}${fine.amount !== null && fine.amount !== undefined ? ` (${Math.round(Number(fine.amount))} KMF)` : ''}. Vous devez d'abord la régler avant d'ajouter ou de modifier l'assurance.`;
    const modal = document.getElementById('fineDetailsModal');
    const licensePlate = document.getElementById('fine-modal-license-plate');
    const reason = document.getElementById('fine-modal-reason');
    const fineAmount = document.getElementById('fine-modal-amount');
    const fineDate = document.getElementById('fine-modal-date');
    const fineReference = document.getElementById('fine-modal-reference');
    const fineMessage = document.getElementById('fine-modal-message');

    if (modal && licensePlate && reason && fineAmount && fineDate && fineReference && fineMessage) {
        licensePlate.value = vehicle.license_plate || '-';
        reason.value = fine.reason || '-';
        fineAmount.value = fine.amount !== null && fine.amount !== undefined ? `${Math.round(Number(fine.amount))} KMF` : '-';
        fineDate.value = fine.issued_at_str || '-';
        fineReference.value = fine.receipt_number || '-';
        fineMessage.textContent = details;
        new bootstrap.Modal(modal).show();
        return;
    }

    alert(details);
}

function saveVehicleDates() {
    const vehicleId = document.getElementById('edit-vehicle-id').value;
    const insuranceExpiry = document.getElementById('edit-insurance-expiry').value;

    if (editLicenseNumbers.length === 0) {
        alert('Veuillez ajouter au moins un numéro de permis conducteur.');
        document.getElementById('edit-license-num-input')?.focus();
        return;
    }

    if (!insuranceExpiry) {
        alert('Veuillez sélectionner une date d\'expiration pour l\'assurance');
        return;
    }

    const expiryInput = document.getElementById('edit-insurance-expiry');
    const requests = [];

    if (expiryInput && !expiryInput.disabled && insuranceExpiry) {
        requests.push(fetch(`/api/vehicles/${vehicleId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ insurance_expiry: insuranceExpiry })
        }).then(r => { if (!r.ok) return r.json().then(e => { throw e; }); return r.json(); }));
    }

    requests.push(fetch(`/api/vehicles/${vehicleId}/assignment-licenses`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ driver_license_numbers: editLicenseNumbers })
    }).then(r => { if (!r.ok) return r.json().then(e => { throw e; }); return r.json(); }));

    Promise.all(requests)
    .then(() => {
        bootstrap.Modal.getInstance(document.getElementById('editDatesModal')).hide();
        loadAssignedVehicles().then(() => {
            updateStatistics();
            renderVehiclesTable();
        });
    })
    .catch(err => {
        console.error('Error updating vehicle:', err);
        alert(err.error || 'Erreur lors de la mise à jour');
    });
}

async function showLicensePreview(licenseNumber) {
    const body = document.getElementById('license-preview-body');
    if (!body) return;
    body.innerHTML = '<div class="text-center py-5 text-white"><i class="fas fa-spinner fa-spin fa-2x"></i></div>';
    new bootstrap.Modal(document.getElementById('licensePreviewModal')).show();

    try {
        const r = await fetch(`/api/vehicles/driver-license-preview?number=${encodeURIComponent(licenseNumber)}`, { credentials: 'same-origin' });
        const d = await r.json();
        if (!r.ok) { body.innerHTML = `<div class="alert alert-danger m-3">${d.error || 'Erreur'}</div>`; return; }

        const isPro = d.is_pro;
        const cardClass = isPro ? 'lp-card lp-pro' : 'lp-card';

        const catsHtml = (d.categories || []).map(code => {
            const det = d.category_details?.[code];
            const iconMap = { A:'fa-motorcycle', A1:'fa-motorcycle', A2:'fa-motorcycle', B:'fa-car', C:'fa-truck', D:'fa-bus', E:'fa-caravan', F:'fa-wheelchair' };
            const icon = iconMap[code] || 'fa-car';
            const exp = det?.expiration || '—';
            return `<div class="lp-cat-chip"><i class="fas ${icon} lp-cat-icon"></i><span class="lp-cat-exp">${exp}</span></div>`;
        }).join('');

        body.innerHTML = `
        <div class="${cardClass}">
            <div class="lp-header">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span class="lp-flag">🇰🇲</span>
                    <div>
                        <div class="lp-title">Union des Comores</div>
                        <div class="lp-sub">Permis de Conduire</div>
                    </div>
                </div>
                <div class="lp-arabic" dir="rtl">جمهورية القمر المتحدة<br>رخصة قيادة</div>
            </div>
            <div class="lp-body">
                <div class="lp-photo-row">
                    <div>
                        <div class="lp-photo">
                            ${d.photo_url
                                ? `<img src="${d.photo_url}" alt="">`
                                : `<span class="lp-no-photo">👤</span>`}
                        </div>
                        <div class="lp-photo-num">${d.license_number}</div>
                    </div>
                    <div class="lp-identity">
                        <div class="lp-lbl">Nom</div>
                        <div class="lp-name">${d.holder_firstname || '—'}</div>
                        <div class="lp-lbl" style="margin-top:4px;">Prénom</div>
                        <div class="lp-name">${d.holder_name || '—'}</div>
                        <div class="lp-divider"></div>
                        <div class="lp-field-lbl">Centre d'immatriculation</div>
                        <div class="lp-field-val">${d.centre_immatriculation || '—'}</div>
                        ${isPro ? `<div class="lp-pro-badge">TYPE : PROFESSIONNEL</div>` : ''}
                    </div>
                </div>
                <div class="lp-validity">
                    <div class="lp-fv-item"><span class="lp-fv-lbl">Délivré le</span><span class="lp-fv-val">${d.issue_date || '—'}</span></div>
                    <span class="lp-fv-sep">→</span>
                    <div class="lp-fv-item"><span class="lp-fv-lbl">Expire le</span><span class="lp-fv-val">${d.expiry_date || '—'}</span></div>
                </div>
                ${catsHtml ? `<div class="lp-cats">${catsHtml}</div>` : ''}
            </div>
            <div class="lp-footer">
                <div class="lp-footer-text">Direction Générale des Routes et Transports Routiers</div>
            </div>
        </div>`;
    } catch(e) {
        body.innerHTML = '<div class="alert alert-danger m-3">Erreur lors du chargement.</div>';
    }
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = typeof dateString === 'string' ? new Date(dateString) : dateString;
    return new Intl.DateTimeFormat('fr-FR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}

// ── Insurance Alerts ────────────────────────────────────────────────

let alertsCache = [];

function loadInsuranceAlerts() {
    return fetch('/api/vehicles/insurance-alerts', { credentials: 'same-origin' })
        .then(r => { if (!r.ok) throw new Error('alerts fetch failed'); return r.json(); })
        .then(data => {
            alertsCache = data.alerts || [];
            renderAlertsTable();
        })
        .catch(err => {
            console.error('Error loading insurance alerts:', err);
            alertsCache = [];
            renderAlertsTable();
        });
}

function renderAlertsTable() {
    const section = document.getElementById('alerts-section');
    const tbody = document.getElementById('alerts-tbody');
    const badge = document.getElementById('alerts-count-badge');

    if (!section || !tbody) return;

    if (alertsCache.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    if (badge) badge.textContent = alertsCache.length;

    const TYPE_ICONS = {
        'accident': '<i class="fas fa-car-crash text-danger me-1"></i>',
        'recherche_vehicule': '<i class="fas fa-search text-warning me-1"></i>',
        'autre': '<i class="fas fa-bell text-secondary me-1"></i>',
    };

    tbody.innerHTML = alertsCache.map(alert => {
        const icon = TYPE_ICONS[alert.alert_type] || '<i class="fas fa-exclamation-circle text-secondary me-1"></i>';
        const statusBadge = alert.is_expired
            ? '<span class="badge bg-secondary">Expirée</span>'
            : '<span class="badge bg-danger">Active</span>';
        const plates = (alert.vehicles || []).map(v =>
            `<span class="badge bg-light text-dark border">${v.license_plate}</span>`
        ).join(' ');
        const hasPhotos = alert.photos && alert.photos.length > 0;
        return `<tr>
            <td><small>${alert.starts_at_str || '—'}</small></td>
            <td>${icon}<small>${alert.alert_type_label}</small></td>
            <td><span class="fw-semibold">${alert.title}</span></td>
            <td>${plates || '—'}</td>
            <td><small>${alert.island}</small></td>
            <td>${statusBadge}</td>
            <td>
                <button class="btn btn-sm btn-outline-danger" onclick="openAlertDetail(${alert.id})" title="Voir détails & photos">
                    <i class="fas fa-eye me-1"></i>${hasPhotos ? `Photos (${alert.photos.length})` : 'Détails'}
                </button>
            </td>
        </tr>`;
    }).join('');
}

function openAlertDetail(alertId) {
    const alert = alertsCache.find(a => a.id === alertId);
    if (!alert) return;

    document.getElementById('alert-modal-title').textContent = alert.title;
    document.getElementById('alert-modal-type').textContent = alert.alert_type_label;
    document.getElementById('alert-modal-island').textContent = alert.island;
    document.getElementById('alert-modal-date').textContent = alert.starts_at_str || '—';

    const descRow = document.getElementById('alert-modal-desc-row');
    const descEl = document.getElementById('alert-modal-desc');
    if (alert.description) {
        descEl.innerHTML = alert.description;
        descRow.style.display = '';
    } else {
        descRow.style.display = 'none';
    }

    const vehiclesEl = document.getElementById('alert-modal-vehicles');
    vehiclesEl.innerHTML = (alert.vehicles || []).map(v =>
        `<span class="badge bg-secondary fs-6 py-2 px-3">${v.license_plate}${v.owner_name ? ' — ' + v.owner_name : ''}</span>`
    ).join('') || '<span class="text-muted">Aucun véhicule</span>';

    const photosRow = document.getElementById('alert-modal-photos-row');
    const photosEl = document.getElementById('alert-modal-photos');
    if (alert.photos && alert.photos.length > 0) {
        photosEl.innerHTML = alert.photos.map(p =>
            `<a href="${p.photo_url}" target="_blank">
                <img src="${p.photo_url}" style="height:120px;width:120px;object-fit:cover;border-radius:6px;border:2px solid #dee2e6;" />
             </a>`
        ).join('');
        photosRow.style.display = '';
    } else {
        photosRow.style.display = 'none';
    }

    const modal = new bootstrap.Modal(document.getElementById('alertDetailModal'));
    modal.show();
}
