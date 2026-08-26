let noVignetteVehiclesCache = [];
let filteredNoVignetteVehiclesCache = [];
let noVignetteCurrentPage = 1;
const NO_VIGNETTE_PAGE_SIZE = 25;

document.addEventListener('DOMContentLoaded', function () {
    loadNoVignetteVehicles();
    setupNoVignetteEventListeners();
    setupNoVignetteAutoRefresh();
});

function setupNoVignetteEventListeners() {
    const searchInput = document.getElementById('no-vignette-search');
    if (searchInput) {
        searchInput.addEventListener('input', filterNoVignetteVehicles);
    }
}

function loadNoVignetteVehicles() {
    fetch('/api/vehicles/vignette-vehicles-without', {
        credentials: 'same-origin'
    })
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}: Failed to load vehicles without vignette`);
            return r.json();
        })
        .then(data => {
            noVignetteVehiclesCache = data.vehicles || [];
            // Show most recently created vehicles first (e.g., vehicles added from vehicle.html)
            noVignetteVehiclesCache.sort((a, b) => {
                const da = a.created_at ? new Date(a.created_at) : new Date(0);
                const db = b.created_at ? new Date(b.created_at) : new Date(0);
                return db - da;
            });
            filteredNoVignetteVehiclesCache = [...noVignetteVehiclesCache];
            noVignetteCurrentPage = 1;
            renderNoVignetteVehicles(filteredNoVignetteVehiclesCache);
        })
        .catch(err => {
            console.error('Error loading vehicles without vignette:', err);
            const tbody = document.getElementById('no-vignette-tbody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-4">Erreur de chargement</td></tr>';
            }
        });
}

function refreshNoVignetteDashboard() {
    loadNoVignetteVehicles();
}

function setupNoVignetteAutoRefresh() {
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            loadNoVignetteVehicles();
        }
    });

    window.addEventListener('focus', function() {
        loadNoVignetteVehicles();
    });

    setInterval(() => {
        if (!document.hidden) {
            loadNoVignetteVehicles();
        }
    }, 60000);
}

function filterNoVignetteVehicles() {
    const searchQuery = (document.getElementById('no-vignette-search').value || '').trim().toLowerCase();
    if (!searchQuery) {
        filteredNoVignetteVehiclesCache = [...noVignetteVehiclesCache];
        noVignetteCurrentPage = 1;
        renderNoVignetteVehicles(filteredNoVignetteVehiclesCache);
        return;
    }

    const filtered = noVignetteVehiclesCache.filter(vehicle => {
        const fields = [
            vehicle.license_plate || '',
            vehicle.owner_name || '',
            vehicle.owner_phone || '',
            vehicle.owner_island || '',
            vehicle.vehicle_type || ''
        ].map(v => v.toLowerCase());

        return fields.some(value => value.includes(searchQuery));
    });

    filteredNoVignetteVehiclesCache = filtered;
    noVignetteCurrentPage = 1;
    renderNoVignetteVehicles(filteredNoVignetteVehiclesCache);
}

function getNoVignettePaginatedSlice(list) {
    const start = (noVignetteCurrentPage - 1) * NO_VIGNETTE_PAGE_SIZE;
    const end = start + NO_VIGNETTE_PAGE_SIZE;
    return list.slice(start, end);
}

function renderNoVignettePagination(totalItems) {
    const container = document.getElementById('no-vignette-pagination');
    if (!container) return;

    if (totalItems === 0) {
        container.innerHTML = '<small class="text-muted">0 résultat</small>';
        return;
    }

    const totalPages = Math.max(1, Math.ceil(totalItems / NO_VIGNETTE_PAGE_SIZE));
    if (noVignetteCurrentPage > totalPages) noVignetteCurrentPage = totalPages;

    const start = (noVignetteCurrentPage - 1) * NO_VIGNETTE_PAGE_SIZE + 1;
    const end = Math.min(noVignetteCurrentPage * NO_VIGNETTE_PAGE_SIZE, totalItems);

    const pageButtons = [];
    for (let p = 1; p <= totalPages; p++) {
        if (p === 1 || p === totalPages || Math.abs(p - noVignetteCurrentPage) <= 1) {
            pageButtons.push(`
                <li class="page-item ${p === noVignetteCurrentPage ? 'active' : ''}">
                    <button class="page-link" onclick="goToNoVignettePage(${p})">${p}</button>
                </li>
            `);
        } else if (
            p === noVignetteCurrentPage - 2 ||
            p === noVignetteCurrentPage + 2
        ) {
            pageButtons.push('<li class="page-item disabled"><span class="page-link">...</span></li>');
        }
    }

    container.innerHTML = `
        <small class="text-muted">Affichage ${start}-${end} sur ${totalItems}</small>
        <nav aria-label="Pagination sans vignette">
            <ul class="pagination pagination-sm mb-0">
                <li class="page-item ${noVignetteCurrentPage === 1 ? 'disabled' : ''}">
                    <button class="page-link" onclick="goToNoVignettePage(${noVignetteCurrentPage - 1})">Précédent</button>
                </li>
                ${pageButtons.join('')}
                <li class="page-item ${noVignetteCurrentPage === totalPages ? 'disabled' : ''}">
                    <button class="page-link" onclick="goToNoVignettePage(${noVignetteCurrentPage + 1})">Suivant</button>
                </li>
            </ul>
        </nav>
    `;
}

function goToNoVignettePage(page) {
    const totalPages = Math.max(1, Math.ceil(filteredNoVignetteVehiclesCache.length / NO_VIGNETTE_PAGE_SIZE));
    if (page < 1 || page > totalPages) return;
    noVignetteCurrentPage = page;
    renderNoVignetteVehicles(filteredNoVignetteVehiclesCache);
}

function renderNoVignetteVehicles(sourceVehicles = noVignetteVehiclesCache) {
    const tbody = document.getElementById('no-vignette-tbody');
    const total = document.getElementById('no-vignette-total');
    if (!tbody || !total) return;

    const vehicles = Array.isArray(sourceVehicles) ? sourceVehicles : [];

    total.textContent = String(vehicles.length);

    if (vehicles.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">Aucun véhicule sans vignette</td></tr>';
        renderNoVignettePagination(0);
        return;
    }

    const paginatedVehicles = getNoVignettePaginatedSlice(vehicles);

    tbody.innerHTML = paginatedVehicles.map(vehicle => {
        const qrExpired = isQrCodeExpired(vehicle);
        const paymentPending = !!vehicle.vignette_payment_request_pending;
       const vinMissing = !vehicle.vin || !vehicle.vin.toString().trim();
        const qrStatus = qrExpired
            ? '<span class="badge bg-danger">QR expiré</span>'
            : '<span class="badge bg-success">QR actif</span>';

       const actionButton = vinMissing
           ? `<button class="btn btn-sm btn-danger" disabled title="VIN manquant: enregistrez le VIN avant d'ajouter une vignette">
                   <i class="fas fa-exclamation"></i> VIN requis
              </button>`
           : qrExpired
            ? `<button class="btn btn-sm btn-secondary" disabled title="QR expiré: activez le QR avant d'ajouter une vignette">
                    <i class="fas fa-ban"></i> Ajouter
               </button>`
            : paymentPending
            ? `<button class="btn btn-sm btn-warning" disabled title="Demande de paiement déjà envoyée à Mobile Money">
                    <i class="fas fa-clock me-1"></i>En attente
               </button>`
            : `<button class="btn btn-sm btn-success" onclick="openAddVignetteModal(${vehicle.id})">
                    <i class="fas fa-plus"></i> Ajouter
               </button>`;

        return `
            <tr>
                <td class="fw-semibold">${vehicle.license_plate || '-'}</td>
                <td>${vehicle.owner_name || '-'}</td>
                <td>${vehicle.vehicle_type || '-'}</td>
                <td>${vehicle.owner_island || '-'}</td>
                <td>${vehicle.owner_phone || '-'}</td>
                <td>${qrStatus}</td>
                <td>
                    ${actionButton}
                </td>
            </tr>
        `;
    }).join('');

    renderNoVignettePagination(vehicles.length);
}

function openAddVignetteModal(vehicleId) {
    const vehicle = noVignetteVehiclesCache.find(v => v.id === vehicleId);
    if (!vehicle) return;

    if (isQrCodeExpired(vehicle)) {
        alert('Impossible d\'ajouter une vignette: le QR code du véhicule est expiré.');
        return;
    }

    if (vehicle.vignette_payment_request_pending) {
        alert('Une demande de paiement est déjà en attente de confirmation Mobile Money.');
        return;
    }

    // Validation: VIN is required to add a vignette
    if (!vehicle.vin || !vehicle.vin.trim()) {
        alert('Impossible d\'ajouter une vignette: le véhicule n\'a pas de VIN (Numéro de série) enregistré. Veuillez d\'abord ajouter le VIN du véhicule.');
        return;
    }

    const qrExpiry = vehicle.qr_code_expiry ? formatDate(vehicle.qr_code_expiry) : 'Non défini';
    // Default expiry: 31 March of next year
    const nowDate = new Date();
    const nextYear = nowDate.getFullYear() + 1;
    const defaultExpiryValue = `${nextYear}-03-31`;
    
    // Get pricing information
    const vignettePrice = vehicle.vignette_price || 0;
    const finesAmount = vehicle.unpaid_fines_amount || 0;
    const qrActivationPrice = vehicle.qr_activation_price || 0;
    const totalAmount = vignettePrice + finesAmount + qrActivationPrice;

    // Build fines display
    let finesDisplay = '';
    if (finesAmount > 0) {
        finesDisplay = `
            <div class="alert alert-warning" role="alert">
                <strong><i class="fas fa-exclamation-circle me-2"></i>Amendes impayées:</strong>
                <div class="mt-2">${finesAmount.toLocaleString('fr-KM')} KMF</div>
            </div>
        `;
    }

    // Build price summary
    const priceSummary = `
        <div class="card border-start border-success border-4 bg-light">
            <div class="card-body">
                <div class="row mb-2">
                    <div class="col-6">
                        <strong>Prix vignette:</strong>
                    </div>
                    <div class="col-6 text-end">
                        ${vignettePrice > 0 ? vignettePrice.toLocaleString('fr-KM') + ' KMF' : '0 KMF'}
                    </div>
                </div>
                ${qrActivationPrice > 0 ? `
                <div class="row mb-2">
                    <div class="col-6">
                        <strong>Activation QR Code:</strong>
                    </div>
                    <div class="col-6 text-end">
                        ${qrActivationPrice.toLocaleString('fr-KM')} KMF
                    </div>
                </div>
                ` : ''}
                ${finesAmount > 0 ? `
                <div class="row mb-2">
                    <div class="col-6">
                        <strong>Amendes impayées:</strong>
                    </div>
                    <div class="col-6 text-end text-danger">
                        ${finesAmount.toLocaleString('fr-KM')} KMF
                    </div>
                </div>
                ` : ''}
                <hr/>
                <div class="row">
                    <div class="col-6">
                        <strong>Montant total à payer:</strong>
                    </div>
                    <div class="col-6 text-end">
                        <strong class="${finesAmount > 0 ? 'text-danger' : ''}">${totalAmount.toLocaleString('fr-KM')} KMF</strong>
                    </div>
                </div>
            </div>
        </div>
    `;

    const tariffMissing = vignettePrice <= 0;
    const saveButtonDisabledAttr = tariffMissing ? 'disabled' : '';
    const saveButtonTitle = tariffMissing
        ? 'Impossible d\'enregistrer: aucun tarif disponible pour cette combinaison fiscal/CV.'
        : '';
    const tariffWarning = tariffMissing
        ? `
            <div class="alert alert-danger" role="alert">
                <strong><i class="fas fa-ban me-2"></i>Tarif indisponible</strong>
                <div class="mt-2">Aucune grille de prix n\'est disponible pour cette combinaison de classe fiscale et classe CV. Le bouton Enregistrer est désactivé.</div>
            </div>
        `
        : '';

    const modalContent = `
        <div class="modal fade" id="noVignetteAddModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-success text-white">
                        <h5 class="modal-title"><i class="fas fa-ticket-alt me-2"></i>Ajouter une vignette</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <p class="mb-2"><strong>Immatriculation:</strong> ${vehicle.license_plate || '-'}</p>
                        <p class="mb-2"><strong>Propriétaire:</strong> ${vehicle.owner_name || '-'}</p>
                        <p class="mb-3"><strong>Île:</strong> ${vehicle.owner_island || '-'}</p>
                        
                        <h6 class="mb-3"><i class="fas fa-money-bill me-2"></i>Résumé des frais</h6>
                        ${priceSummary}
                        ${tariffWarning}
                        
                        <hr class="my-3"/>
                        
                        <label for="add-vignette-expiry" class="form-label fw-semibold mt-3">Date d'expiration vignette</label>
                        <input type="date" id="add-vignette-expiry" class="form-control" value="${defaultExpiryValue}" />
                        <div id="add-vignette-error" class="text-danger mt-2 small"></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-success" id="save-add-vignette-btn" onclick="saveNoVignetteDate(${vehicle.id})" ${saveButtonDisabledAttr} title="${saveButtonTitle}">
                            <i class="fas fa-save me-1"></i>Enregistrer
                        </button>
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Fermer</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    const oldModal = document.getElementById('noVignetteAddModal');
    if (oldModal) oldModal.remove();

    document.body.insertAdjacentHTML('beforeend', modalContent);
    const modal = new bootstrap.Modal(document.getElementById('noVignetteAddModal'));
    modal.show();
}

