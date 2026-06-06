/**
 * Vignette Dashboard Script
 * Allows tax agents to view and update vehicle vignettes
 */

let vehiclesCache = [];
let filteredVehiclesCache = [];
let currentEditVehicle = null;
let currentPage = 1;
const PAGE_SIZE = 25;

document.addEventListener('DOMContentLoaded', function() {
    console.log('Vignette dashboard loaded');
    loadDashboardData();
    setupEventListeners();
    setupAutoRefresh();
});

function setupEventListeners() {
    const searchInput = document.getElementById('vehicle-search');
    const filterSelect = document.getElementById('vignette-filter');
    
    if (searchInput) {
        searchInput.addEventListener('input', filterVehicles);
    }
    if (filterSelect) {
        filterSelect.addEventListener('change', filterVehicles);
    }
}

function loadDashboardData() {
    console.log('Loading vignette dashboard data...');
    loadVignetteVehicles()
        .then(() => {
            updateStatistics();
            filteredVehiclesCache = [...vehiclesCache];
            
            // Sort by updated_at (most recent first) so newly added/renewed vehicles appear at top
            filteredVehiclesCache.sort((a, b) => {
                const dateA = new Date(a.updated_at || 0);
                const dateB = new Date(b.updated_at || 0);
                return dateB - dateA; // Descending order (most recent first)
            });
            
            currentPage = 1;
            renderVehiclesTable(filteredVehiclesCache);
        })
        .catch(err => console.error('Error loading dashboard:', err));
}

function refreshVignetteDashboard() {
    loadDashboardData();
}

function setupAutoRefresh() {
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            loadDashboardData();
        }
    });

    window.addEventListener('focus', function() {
        loadDashboardData();
    });

    setInterval(() => {
        if (!document.hidden) {
            loadDashboardData();
        }
    }, 60000);
}

