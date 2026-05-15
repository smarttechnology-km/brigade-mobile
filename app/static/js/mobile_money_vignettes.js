let vignetteVehiclesCache = [];
let filteredVignetteVehiclesCache = [];
let selectedVignetteVehicleId = null;

document.addEventListener('DOMContentLoaded', function () {
    const searchEl = document.getElementById('mm-vignette-search');
    const refreshBtn = document.getElementById('mm-vignette-refresh-btn');
    const confirmBtn = document.getElementById('mm-vignette-confirm-btn');

    if (searchEl) {
        searchEl.addEventListener('input', function () {
            filterVignetteVehicles(this.value || '');
        });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', function () {
            loadVignettePayments();
        });
    }

    if (confirmBtn) {
        confirmBtn.addEventListener('click', approveVignettePayment);
    }

    loadVignettePayments();
});

function loadVignettePayments() {
    const tbody = document.getElementById('mm-vignette-tbody');
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Chargement...</td></tr>';
    }

    fetch('/api/vehicles/vignette-vehicles', { credentials: 'same-origin' })
        .then(function (r) {
            if (!r.ok) throw new Error('Erreur de chargement');
            return r.json();
        })
        .then(function (data) {
            const vehicles = Array.isArray(data.vehicles) ? data.vehicles : [];
            vignetteVehiclesCache = vehicles.filter(function (vehicle) {
                return vehicle.vignette_status === 'expired' || vehicle.vignette_status === 'pending' || vehicle.vignette_payment_request_pending;
            });

            vignetteVehiclesCache.sort(function (a, b) {
                const dateA = a.vignette_expiry ? new Date(a.vignette_expiry) : new Date(0);
                const dateB = b.vignette_expiry ? new Date(b.vignette_expiry) : new Date(0);
                return dateA - dateB;
            });

            filteredVignetteVehiclesCache = vignetteVehiclesCache.slice();
            renderVignetteVehicles(filteredVignetteVehiclesCache);
            updateCount(filteredVignetteVehiclesCache.length);
        })
        .catch(function () {
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="10" class="text-center text-danger py-4">Erreur lors du chargement des vignettes expirées.</td></tr>';
            }
            updateCount(0);
        });
}

function updateCount(count) {
    const badge = document.getElementById('mm-vignette-count');
    if (badge) {
        badge.textContent = count + ' véhicule(s)';
    }
}

function filterVignetteVehicles(query) {
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        filteredVignetteVehiclesCache = vignetteVehiclesCache.slice();
    } else {
        filteredVignetteVehiclesCache = vignetteVehiclesCache.filter(function (vehicle) {
            return (
                (vehicle.license_plate || '').toLowerCase().includes(q) ||
                (vehicle.owner_name || '').toLowerCase().includes(q) ||
                (vehicle.owner_island || '').toLowerCase().includes(q)
            );
        });
    }

    renderVignetteVehicles(filteredVignetteVehiclesCache);
    updateCount(filteredVignetteVehiclesCache.length);
}

function renderVignetteVehicles(items) {
    const tbody = document.getElementById('mm-vignette-tbody');
    if (!tbody) return;

    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-4">Aucune vignette expirée à traiter.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(function (vehicle, idx) {
        const vignettePrice = Number(vehicle.vignette_price || 0);
        const penaltyAmount = Number(vehicle.penalty_amount || 0);
        const finesAmount = Number(vehicle.unpaid_fines_amount || 0);
        const totalAmount = vignettePrice + penaltyAmount + finesAmount;

        let expiryDate = vehicle.vignette_expiry || '-';
        if (vehicle.vignette_expiry) {
            try {
                expiryDate = new Date(vehicle.vignette_expiry).toLocaleDateString('fr-FR');
            } catch (e) {
                expiryDate = vehicle.vignette_expiry;
            }
        }

        const approved = !!vehicle.vignette_payment_approved;
        const pendingRequest = !!vehicle.vignette_payment_request_pending && !approved;
        const pendingStatus = vehicle.vignette_status === 'pending' && !approved;
        const statusBadge = approved
            ? '<span class="badge bg-success">Approuvé</span>'
            : pendingStatus || pendingRequest
            ? '<span class="badge bg-primary">Demande en attente</span>'
            : '<span class="badge bg-warning text-dark">En attente</span>';

        const actionButton = approved
            ? '<button class="btn btn-sm btn-outline-success" disabled><i class="fas fa-check me-1"></i>Déjà approuvé</button>'
            : '<button class="btn btn-sm btn-success" data-vignette-id="' + vehicle.id + '"><i class="fas fa-circle-check me-1"></i>Accepter paiement</button>';

        const displayExpiry = vehicle.vignette_expiry || vehicle.vignette_requested_expiry || '-';

        return '<tr>' +
            '<td>' + (idx + 1) + '</td>' +
            '<td>' + (vehicle.license_plate || '') + '</td>' +
            '<td>' + (vehicle.owner_name || '-') + '</td>' +
            '<td>' + (vehicle.owner_island || '-') + '</td>' +
            '<td>' + (displayExpiry ? (displayExpiry === '-' ? '-' : new Date(displayExpiry).toLocaleDateString('fr-FR')) : '-') + '</td>' +
            '<td>' + Math.round(vignettePrice) + ' KMF</td>' +
            '<td>' + Math.round(penaltyAmount) + ' KMF</td>' +
            '<td>' + Math.round(finesAmount) + ' KMF</td>' +
            '<td><strong>' + Math.round(totalAmount) + ' KMF</strong></td>' +
            '<td>' + statusBadge + '</td>' +
            '<td>' + actionButton + '</td>' +
            '</tr>';
    }).join('');

    tbody.querySelectorAll('[data-vignette-id]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            openVignettePaymentModal(this.getAttribute('data-vignette-id'));
        });
    });
}

function openVignettePaymentModal(vehicleId) {
    selectedVignetteVehicleId = vehicleId;
    const vehicle = vignetteVehiclesCache.find(function (item) {
        return String(item.id) === String(vehicleId);
    });
    if (!vehicle) return;

    const vignettePrice = Number(vehicle.vignette_price || 0);
    const penaltyAmount = Number(vehicle.penalty_amount || 0);
    const finesAmount = Number(vehicle.unpaid_fines_amount || 0);
    const totalAmount = vignettePrice + penaltyAmount + finesAmount;

    const text = document.getElementById('mm-vignette-pay-text');
    if (text) {
        text.textContent = 'Approuver le paiement de ' + (vehicle.license_plate || '') + ' pour renouvellement: ' + Math.round(totalAmount) + ' KMF ?';
    }

    const modal = new bootstrap.Modal(document.getElementById('mmVignettePayModal'));
    modal.show();
}

function approveVignettePayment() {
    if (!selectedVignetteVehicleId) return;

    const paymentMethod = document.getElementById('mm-vignette-pay-method').value || 'mobile_money_manual';

    fetch('/api/vehicles/' + selectedVignetteVehicleId + '/vignette/payment-approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_method: paymentMethod })
    })
        .then(function (r) {
            if (!r.ok) {
                return r.json().then(function (payload) {
                    throw new Error(payload.error || 'Erreur lors de l’approbation');
                });
            }
            return r.json();
        })
        .then(function (res) {
            const modalEl = document.getElementById('mmVignettePayModal');
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();

            if (window.showSuccess) {
                window.showSuccess(res.message || 'Paiement de vignette approuvé');
            } else {
                alert(res.message || 'Paiement de vignette approuvé');
            }

            loadVignettePayments();
        })
        .catch(function (err) {
            alert(err.message || 'Erreur lors de l’approbation du paiement');
        });
}