function saveNoVignetteDate(vehicleId) {
    const dateInput = document.getElementById('add-vignette-expiry');
    const errorEl = document.getElementById('add-vignette-error');
    const saveBtn = document.getElementById('save-add-vignette-btn');

    if (errorEl) errorEl.textContent = '';
    const vignetteExpiry = dateInput ? dateInput.value : '';
    if (!vignetteExpiry) {
        if (errorEl) errorEl.textContent = 'Veuillez sélectionner une date d\'expiration.';
        return;
    }

    const vehicle = noVignetteVehiclesCache.find(v => v.id === vehicleId);
    const vignettePrice = Number(vehicle && vehicle.vignette_price ? vehicle.vignette_price : 0);
    if (vignettePrice <= 0) {
        if (errorEl) errorEl.textContent = 'Impossible d\'enregistrer: aucun tarif disponible pour cette combinaison fiscal/CV.';
        return;
    }

    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Enregistrement...';
    }

    fetch(`/api/vehicles/${vehicleId}/vignette/payment-request`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify({ vignette_expiry: vignetteExpiry })
    })
        .then(async r => {
            if (!r.ok) {
                let message = 'Erreur lors de l\'ajout de la vignette';
                try {
                    const payload = await r.json();
                    message = payload.error || payload.message || message;
                } catch (e) {
                    // Keep default message.
                }
                throw new Error(message);
            }
            return r.json();
        })
        .then(() => {
            const idx = noVignetteVehiclesCache.findIndex(v => v.id === vehicleId);
            if (idx >= 0) {
                noVignetteVehiclesCache[idx].vignette_payment_request_pending = true;
                noVignetteVehiclesCache[idx].vignette_payment_requested_expiry = vignetteExpiry;
            }
            filterNoVignetteVehicles();

            const modalEl = document.getElementById('noVignetteAddModal');
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();

            alert('Demande de paiement envoyée à Mobile Money. La vignette sera mise à jour après confirmation.');
        })
        .catch(err => {
            if (errorEl) errorEl.textContent = err.message;
        })
        .finally(() => {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<i class="fas fa-save me-1"></i>Enregistrer';
            }
        });
}

function isQrCodeExpired(vehicle) {
    return !!(vehicle && vehicle.qr_code_expiry && new Date(vehicle.qr_code_expiry) < new Date());
}

function formatDate(date) {
    if (!date) return '-';
    const d = new Date(date);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    return `${day}/${month}/${year}`;
}