function loadVignetteVehicles() {
    return fetch('/api/vehicles/vignette-vehicles', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: Failed to load vehicles`);
        return r.json();
    })
    .then(data => {
        vehiclesCache = data.vehicles || [];
        console.log('Loaded ' + vehiclesCache.length + ' vehicles with vignettes');
        
        // Log if no vehicles
        if (vehiclesCache.length === 0) {
            console.warn('No vehicles with vignettes found. Check if vehicles have vignette_expiry set.');
        }
    })
    .catch(err => {
        console.error('Error loading vehicles:', err);
        throw err;
    });
}

function updateStatistics() {
    const today = new Date();
    const thirtyDaysFromNow = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000);
    
    let totalVehicles = 0;
    let activeCount = 0;
    let expiringSoon = 0;
    let expiredCount = 0;
    
    vehiclesCache.forEach(vehicle => {
        totalVehicles++;
        
        const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
        const isPending = vehicle.vignette_status === 'pending' || (vehicle.vignette_payment_request_pending && !vehicle.vignette_expiry);
        
        if (isPending) {
            // Pending requests are not counted as active/expired.
        } else if (!vignetteExpiry) {
            // No expiry date set
        } else if (vignetteExpiry < today) {
            expiredCount++;
        } else if (vignetteExpiry < thirtyDaysFromNow) {
            expiringSoon++;
        } else {
            activeCount++;
        }
    });
    
    document.getElementById('total-vehicles').textContent = totalVehicles;
    document.getElementById('active-count').textContent = activeCount;
    document.getElementById('expiring-soon').textContent = expiringSoon;
    document.getElementById('expired-count').textContent = expiredCount;
}

function isQrCodeExpired(vehicle) {
    if (!vehicle || !vehicle.qr_code_expiry) return false;
    return new Date(vehicle.qr_code_expiry) < new Date();
}

function getPaginatedSlice(list) {
    const start = (currentPage - 1) * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    return list.slice(start, end);
}

function renderVehiclesPagination(totalItems) {
    const container = document.getElementById('vignette-pagination');
    if (!container) return;

    if (totalItems === 0) {
        container.innerHTML = '<small class="text-muted">0 résultat</small>';
        return;
    }

    const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * PAGE_SIZE + 1;
    const end = Math.min(currentPage * PAGE_SIZE, totalItems);

    const pageButtons = [];
    for (let p = 1; p <= totalPages; p++) {
        if (p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1) {
            pageButtons.push(`
                <li class="page-item ${p === currentPage ? 'active' : ''}">
                    <button class="page-link" onclick="goToVignettePage(${p})">${p}</button>
                </li>
            `);
        } else if (
            p === currentPage - 2 ||
            p === currentPage + 2
        ) {
            pageButtons.push('<li class="page-item disabled"><span class="page-link">...</span></li>');
        }
    }

    container.innerHTML = `
        <small class="text-muted">Affichage ${start}-${end} sur ${totalItems}</small>
        <nav aria-label="Pagination vignettes">
            <ul class="pagination pagination-sm mb-0">
                <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                    <button class="page-link" onclick="goToVignettePage(${currentPage - 1})">Précédent</button>
                </li>
                ${pageButtons.join('')}
                <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                    <button class="page-link" onclick="goToVignettePage(${currentPage + 1})">Suivant</button>
                </li>
            </ul>
        </nav>
    `;
}

function goToVignettePage(page) {
    const totalPages = Math.max(1, Math.ceil(filteredVehiclesCache.length / PAGE_SIZE));
    if (page < 1 || page > totalPages) return;
    currentPage = page;
    renderVehiclesTable(filteredVehiclesCache);
}

function renderVehiclesTable(sourceVehicles = vehiclesCache) {
    const tbody = document.getElementById('vehicles-tbody');
    if (!tbody) return;

    const vehicles = Array.isArray(sourceVehicles) ? sourceVehicles : [];

    if (vehicles.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Aucun véhicule avec vignette trouvé</td></tr>';
        renderVehiclesPagination(0);
        return;
    }

    const paginatedVehicles = getPaginatedSlice(vehicles);
    
    tbody.innerHTML = paginatedVehicles.map(vehicle => {
        const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
        const requestedExpiry = vehicle.vignette_requested_expiry ? new Date(vehicle.vignette_requested_expiry) : null;
        const today = new Date();
        const isPending = vehicle.vignette_status === 'pending' || (vehicle.vignette_payment_request_pending && !vehicle.vignette_expiry);
        
        let statusBadge = '';
        let statusText = '';
        let isExpired = false;
        
        if (isPending) {
            statusBadge = 'badge bg-warning text-dark';
            statusText = 'En attente';
        } else if (!vignetteExpiry) {
            statusBadge = 'badge bg-secondary';
            statusText = 'Pas de vignette';
        } else if (vignetteExpiry < today) {
            statusBadge = 'badge bg-danger';
            statusText = 'Expirée';
            isExpired = true;
        } else if (vehicle.renewal_needed) {
            statusBadge = 'badge bg-info';
            statusText = 'À renouveler';
        } else if (vignetteExpiry < new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000)) {
            statusBadge = 'badge bg-warning';
            statusText = 'Expiration proche';
        } else {
            statusBadge = 'badge bg-success';
            statusText = 'Active';
        }
        
        let actionButtonsContent = `
            <button class="btn btn-sm btn-info" onclick="openViewVehicleModal(${vehicle.id})">
                <i class="fas fa-eye"></i> Voir
            </button>
        `;
        
        if (isExpired) {
            if (isQrCodeExpired(vehicle)) {
                actionButtonsContent += `
                <button class="btn btn-sm btn-secondary ms-1" disabled title="QR code expiré: activez le QR avant de renouveler la vignette">
                    <i class="fas fa-ban"></i> QR expiré
                </button>
                `;
            } else if (vehicle.vignette_payment_approved) {
                actionButtonsContent += `
                <button class="btn btn-sm btn-success ms-1" onclick="renewVignette(${vehicle.id})">
                    <i class="fas fa-sync-alt"></i> 
                </button>
                `;
            } else {
                actionButtonsContent += `
                <button class="btn btn-sm btn-outline-warning ms-1" disabled title="Paiement Mobile Money requis avant renouvellement">
                    <i class="fas fa-clock"></i> 
                </button>
                `;
            }
        }
        
        const actionButtons = `<div class="d-flex gap-2 flex-nowrap">${actionButtonsContent}</div>`;
        
        // Get penalty amount from API response
        const penaltyAmount = vehicle.penalty_amount || 0;
        
        // Get unpaid fines amount (default to 0 if not provided)
        const finesAmount = vehicle.unpaid_fines_amount || 0;
        
        // Get vignette price from API response
        const vignettePrice = vehicle.vignette_price || 0;
        const displayExpiry = vehicle.vignette_expiry || vehicle.vignette_requested_expiry || null;
        
        // Calculate total
        const totalAmount = vignettePrice + penaltyAmount + finesAmount;
        
        return `
            <tr>
                <td class="fw-semibold">${vehicle.license_plate || '-'}</td>
                <td>${vehicle.vehicle_type || '-'}</td>
                <td>${vehicle.usage_type || '-'}</td>
            <td>${displayExpiry ? formatDate(displayExpiry) : '-'}</td>
                <td class="text-center">${vignettePrice > 0 ? vignettePrice.toLocaleString('fr-KM') + ' KMF' : '-'}</td>
                <td class="text-center ${penaltyAmount > 0 ? 'text-danger' : ''}">${penaltyAmount > 0 ? penaltyAmount.toLocaleString('fr-KM') + ' KMF' : '-'}</td>
                <td class="text-center ${finesAmount > 0 ? 'text-danger' : ''}">${finesAmount > 0 ? finesAmount.toLocaleString('fr-KM') + ' KMF' : '-'}</td>
                <td class="fw-semibold text-center ${totalAmount > 0 ? 'text-danger' : ''}">${totalAmount > 0 ? totalAmount.toLocaleString('fr-KM') + ' KMF' : '-'}</td>
                <td><span class="${statusBadge}">${statusText}</span></td>
                <td>${actionButtons}</td>
            </tr>
        `;
    }).join('');

    renderVehiclesPagination(vehicles.length);
}

function filterVehicles() {
    const searchQuery = (document.getElementById('vehicle-search').value || '').toLowerCase();
    const statusFilter = document.getElementById('vignette-filter').value;
    
    let filtered = vehiclesCache;
    
    // Apply search filter
    if (searchQuery) {
        filtered = filtered.filter(vehicle => {
            const searchableFields = [
                vehicle.license_plate || '',
                vehicle.owner_name || '',
                vehicle.owner_phone || '',
                vehicle.owner_island || ''
            ].map(f => f.toLowerCase());
            
            return searchableFields.some(field => field.includes(searchQuery));
        });
    }
    
    // Apply status filter
    if (statusFilter) {
        const today = new Date();
        const thirtyDaysFromNow = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000);
        
        filtered = filtered.filter(vehicle => {
            const isPending = vehicle.vignette_status === 'pending' || (vehicle.vignette_payment_request_pending && !vehicle.vignette_expiry);
            const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
            
            if (statusFilter === 'pending') {
                return isPending;
            }
            if (statusFilter === 'active') {
                return vignetteExpiry && vignetteExpiry >= thirtyDaysFromNow;
            } else if (statusFilter === 'expiring') {
                return vignetteExpiry && vignetteExpiry < thirtyDaysFromNow && vignetteExpiry >= today;
            } else if (statusFilter === 'expired') {
                return vignetteExpiry && vignetteExpiry < today;
            }
            return true;
        });
    }
    
    // Sort by updated_at (most recent first) so newly added/renewed vehicles appear at top
    filtered.sort((a, b) => {
        const dateA = new Date(a.updated_at || 0);
        const dateB = new Date(b.updated_at || 0);
        return dateB - dateA; // Descending order (most recent first)
    });
    
    filteredVehiclesCache = filtered;
    currentPage = 1;
    renderVehiclesTable(filteredVehiclesCache);
}

function openUpdateVignetteModal(vehicleId) {
    const vehicle = vehiclesCache.find(v => v.id === vehicleId);
    if (!vehicle) {
        console.error('Vehicle not found:', vehicleId);
        return;
    }
    
    currentEditVehicle = vehicle;
    
    // Populate modal fields
    document.getElementById('edit-vehicle-id').value = vehicle.id;
    document.getElementById('edit-license-plate').value = vehicle.license_plate || '';
    document.getElementById('edit-owner-name').value = vehicle.owner_name || '';
    document.getElementById('edit-vehicle-type').value = vehicle.vehicle_type || '';
    document.getElementById('edit-owner-island').value = vehicle.owner_island || '';
    document.getElementById('edit-owner-phone').value = vehicle.owner_phone || '';
    document.getElementById('edit-fuel-type').value = vehicle.fuel_type || '';
    
    // Set vignette expiry date
    if (vehicle.vignette_expiry) {
        document.getElementById('edit-vignette-expiry').value = vehicle.vignette_expiry;
    } else {
        document.getElementById('edit-vignette-expiry').value = '';
    }
    
    // Show alert if vignette is expired or expiring soon
    const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
    const today = new Date();
    const alertDiv = document.getElementById('edit-dates-alert');
    const alertText = document.getElementById('edit-dates-alert-text');
    
    if (vignetteExpiry && vignetteExpiry < today) {
        alertDiv.style.display = 'block';
        alertText.textContent = 'La vignette est expirée depuis le ' + formatDate(vignetteExpiry);
    } else if (vignetteExpiry && vignetteExpiry < new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000)) {
        alertDiv.style.display = 'block';
        alertText.textContent = 'La vignette expirera bientôt (' + formatDate(vignetteExpiry) + ')';
    } else {
        alertDiv.style.display = 'none';
    }
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('updateVignetteModal'));
    modal.show();
}

function saveVignetteDate() {
    const vehicleId = parseInt(document.getElementById('edit-vehicle-id').value);
    const vignetteExpiry = document.getElementById('edit-vignette-expiry').value;
    
    if (!vehicleId || !vignetteExpiry) {
        alert('Veuillez remplir tous les champs');
        return;
    }
    
    const saveBtn = document.getElementById('save-vignette-btn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Enregistrement...';
    
    fetch(`/api/vehicles/${vehicleId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify({
            vignette_expiry: vignetteExpiry
        })
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to update vehicle');
        return r.json();
    })
    .then(data => {
        // Update cache
        const vehicleIdx = vehiclesCache.findIndex(v => v.id === vehicleId);
        if (vehicleIdx >= 0) {
            vehiclesCache[vehicleIdx].vignette_expiry = vignetteExpiry;
        }
        
        // Refresh statistics and table
        updateStatistics();
        filterVehicles();
        
        // Close modal
        bootstrap.Modal.getInstance(document.getElementById('updateVignetteModal')).hide();
        
        // Show success message
        alert('Vignette mise à jour avec succès');
    })
    .catch(err => {
        console.error('Error:', err);
        alert('Erreur lors de la mise à jour: ' + err.message);
    })
    .finally(() => {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save me-1"></i>Enregistrer';
    });
}

