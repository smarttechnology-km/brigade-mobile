let mmAllFines = [];
let mmAllVehicles = [];
let mmFilteredVehicles = [];
let selectedVehicleId = null;
let _mmdLastRefresh = Date.now();

function _mmdUpdateLiveBadge() {
    const badge = document.getElementById('mmd-live-badge');
    if (!badge) return;
    const secs = Math.round((Date.now() - _mmdLastRefresh) / 1000);
    if (secs < 5) {
        badge.className = 'badge bg-success ms-2 fw-normal align-middle';
        badge.textContent = '● En direct';
    } else if (secs < 35) {
        badge.className = 'badge bg-secondary ms-2 fw-normal align-middle';
        badge.textContent = `↻ il y a ${secs}s`;
    } else {
        badge.className = 'badge bg-warning text-dark ms-2 fw-normal align-middle';
        badge.textContent = `↻ il y a ${secs}s`;
    }
}

function setupDashboardAutoRefresh() {
    _mmdUpdateLiveBadge();
    setInterval(_mmdUpdateLiveBadge, 1000);

    function doRefresh() {
        if (document.hidden) return;
        _mmdLastRefresh = Date.now();
        _mmdUpdateLiveBadge();
        loadUnpaidFines();
    }

    document.addEventListener('visibilitychange', () => { if (!document.hidden) doRefresh(); });
    window.addEventListener('focus', doRefresh);
    setInterval(doRefresh, 30000);
}

document.addEventListener('DOMContentLoaded', function () {
    const searchEl = document.getElementById('mm-search');
    const confirmBtn = document.getElementById('mm-confirm-pay-btn');

    if (searchEl) {
        searchEl.addEventListener('input', function () {
            filterRows(this.value || '');
        });
    }

    if (confirmBtn) {
        confirmBtn.addEventListener('click', submitManualPayment);
    }

    const openPayBtn = document.getElementById('mm-open-pay-modal-btn');
    if (openPayBtn) {
        openPayBtn.addEventListener('click', function () {
            const detailsModalEl = document.getElementById('mmDetailsModal');
            const detailsModal = bootstrap.Modal.getInstance(detailsModalEl);
            if (detailsModal) detailsModal.hide();
            if (selectedVehicleId) {
                openPayModal(selectedVehicleId);
            }
        });
    }

    loadUnpaidFines();
    setupDashboardAutoRefresh();
});

function loadUnpaidFines() {
    const tbody = document.getElementById('mm-tbody');
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">Chargement...</td></tr>';
    }

    fetch('/api/vehicles/fines/all?paid=false')
        .then(function (r) {
            if (!r.ok) {
                throw new Error('Erreur de chargement');
            }
            return r.json();
        })
        .then(function (data) {
            mmAllFines = Array.isArray(data) ? data : [];
            mmAllFines.sort(function (a, b) {
                const dateA = a.issued_at ? new Date(a.issued_at) : new Date(0);
                const dateB = b.issued_at ? new Date(b.issued_at) : new Date(0);
                return dateB - dateA;
            });
            mmAllVehicles = groupFinesByVehicle(mmAllFines);
            mmFilteredVehicles = mmAllVehicles.slice();
            renderTable(mmFilteredVehicles);
            updateCount(mmFilteredVehicles.length, mmAllFines.length);
        })
        .catch(function () {
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center text-danger py-4">Erreur lors du chargement des amendes impayées.</td></tr>';
            }
            updateCount(0, 0);
        });
}

function groupFinesByVehicle(fines) {
    const groups = new Map();

    (fines || []).forEach(function (fine) {
        const key = String(fine.vehicle_id || fine.license_plate || fine.track_token || fine.id);
        if (!groups.has(key)) {
            groups.set(key, {
                vehicle_id: fine.vehicle_id,
                license_plate: fine.license_plate || '',
                owner_name: fine.owner_name || '',
                status: fine.status || null,
                total_amount: 0,
                count: 0,
                last_issued_at: null,
                is_qr_expired: fine.is_qr_expired || false,
                qr_code_expiry: fine.qr_code_expiry || null,
                fines: []
            });
        }

        const group = groups.get(key);
        group.total_amount += Number(fine.amount || 0);
        group.count += 1;
        group.fines.push(fine);
        // propagate vehicle status from any fine (all fines for same vehicle should share it)
        if (fine.status !== undefined && fine.status !== null) {
            group.status = fine.status;
        }
        
        // Update QR expiry status from any fine in the group (all same vehicle)
        if (fine.is_qr_expired !== undefined) {
            group.is_qr_expired = fine.is_qr_expired;
        }
        if (fine.qr_code_expiry !== undefined) {
            group.qr_code_expiry = fine.qr_code_expiry;
        }

        const candidateDate = fine.issued_at ? new Date(fine.issued_at) : null;
        if (candidateDate && (!group.last_issued_at || candidateDate > group.last_issued_at)) {
            group.last_issued_at = candidateDate;
        }
    });

    return Array.from(groups.values()).sort(function (a, b) {
        const dateA = a.last_issued_at ? a.last_issued_at.getTime() : 0;
        const dateB = b.last_issued_at ? b.last_issued_at.getTime() : 0;
        return dateB - dateA;
    });
}

