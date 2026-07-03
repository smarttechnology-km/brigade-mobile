/**
 * Vignette Settings Script
 * Manages vignette rates and penalty rates
 */

let vignetteRatesCache = [];
let penaltyRatesCache = [];
let vehicleOptionsCache = {};
let currentEditVignetteRateId = null;
let currentEditPenaltyRateId = null;

document.addEventListener('DOMContentLoaded', function() {
    console.log('Vignette settings page loaded');
    loadVehicleOptions();
    loadVignetteRates();
    loadPenaltyRates();
    loadVignetteSettings();
});

// ============= VEHICLE OPTIONS =============

function loadVehicleOptions() {
    // Only need to load fuel types now
    const fuelTypeSelect = document.getElementById('vignette-fuel-type');
    if (fuelTypeSelect) {
        // Fuel types are already in the HTML, no need to load
        console.log('Fuel types already populated in HTML');
    }
}

// ============= VIGNETTE RATES =============

function loadVignetteRates() {
    fetch('/api/vehicles/vignette-rates', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to load vignette rates');
        return r.json();
    })
    .then(data => {
        vignetteRatesCache = data.rates || [];
        console.log('Loaded ' + vignetteRatesCache.length + ' vignette rates');
        renderVignetteRatesTable();
    })
    .catch(err => {
        console.error('Error loading vignette rates:', err);
        alert('Erreur lors du chargement des tarifs: ' + err.message);
    });
}