function openViewVehicleModal(vehicleId) {
    const vehicle = vehiclesCache.find(v => v.id === vehicleId);
    if (!vehicle) {
        console.error('Vehicle not found:', vehicleId);
        return;
    }
    
    // Create a simple modal content
    const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
    const modalContent = `
        <div class="modal fade" id="viewVehicleModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-lg modal-dialog-centered">
                <div class="modal-content border-0 shadow-lg">
                    <div class="modal-header bg-info text-white">
                        <h5 class="modal-title">
                            <i class="fas fa-car me-2"></i>
                            <span>${vehicle.license_plate}</span>
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-4">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-id-card text-muted me-1"></i>Immatriculation</label>
                                <p>${vehicle.license_plate || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-user text-muted me-1"></i>Propriétaire</label>
                                <p>${vehicle.owner_name || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-car text-muted me-1"></i>Type</label>
                                <p>${vehicle.vehicle_type || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-fuel-pump text-muted me-1"></i>Carburant</label>
                                <p>${vehicle.fuel_type || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-layer-group text-muted me-1"></i>Classe Fiscale</label>
                                <p>${vehicle.fiscal_class || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-tachometer-alt text-muted me-1"></i>Classe CV</label>
                                <p>${vehicle.cv_class || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-barcode text-muted me-1"></i>VIN (Numéro de série)</label>
                                <p>${vehicle.vin || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-map-marker-alt text-muted me-1"></i>Île</label>
                                <p>${vehicle.owner_island || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-phone text-muted me-1"></i>Téléphone</label>
                                <p>${vehicle.owner_phone || '-'}</p>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold"><i class="fas fa-ticket-alt text-primary me-1"></i>Vignette Exp.</label>
                                <p>${vignetteExpiry ? formatDate(vignetteExpiry) : 'Pas de vignette'}</p>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer bg-light">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="fas fa-times me-1"></i>Fermer
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove old modal if exists
    const oldModal = document.getElementById('viewVehicleModal');
    if (oldModal) oldModal.remove();
    
    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalContent);
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('viewVehicleModal'));
    modal.show();
}

function renewVignette(vehicleId) {
    const vehicle = vehiclesCache.find(v => v.id === vehicleId);
    if (!vehicle) {
        console.error('Vehicle not found:', vehicleId);
        return;
    }

    if (isQrCodeExpired(vehicle)) {
        alert('Impossible de renouveler la vignette: le QR code du véhicule est expiré. Activez d\'abord le QR code.');
        return;
    }
    
    const vignetteExpiry = vehicle.vignette_expiry ? new Date(vehicle.vignette_expiry) : null;
    if (!vignetteExpiry) {
        alert('Impossible de Renew: aucune date d\'expiration définie');
        return;
    }
    
    // Confirm renewal
    const confirmMsg = `Renew la vignette de ${vehicle.license_plate}?\n` +
        `Date actuelle: ${formatDate(vignetteExpiry)}\n` +
        `Nouvelle date: ${formatDate(new Date(vignetteExpiry.getTime() + 365 * 24 * 60 * 60 * 1000))}`;
    
    if (!confirm(confirmMsg)) return;
    
    // Calculate new expiry date (1 year from current expiry)
    const newExpiry = new Date(vignetteExpiry.getTime() + 365 * 24 * 60 * 60 * 1000);
    
    // Update vehicle
    fetch(`/api/vehicles/${vehicleId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify({
            vignette_expiry: newExpiry.toISOString().split('T')[0]
        })
    })
    .then(async r => {
        if (!r.ok) {
            let message = 'Failed to renew vignette';
            try {
                const payload = await r.json();
                message = payload.error || payload.message || message;
            } catch (e) {
                // Keep default message when response is not JSON.
            }
            throw new Error(message);
        }
        return r.json();
    })
    .then(data => {
        // Update cache
        const vehicleIdx = vehiclesCache.findIndex(v => v.id === vehicleId);
        if (vehicleIdx >= 0) {
            vehiclesCache[vehicleIdx].vignette_expiry = newExpiry.toISOString().split('T')[0];
        }
        
        // Refresh statistics and table
        updateStatistics();
        filterVehicles();
        
        // Show success message
        alert('✅ Vignette renouvelée avec succès jusqu\'au ' + formatDate(newExpiry));
    })
    .catch(err => {
        console.error('Error:', err);
        alert('❌ Erreur lors du renouvellement: ' + err.message);
    });
}

function formatDate(date) {
    if (!date) return '-';
    const d = new Date(date);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    return `${day}/${month}/${year}`;
}