function updateCount(vehicleCount, fineCount) {
    const badge = document.getElementById('mm-unpaid-count');
    if (badge) {
        badge.textContent = vehicleCount + ' véhicule(s) à traiter • ' + fineCount + ' amende(s)';
    }
}

function filterRows(query) {
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        mmFilteredVehicles = mmAllVehicles.slice();
    } else {
        mmFilteredVehicles = mmAllVehicles.filter(function (vehicle) {
            return (
                (vehicle.license_plate || '').toLowerCase().includes(q) ||
                (vehicle.owner_name || '').toLowerCase().includes(q) ||
                vehicle.fines.some(function (fine) {
                    return (
                        (fine.reason || '').toLowerCase().includes(q) ||
                        (fine.receipt_number || '').toLowerCase().includes(q) ||
                        (fine.issued_at_str || '').toLowerCase().includes(q)
                    );
                })
            );
        });
    }
    renderTable(mmFilteredVehicles);
    const fineCount = mmFilteredVehicles.reduce(function (acc, vehicle) { return acc + vehicle.fines.length; }, 0);
    updateCount(mmFilteredVehicles.length, fineCount);
}

function renderTable(items) {
    const tbody = document.getElementById('mm-tbody');
    if (!tbody) return;

    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">Aucun véhicule avec amende impayée.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(function (vehicle, idx) {
        const latestFine = vehicle.fines[0] || {};
        const statusBadge = getVehicleStatusBadge(vehicle.status, vehicle.is_qr_expired);
        let issuedDate = vehicle.last_issued_at ? vehicle.last_issued_at.toLocaleDateString('fr-FR') : '';
        if (!issuedDate && latestFine.issued_at) {
            try {
                issuedDate = new Date(latestFine.issued_at).toLocaleDateString('fr-FR');
            } catch (e) {
                issuedDate = latestFine.issued_at;
            }
        }

        // Disable pay button if QR is expired
        const payButtonDisabled = vehicle.is_qr_expired ? ' disabled' : '';
        const payButtonClass = vehicle.is_qr_expired ? 'btn-secondary' : 'btn-success';

        return '<tr>' +
            '<td>' + (idx + 1) + '</td>' +
            '<td>' + (vehicle.license_plate || '') + '</td>' +
            '<td><span class="badge bg-primary">' + vehicle.count + '</span></td>' +
            '<td>' + Math.round(vehicle.total_amount || 0) + ' KMF</td>' +
            '<td>' + (issuedDate || '-') + '</td>' +
                '<td>' + statusBadge + '</td>' +
            '<td class="d-flex gap-1 flex-wrap"><button class="btn btn-sm btn-outline-secondary" data-details-id="' + (vehicle.vehicle_id || vehicle.license_plate) + '"><i class="fas fa-eye me-1"></i>Détails</button><button class="btn btn-sm ' + payButtonClass + '" data-pay-id="' + (vehicle.vehicle_id || vehicle.license_plate) + '"' + payButtonDisabled + ' title="' + (vehicle.is_qr_expired ? 'QR code expiré - paiement impossible' : '') + '"><i class="fas fa-check me-1"></i>Accepter Paiement</button></td>' +
            '</tr>';
    }).join('');

    tbody.querySelectorAll('[data-details-id]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const vehicleId = this.getAttribute('data-details-id');
            openDetailsModal(vehicleId);
        });
    });

    tbody.querySelectorAll('[data-pay-id]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const vehicleId = this.getAttribute('data-pay-id');
            openPayModal(vehicleId);
        });
    });
}