function renderVignetteRatesTable() {
    const tbody = document.getElementById('vignette-rates-tbody');
    if (!tbody) return;

    if (vignetteRatesCache.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Aucun tarif défini</td></tr>';
        return;
    }

    tbody.innerHTML = vignetteRatesCache.map(rate => {
        const totalPrice = Number(rate.total_price_kmf ?? (Number(rate.price_kmf || 0) + Number(rate.annual_ds ?? 1000)));
        return `
            <tr>
                <td>${rate.fiscal_class || '-'}</td>
                <td>${rate.cv_class || '-'}</td>
                <td>${rate.fuel_type || '-'}</td>
                <td class="text-center">${rate.vehicle_age_min !== null ? rate.vehicle_age_min : '0'}</td>
                <td class="text-center">${rate.vehicle_age_max !== null ? rate.vehicle_age_max : '∞'}</td>
                <td class="fw-semibold">${totalPrice.toLocaleString('fr-KM')} KMF</td>
                <td>${rate.description || '-'}</td>
                <td><span class="badge bg-success">Actif</span></td>
                <td>
                    <button class="btn btn-sm btn-warning" onclick="editVignetteRate(${rate.id})">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-sm btn-danger ms-1" onclick="deleteVignetteRate(${rate.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function openVignetteRateModal() {
    currentEditVignetteRateId = null;
    document.getElementById('vignette-rate-id').value = '';
    document.getElementById('vignette-fiscal-class').value = '';
    document.getElementById('vignette-cv-class').value = '';
    document.getElementById('vignette-fuel-type').value = '';
    document.getElementById('vignette-price').value = '';
        document.getElementById('vignette-annual-ds').value = '1000';
    document.getElementById('vignette-age-min').value = '0';
    document.getElementById('vignette-age-max').value = '';
    document.getElementById('vignette-description').value = '';
    document.getElementById('vignette-rate-modal-title').textContent = 'Ajouter un Tarif';
    
    const modal = new bootstrap.Modal(document.getElementById('vignetteRateModal'));
    modal.show();
}

function editVignetteRate(rateId) {
    const rate = vignetteRatesCache.find(r => r.id === rateId);
    if (!rate) return;
    
    currentEditVignetteRateId = rateId;
    document.getElementById('vignette-rate-id').value = rateId;
    document.getElementById('vignette-fiscal-class').value = rate.fiscal_class || '';
    document.getElementById('vignette-cv-class').value = rate.cv_class || '';
    document.getElementById('vignette-fuel-type').value = rate.fuel_type || '';
    document.getElementById('vignette-price').value = rate.price_kmf;
        document.getElementById('vignette-annual-ds').value = rate.annual_ds || 1000;
    document.getElementById('vignette-age-min').value = rate.vehicle_age_min !== null ? rate.vehicle_age_min : '0';
    document.getElementById('vignette-age-max').value = rate.vehicle_age_max || '';
    document.getElementById('vignette-description').value = rate.description || '';
    document.getElementById('vignette-rate-modal-title').textContent = 'Modifier un Tarif';
    
    const modal = new bootstrap.Modal(document.getElementById('vignetteRateModal'));
    modal.show();
}

function saveVignetteRate() {
    const rateId = document.getElementById('vignette-rate-id').value;
    const price = document.getElementById('vignette-price').value;
    
    if (!price) {
        alert('Le prix est obligatoire');
        return;
    }
    
    const payload = {
        fiscal_class: document.getElementById('vignette-fiscal-class').value || null,
        cv_class: document.getElementById('vignette-cv-class').value || null,
        fuel_type: document.getElementById('vignette-fuel-type').value || null,
        price_kmf: parseFloat(price),
            annual_ds: parseFloat(document.getElementById('vignette-annual-ds').value) || 1000,
        vehicle_age_min: parseInt(document.getElementById('vignette-age-min').value) || 0,
        vehicle_age_max: document.getElementById('vignette-age-max').value ? parseInt(document.getElementById('vignette-age-max').value) : null,
        description: document.getElementById('vignette-description').value || null
    };
    
    const method = rateId ? 'PUT' : 'POST';
    const url = rateId ? `/api/vehicles/vignette-rates/${rateId}` : '/api/vehicles/vignette-rates';
    
    fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to save vignette rate');
        return r.json();
    })
    .then(data => {
        bootstrap.Modal.getInstance(document.getElementById('vignetteRateModal')).hide();
        loadVignetteRates();
        alert(rateId ? 'Tarif modifié avec succès' : 'Tarif créé avec succès');
    })
    .catch(err => {
        console.error('Error:', err);
        alert('Erreur: ' + err.message);
    });
}

function deleteVignetteRate(rateId) {
    if (!confirm('Êtes-vous sûr de vouloir supprimer ce tarif?')) return;
    
    fetch(`/api/vehicles/vignette-rates/${rateId}`, {
        method: 'DELETE',
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to delete vignette rate');
        return r.json();
    })
    .then(data => {
        loadVignetteRates();
        alert('Tarif supprimé avec succès');
    })
    .catch(err => {
        console.error('Error:', err);
        alert('Erreur: ' + err.message);
    });
}


// ============= PENALTY RATES =============

function loadPenaltyRates() {
    fetch('/api/vehicles/penalty-rates', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to load penalty rates');
        return r.json();
    })
    .then(data => {
        penaltyRatesCache = data.rates || [];
        console.log('Loaded ' + penaltyRatesCache.length + ' penalty rates');
        renderPenaltyRatesTable();
    })
    .catch(err => {
        console.error('Error loading penalty rates:', err);
        alert('Erreur lors du chargement des pénalités: ' + err.message);
    });
}

function renderPenaltyRatesTable() {
    const tbody = document.getElementById('penalty-rates-tbody');
    if (!tbody) return;

    if (penaltyRatesCache.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">Aucune pénalité définie</td></tr>';
        return;
    }

    tbody.innerHTML = penaltyRatesCache.map(rate => {
        return `
            <tr>
                <td class="text-center">${rate.days_late_min}</td>
                <td class="text-center">${rate.days_late_max}</td>
                <td class="fw-semibold">${parseInt(rate.penalty_per_day).toLocaleString('fr-KM')} KMF/jour</td>
                <td>${rate.description || '-'}</td>
                <td><span class="badge bg-success">Actif</span></td>
                <td>
                    <button class="btn btn-sm btn-warning" onclick="editPenaltyRate(${rate.id})">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-sm btn-danger ms-1" onclick="deletePenaltyRate(${rate.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function openPenaltyRateModal() {
    currentEditPenaltyRateId = null;
    document.getElementById('penalty-rate-id').value = '';
    document.getElementById('penalty-days-min').value = '';
    document.getElementById('penalty-days-max').value = '';
    document.getElementById('penalty-per-day').value = '';
    document.getElementById('penalty-description').value = '';
    document.getElementById('penalty-rate-modal-title').textContent = 'Ajouter une Pénalité';
    
    const modal = new bootstrap.Modal(document.getElementById('penaltyRateModal'));
    modal.show();
}

function editPenaltyRate(rateId) {
    const rate = penaltyRatesCache.find(r => r.id === rateId);
    if (!rate) return;
    
    currentEditPenaltyRateId = rateId;
    document.getElementById('penalty-rate-id').value = rateId;
    document.getElementById('penalty-days-min').value = rate.days_late_min;
    document.getElementById('penalty-days-max').value = rate.days_late_max;
    document.getElementById('penalty-per-day').value = rate.penalty_per_day;
    document.getElementById('penalty-description').value = rate.description || '';
    document.getElementById('penalty-rate-modal-title').textContent = 'Modifier une Pénalité';
    
    const modal = new bootstrap.Modal(document.getElementById('penaltyRateModal'));
    modal.show();
}

function savePenaltyRate() {
    const rateId = document.getElementById('penalty-rate-id').value;
    const daysMin = document.getElementById('penalty-days-min').value;
    const daysMax = document.getElementById('penalty-days-max').value;
    const perDay = document.getElementById('penalty-per-day').value;
    
    if (!daysMin || !daysMax || !perDay) {
        alert('Tous les champs obligatoires doivent être remplis');
        return;
    }
    
    const payload = {
        days_late_min: parseInt(daysMin),
        days_late_max: parseInt(daysMax),
        penalty_per_day: parseFloat(perDay),
        description: document.getElementById('penalty-description').value || null
    };
    
    const method = rateId ? 'PUT' : 'POST';
    const url = rateId ? `/api/vehicles/penalty-rates/${rateId}` : '/api/vehicles/penalty-rates';
    
    fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to save penalty rate');
        return r.json();
    })
    .then(data => {
        bootstrap.Modal.getInstance(document.getElementById('penaltyRateModal')).hide();
        loadPenaltyRates();
        alert(rateId ? 'Pénalité modifiée avec succès' : 'Pénalité créée avec succès');
    })
    .catch(err => {
        console.error('Error:', err);
        alert('Erreur: ' + err.message);
    });
}

function deletePenaltyRate(rateId) {
    if (!confirm('Êtes-vous sûr de vouloir supprimer cette pénalité?')) return;
    
    fetch(`/api/vehicles/penalty-rates/${rateId}`, {
        method: 'DELETE',
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to delete penalty rate');
        return r.json();
    })
    .then(data => {
        loadPenaltyRates();
        alert('Pénalité supprimée avec succès');
    })
    .catch(err => {
        console.error('Error:', err);
        alert('Erreur: ' + err.message);
    });
}

// ============= VIGNETTE SETTINGS (GENERAL) =============

async function loadVignetteSettings() {
    try {
        const res = await fetch('/api/vehicles/vignette-settings', { credentials: 'include' });
        if (!res.ok) return;
        const data = await res.json();
        const input = document.getElementById('renewal-opening-date');
        if (input) input.value = data.renewal_opening_date || '';
        updateRenewalStatusBanner(data.renewal_opening_date);
    } catch (e) {
        console.error('Error loading vignette settings:', e);
    }
}

function updateRenewalStatusBanner(dateStr) {
    const banner = document.getElementById('renewal-status-banner');
    if (!banner) return;
    if (!dateStr) {
        banner.className = 'alert alert-secondary mb-4';
        banner.innerHTML = '<i class="fas fa-minus-circle me-2"></i>Aucune date d\'ouverture configurée. Le renouvellement n\'est autorisé qu\'après le 31 mars.';
        banner.classList.remove('d-none');
        return;
    }
    const opening = new Date(dateStr);
    const now = new Date();
    const march31 = new Date(now.getFullYear(), 2, 31); // month is 0-indexed
    if (now >= opening && now <= march31) {
        banner.className = 'alert alert-success mb-4';
        banner.innerHTML = `<i class="fas fa-check-circle me-2"></i><strong>Période de renouvellement ouverte</strong> depuis le ${opening.toLocaleDateString('fr-FR', {day:'2-digit', month:'long', year:'numeric'})}. Les pénalités commenceront le 31 mars.`;
    } else if (now < opening) {
        banner.className = 'alert alert-warning mb-4';
        banner.innerHTML = `<i class="fas fa-clock me-2"></i>La période de renouvellement s'ouvrira le <strong>${opening.toLocaleDateString('fr-FR', {day:'2-digit', month:'long', year:'numeric'})}</strong>.`;
    } else {
        banner.className = 'alert alert-danger mb-4';
        banner.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>Le 31 mars est dépassé. Les <strong>pénalités de retard</strong> sont en cours d'application.`;
    }
    banner.classList.remove('d-none');
}

async function saveVignetteSettings() {
    const input = document.getElementById('renewal-opening-date');
    const msgEl = document.getElementById('settings-save-msg');
    const dateVal = input ? input.value : '';
    try {
        const res = await fetch('/api/vehicles/vignette-settings', {
            method: 'PUT',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ renewal_opening_date: dateVal || null })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Erreur serveur');
        updateRenewalStatusBanner(data.renewal_opening_date);
        if (msgEl) {
            msgEl.className = 'alert alert-success';
            msgEl.textContent = 'Paramètres enregistrés avec succès.';
            msgEl.classList.remove('d-none');
            setTimeout(() => msgEl.classList.add('d-none'), 3000);
        }
    } catch (e) {
        if (msgEl) {
            msgEl.className = 'alert alert-danger';
            msgEl.textContent = 'Erreur : ' + e.message;
            msgEl.classList.remove('d-none');
        }
    }
}

function clearRenewalDate() {
    const input = document.getElementById('renewal-opening-date');
    if (input) input.value = '';
    saveVignetteSettings();
}
