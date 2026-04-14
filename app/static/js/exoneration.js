// exoneration.js
let exoneratedList = [];
let currentVehicle = null;

document.addEventListener('DOMContentLoaded', function() {
    loadExoneratedVehicles();
    
    // Save button
    document.getElementById('btn-save-exoneration').addEventListener('click', handleSaveExoneration);
    
    // Add button
    document.getElementById('btn-add-exoneration').addEventListener('click', function() {
        document.getElementById('exoneration-form').reset();
        currentVehicle = null;
        hideVehicleInfo();
    });
    
    // License plate input with debounce
    const licensePlateInput = document.getElementById('license-plate-input');
    let debounceTimer;
    licensePlateInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const licensePlate = this.value.trim();
            if (licensePlate.length >= 3) {
                searchVehicleByLicensePlate(licensePlate);
            } else {
                hideVehicleInfo();
            }
        }, 500);
    });
});

function loadExoneratedVehicles() {
    fetch('/api/vehicles/exonerated/list')
        .then(response => response.json())
        .then(data => {
            exoneratedList = data;
            renderExoneratedTable();
        })
        .catch(error => {
            console.error('Erreur:', error);
            showError('Erreur de chargement des véhicules exonérés');
        });
}

function searchVehicleByLicensePlate(licensePlate) {
    fetch(`/api/vehicles/query?q=${encodeURIComponent(licensePlate)}`)
        .then(response => response.json())
        .then(data => {
            // Find exact or close match
            const vehicle = data.find(v => 
                v.license_plate.toLowerCase() === licensePlate.toLowerCase()
            ) || data[0];
            
            if (vehicle) {
                // Check if already exonerated
                const isExonerated = exoneratedList.some(e => e.vehicle_id === vehicle.id);
                if (isExonerated) {
                    showVehicleError('Ce véhicule est déjà dans la liste d\'exonération');
                    currentVehicle = null;
                } else {
                    currentVehicle = vehicle;
                    showVehicleInfo(vehicle);
                }
            } else {
                showVehicleError('Aucun véhicule trouvé avec ce matricule');
                currentVehicle = null;
            }
        })
        .catch(error => {
            console.error('Erreur:', error);
            showVehicleError('Erreur de recherche du véhicule');
            currentVehicle = null;
        });
}

function showVehicleInfo(vehicle) {
    const infoDiv = document.getElementById('vehicle-info');
    const errorDiv = document.getElementById('vehicle-error');
    const detailsSpan = document.getElementById('vehicle-details');
    
    detailsSpan.textContent = `${vehicle.license_plate} - ${vehicle.owner_name} (${vehicle.vehicle_type})`;
    infoDiv.style.display = 'block';
    errorDiv.style.display = 'none';
}

function showVehicleError(message) {
    const infoDiv = document.getElementById('vehicle-info');
    const errorDiv = document.getElementById('vehicle-error');
    const errorSpan = document.getElementById('error-message');
    
    errorSpan.textContent = message;
    errorDiv.style.display = 'block';
    infoDiv.style.display = 'none';
}

function hideVehicleInfo() {
    document.getElementById('vehicle-info').style.display = 'none';
    document.getElementById('vehicle-error').style.display = 'none';
    currentVehicle = null;
}

function renderExoneratedTable() {
    const tbody = document.getElementById('exonerated-tbody');
    
    if (exoneratedList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Aucun véhicule exonéré</td></tr>';
        return;
    }
    
    tbody.innerHTML = exoneratedList.map((exo, index) => `
        <tr>
            <td>${index + 1}</td>
            <td><strong>${exo.license_plate || 'N/A'}</strong></td>
            <td>${exo.owner_name || 'N/A'}</td>
            <td>${exo.reason || 'N/A'}</td>
            <td>${exo.added_by || 'N/A'}</td>
            <td>${formatDate(exo.created_at_str)}</td>
            <td>
                <button class="btn btn-sm btn-info" onclick="showDetails(${exo.id})">
                    <i class="fas fa-eye"></i>
                </button>
                <button class="btn btn-sm btn-danger" onclick="removeExoneration(${exo.id}, '${exo.license_plate}')">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function handleSaveExoneration() {
    const form = document.getElementById('exoneration-form');
    const formData = new FormData(form);
    
    if (!currentVehicle) {
        alert('Veuillez saisir un matricule valide');
        return;
    }
    
    if (!formData.get('reason')) {
        alert('Veuillez sélectionner une raison');
        return;
    }
    
    const data = {
        vehicle_id: currentVehicle.id,
        reason: formData.get('reason'),
        notes: formData.get('notes') || ''
    };
    
    fetch('/api/vehicles/exonerated/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => Promise.reject(err));
        }
        return response.json();
    })
    .then(result => {
        showSuccess('Véhicule ajouté à la liste d\'exonération');
        bootstrap.Modal.getInstance(document.getElementById('exonerationModal')).hide();
        loadExoneratedVehicles();
    })
    .catch(error => {
        console.error('Erreur:', error);
        showError(error.error || 'Erreur lors de l\'ajout de l\'exonération');
    });
}

function removeExoneration(id, licensePlate) {
    if (!confirm(`Êtes-vous sûr de vouloir retirer le véhicule ${licensePlate} de la liste d'exonération ?`)) {
        return;
    }
    
    fetch(`/api/vehicles/exonerated/${id}`, {
        method: 'DELETE'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Erreur lors de la suppression');
        }
        return response.json();
    })
    .then(result => {
        showSuccess('Véhicule retiré de la liste d\'exonération');
        loadExoneratedVehicles();
    })
    .catch(error => {
        console.error('Erreur:', error);
        showError('Erreur lors de la suppression de l\'exonération');
    });
}

function showDetails(id) {
    const exo = exoneratedList.find(e => e.id === id);
    if (!exo) return;
    
    const content = `
        <div class="row">
            <div class="col-md-6">
                <p><strong>Immatriculation:</strong> ${exo.license_plate || 'N/A'}</p>
                <p><strong>Propriétaire:</strong> ${exo.owner_name || 'N/A'}</p>
                <p><strong>Raison:</strong> ${exo.reason || 'N/A'}</p>
            </div>
            <div class="col-md-6">
                <p><strong>Ajouté par:</strong> ${exo.added_by || 'N/A'}</p>
                <p><strong>Date d'ajout:</strong> ${formatDate(exo.created_at_str)}</p>
            </div>
            <div class="col-12 mt-3">
                <p><strong>Notes:</strong></p>
                <p class="text-muted">${exo.notes || 'Aucune note'}</p>
            </div>
        </div>
    `;
    
    document.getElementById('details-content').innerHTML = content;
    new bootstrap.Modal(document.getElementById('detailsModal')).show();
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    return dateStr;
}

function showSuccess(message) {
    // Simple alert for now - can be replaced with a better notification system
    alert(message);
}

function showError(message) {
    // Simple alert for now - can be replaced with a better notification system
    alert('Erreur: ' + message);
}