function getVehicleStatusBadge(status, isQrExpired) {
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

    if (isQrExpired) {
        return '<span class="badge bg-danger">QR Expiré</span>';
    }

    return '<span class="badge bg-secondary">' + (status || 'Inconnu') + '</span>';
}

function openDetailsModal(vehicleId) {
    const vehicle = mmAllVehicles.find(function (item) { return String(item.vehicle_id || item.license_plate) === String(vehicleId); });
    if (!vehicle) return;

    selectedVehicleId = vehicleId;

    const title = document.getElementById('mm-details-title');
    const subtitle = document.getElementById('mm-details-subtitle');
    const tbody = document.getElementById('mm-details-tbody');
    if (title) title.textContent = 'Véhicule ' + (vehicle.license_plate || '');
    if (subtitle) subtitle.textContent = (vehicle.owner_name || '-') + ' • ' + vehicle.count + ' infraction(s) • ' + Math.round(vehicle.total_amount || 0) + ' KMF';

    if (tbody) {
        tbody.innerHTML = vehicle.fines.map(function (fine, index) {
            let issuedDate = fine.issued_at_str || '';
            if (!issuedDate && fine.issued_at) {
                try {
                    issuedDate = new Date(fine.issued_at).toLocaleDateString('fr-FR');
                } catch (e) {
                    issuedDate = fine.issued_at;
                }
            }

            return '<tr>' +
                '<td>' + (index + 1) + '</td>' +
                '<td>' + (fine.reason || '') + '</td>' +
                '<td>' + Math.round(fine.amount || 0) + ' KMF</td>' +
                '<td>' + (issuedDate || '-') + '</td>' +
                '</tr>';
        }).join('');
    }

    // Update pay button state based on QR expiry
    const payBtn = document.getElementById('mm-open-pay-modal-btn');
    if (payBtn) {
        if (vehicle.is_qr_expired) {
            payBtn.disabled = true;
            payBtn.classList.add('disabled');
            payBtn.title = 'QR code expiré - paiement impossible';
        } else {
            payBtn.disabled = false;
            payBtn.classList.remove('disabled');
            payBtn.title = '';
        }
    }

    const modal = new bootstrap.Modal(document.getElementById('mmDetailsModal'));
    modal.show();
}

function openPayModal(vehicleId) {
    selectedVehicleId = vehicleId;
    const vehicle = mmAllVehicles.find(function (item) { return String(item.vehicle_id || item.license_plate) === String(vehicleId); });
    
    // Check if QR is expired before opening payment modal
    if (vehicle && vehicle.is_qr_expired) {
        alert('Impossible de traiter le paiement : le code QR du véhicule est expiré. Veuillez renouveler le code QR.');
        return;
    }
    
    const text = document.getElementById('mm-pay-text');
    if (text && vehicle) {
        text.textContent = 'Confirmer le paiement groupé de ' + (vehicle.license_plate || '') + ' pour ' + vehicle.count + ' infraction(s) et ' + Math.round(vehicle.total_amount || 0) + ' KMF ?';
    }

    const modal = new bootstrap.Modal(document.getElementById('mmPayModal'));
    modal.show();
}

function submitManualPayment() {
    if (!selectedVehicleId) return;

    // Check if vehicle has expired QR code
    const vehicle = mmAllVehicles.find(function (item) { return String(item.vehicle_id || item.license_plate) === String(selectedVehicleId); });
    if (vehicle && vehicle.is_qr_expired) {
        alert('Impossible de traiter le paiement : le code QR du véhicule est expiré. Veuillez renouveler le code QR.');
        return;
    }

    const method = document.getElementById('mm-pay-method').value || 'mobile_money_manual';

    fetch('/api/vehicles/' + selectedVehicleId + '/fines/pay-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_method: method })
    })
        .then(function (r) {
            if (!r.ok) {
                return r.json().then(function (x) { throw new Error(x.error || 'Erreur de paiement'); });
            }
            return r.json();
        })
        .then(function (res) {
            const modalEl = document.getElementById('mmPayModal');
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();

            if (window.showSuccess) {
                window.showSuccess(res.message || 'Paiement groupé confirmé');
            } else {
                alert(res.message || 'Paiement groupé confirmé');
            }

            loadUnpaidFines();
        })
        .catch(function (err) {
            alert(err.message || 'Erreur lors de la confirmation du paiement');
        });
}
