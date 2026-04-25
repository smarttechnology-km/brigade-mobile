/**
 * Insurance Dashboard Script
 * Allows insurance accounts to view and update their assigned vehicles
 */

let vehiclesCache = [];
let currentEditVehicle = null;

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
    
    // Load company info and vehicles in parallel
    Promise.all([
        loadCompanyInfo(),
        loadAssignedVehicles()
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
        
        const actionButton = vehicle.has_unpaid_fines
            ? `<button class="btn btn-sm btn-outline-secondary" type="button" onclick="showFineDetails(${vehicle.id})" title="Cliquer pour voir le type d'amende">
                    <i class="fas fa-lock"></i>
                </button>`
            : `<button class="btn btn-sm btn-outline-primary" onclick="openEditDatesModal(${vehicle.id})" title="Modifier les dates">
                    <i class="fas fa-edit"></i>
                </button>`;

        return `
            <tr>
                <td><strong>${vehicle.license_plate}</strong></td>
                <td>${vehicle.owner_name || '-'}</td>
                <td>${vehicle.vehicle_type || '-'}</td>
                <td>${vehicle.owner_island || '-'}</td>
                <td>${vehicle.owner_phone || '-'}</td>
                <td>${vehicle.usage_type || '-'}</td>
                <td>${insuranceBadge}</td>
                <td>
                    ${actionButton}
                </td>
            </tr>
        `;
    }).join('');
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

    if (vehicle.has_unpaid_fines) {
        alert(vehicle.block_reason || 'Ce véhicule a une amende non payée.');
        return;
    }
    
    currentEditVehicle = vehicle;
    
    document.getElementById('edit-vehicle-id').value = vehicle.id;
    document.getElementById('edit-license-plate').value = vehicle.license_plate;
    document.getElementById('edit-owner-name').value = vehicle.owner_name || '';
    document.getElementById('edit-vehicle-type').value = vehicle.vehicle_type || '';
    document.getElementById('edit-owner-island').value = vehicle.owner_island || '';
    document.getElementById('edit-owner-phone').value = vehicle.owner_phone || '';
    document.getElementById('edit-usage-type').value = vehicle.usage_type || '';
    document.getElementById('edit-insurance-expiry').value = vehicle.insurance_expiry ? vehicle.insurance_expiry.split('T')[0] : '';
    
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
    
    if (!insuranceExpiry) {
        alert('Veuillez sélectionner une date d\'expiration pour l\'assurance');
        return;
    }
    
    const payload = {
        insurance_expiry: insuranceExpiry
    };
    
    fetch(`/api/vehicles/${vehicleId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
    })
    .then(r => {
        if (!r.ok) return r.json().then(e => { throw e; });
        return r.json();
    })
    .then(data => {
        console.log('Vehicle dates updated:', data);
        bootstrap.Modal.getInstance(document.getElementById('editDatesModal')).hide();
        loadAssignedVehicles().then(() => {
            updateStatistics();
            renderVehiclesTable();
        });
    })
    .catch(err => {
        console.error('Error updating vehicle dates:', err);
        alert(err.error || 'Erreur lors de la mise à jour');
    });
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = typeof dateString === 'string' ? new Date(dateString) : dateString;
    return new Intl.DateTimeFormat('fr-FR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}
