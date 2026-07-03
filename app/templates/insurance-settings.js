/**
 * Insurance Settings Management
 */

let insurancesCache = [];
let isLoadingInsurances = false;
let lastInsurancesLoadTime = 0;
const INSURANCE_CACHE_TIMEOUT = 30000; // Cache for 30 seconds

document.addEventListener('DOMContentLoaded', function() {
    console.log('Insurance settings script loaded');
    console.log('Current user role:', window.currentUserRole);
    console.log('Current user country:', window.currentUserCountry);
    
    // Pre-fill island for judiciaire/policier users
    const islandInput = document.getElementById('insurance_island_input');
    if (islandInput && window.currentUserRole && ['judiciaire', 'policier'].includes(window.currentUserRole)) {
        if (window.currentUserCountry) {
            islandInput.value = window.currentUserCountry;
            islandInput.disabled = true; // Disable for judiciaire/policier users (auto-filled)
        }
    }
    
    const settingsModal = document.getElementById('settingsModal');
    if (settingsModal) {
        settingsModal.addEventListener('show.bs.modal', function() {
            console.log('Settings modal opened');
            loadInsurances();
        });
    }
});

function loadInsurances() {
    const now = Date.now();
    
    // If cache is fresh and not expired, reuse it
    if (insurancesCache.length > 0 && (now - lastInsurancesLoadTime) < INSURANCE_CACHE_TIMEOUT) {
        console.log('Using cached insurances');
        renderInsurancesTable();
        updateInsuranceSelect();
        return Promise.resolve(insurancesCache);
    }
    
    // If already loading, return the existing promise
    if (isLoadingInsurances) {
        console.log('Insurance load already in progress, skipping duplicate request');
        return Promise.resolve(insurancesCache);
    }
    
    console.log('Loading insurances...');
    isLoadingInsurances = true;
    
    return fetch('/api/vehicles/insurances', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to load insurances');
        return r.json();
    })
    .then(data => {
        insurancesCache = data.insurances || [];
        lastInsurancesLoadTime = Date.now();
        console.log('Loaded ' + insurancesCache.length + ' insurances');
        renderInsurancesTable();
        updateInsuranceSelect();
        return insurancesCache;
    })
    .catch(err => {
        console.error('Error loading insurances:', err);
        const tbody = document.getElementById('insurances-tbody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">Erreur lors du chargement</td></tr>';
        return [];
    })
    .finally(() => {
        isLoadingInsurances = false;
    });
}

function renderInsurancesTable() {
    const tbody = document.getElementById('insurances-tbody');
    if (!tbody) return;
    
    if (insurancesCache.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Aucune compagnie d\'assurance</td></tr>';
        return;
    }
    
    const isAdmin = window.currentUserRole === 'administrateur';
    const isJudiciaire = ['judiciaire', 'policier'].includes(window.currentUserRole);
    
    tbody.innerHTML = insurancesCache.map(ins => `
        <tr>
            <td><strong>${ins.company_name}</strong></td>
            <td>${ins.phone || '-'}</td>
            <td>${ins.island || '-'}</td>
            <td>${ins.address || '-'}</td>
            <td>
                ${(isAdmin || (isJudiciaire && ins.island === window.currentUserCountry)) ? `
                    <button class="btn btn-sm btn-outline-warning" onclick="editInsurance(${ins.id})" title="Éditer">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteInsurance(${ins.id})" title="Supprimer">
                        <i class="fas fa-trash"></i>
                    </button>
                ` : '<span class="text-muted small">Lecture seule</span>'}
            </td>
        </tr>
    `).join('');
}

function addInsurance() {
    const name = document.getElementById('insurance_name_input').value.trim();
    const phone = document.getElementById('insurance_phone_input').value.trim();
    let island = document.getElementById('insurance_island_input').value;
    const address = document.getElementById('insurance_address_input').value.trim();
    
    // For judiciaire/policier users, force the island to their country
    if (window.currentUserRole && ['judiciaire', 'policier'].includes(window.currentUserRole) && window.currentUserCountry) {
        island = window.currentUserCountry;
    }
    
    if (!name) {
        alert('Veuillez entrer le nom de la compagnie');
        return;
    }
    
    if (!island || island.trim() === '') {
        alert('Veuillez sélectionner une île');
        return;
    }
    
    const payload = {
        company_name: name,
        phone: phone,
        island: island,
        address: address
    };
    
    fetch('/api/vehicles/insurances', {
        method: 'POST',
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
        console.log('Insurance added:', data);
        console.log('Insurance data:', data.insurance);
        // Clear inputs
        document.getElementById('insurance_name_input').value = '';
        document.getElementById('insurance_phone_input').value = '';
        document.getElementById('insurance_address_input').value = '';
        // Reset island if not locked
        const islandInput = document.getElementById('insurance_island_input');
        if (!islandInput.disabled) {
            islandInput.value = '';
        }
        // Reload insurances
        loadInsurances();
    })
    .catch(err => {
        console.error('Error adding insurance:', err);
        alert(err.error || 'Erreur lors de l\'ajout');
    });
}

function deleteInsurance(id) {
    if (!confirm('Êtes-vous sûr de vouloir supprimer cette compagnie d\'assurance ?')) return;
    
    fetch(`/api/vehicles/insurances/${id}`, {
        method: 'DELETE',
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) return r.json().then(e => { throw e; });
        return r.json();
    })
    .then(() => {
        console.log('Insurance deleted');
        loadInsurances();
    })
    .catch(err => {
        console.error('Error deleting insurance:', err);
        alert('Erreur lors de la suppression');
    });
}

function editInsurance(id) {
    const insurance = insurancesCache.find(i => i.id === id);
    if (!insurance) return;
    
    document.getElementById('insurance_name_input').value = insurance.company_name;
    document.getElementById('insurance_phone_input').value = insurance.phone || '';
    document.getElementById('insurance_island_input').value = insurance.island || '';
    document.getElementById('insurance_address_input').value = insurance.address || '';
    
    // Show update button instead of add
    const addBtn = document.querySelector('button[onclick="addInsurance()"]');
    if (addBtn) {
        addBtn.onclick = function() { updateInsurance(id); };
        addBtn.innerHTML = '<i class="fas fa-save me-1"></i>Mettre à jour';
    }
}

function updateInsurance(id) {
    const name = document.getElementById('insurance_name_input').value.trim();
    const phone = document.getElementById('insurance_phone_input').value.trim();
    let island = document.getElementById('insurance_island_input').value;
    const address = document.getElementById('insurance_address_input').value.trim();
    
    // For judiciaire/policier users, force the island to their country
    if (window.currentUserRole && ['judiciaire', 'policier'].includes(window.currentUserRole) && window.currentUserCountry) {
        island = window.currentUserCountry;
    }
    
    if (!name) {
        alert('Veuillez entrer le nom de la compagnie');
        return;
    }
    
    const payload = {
        company_name: name,
        phone: phone,
        island: island,
        address: address
    };
    
    fetch(`/api/vehicles/insurances/${id}`, {
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
        console.log('Insurance updated:', data);
        // Clear inputs
        document.getElementById('insurance_name_input').value = '';
        document.getElementById('insurance_phone_input').value = '';
        document.getElementById('insurance_address_input').value = '';
        // Reset button
        const addBtn = document.querySelector('button[onclick*="updateInsurance"]');
        if (addBtn) {
            addBtn.onclick = function() { addInsurance(); };
            addBtn.innerHTML = '<i class="fas fa-plus me-1"></i>Ajouter';
        }
        // Reload insurances
        loadInsurances();
    })
    .catch(err => {
        console.error('Error updating insurance:', err);
        alert(err.error || 'Erreur lors de la mise à jour');
    });
}

function updateInsuranceSelect(filterByIsland = null) {
    // Update the insurance select in the vehicle form
    const selectEl = document.getElementById('insurance_company');
    if (!selectEl) return;
    
    console.log('updateInsuranceSelect called with filterByIsland:', filterByIsland);
    console.log('insurancesCache length:', insurancesCache.length);
    
    // If cache is empty, load insurances first
    if (insurancesCache.length === 0) {
        console.log('Insurance cache is empty, loading...');
        return loadInsurances().then(() => {
            console.log('Insurances loaded, now populating select');
            // After loading, populate the select
            populateInsuranceSelect(selectEl, filterByIsland);
        });
    }
    
    // Cache is already populated
    populateInsuranceSelect(selectEl, filterByIsland);
}

function clearInsuranceSelect() {
    // Clear the insurance select - only show placeholder and "Autre" option
    const selectEl = document.getElementById('insurance_company');
    if (!selectEl) return;
    
    console.log('Clearing insurance select');
    selectEl.innerHTML = '<option value="">-- Sélectionner une compagnie --</option>';
    
    // Add "Autre" option
    const otherOption = document.createElement('option');
    otherOption.value = 'Autre';
    otherOption.textContent = '➕ Autre...';
    selectEl.appendChild(otherOption);
}

function populateInsuranceSelect(selectEl, filterByIsland = null) {
    // Save current value
    const currentValue = selectEl.value;
    
    // Clear options except placeholder
    selectEl.innerHTML = '<option value="">-- Sélectionner une compagnie --</option>';
    
    // Filter insurances by island if specified
    let filteredInsurances = insurancesCache;
    if (filterByIsland && filterByIsland.trim() !== '') {
        console.log('Filtering insurances by island:', filterByIsland);
        // Show insurances that have this island OR have no island defined (for backward compatibility)
        filteredInsurances = insurancesCache.filter(ins => {
            // If insurance has an island, it must match the selected island
            // If insurance has NO island, also show it (backward compatibility)
            return !ins.island || ins.island.trim() === '' || ins.island === filterByIsland;
        });
        console.log('Filtered insurances count:', filteredInsurances.length);
        console.log('Filtered insurances:', filteredInsurances);
    } else {
        // If no island filter, show all insurances
        console.log('No island filter, showing all insurances');
        console.log('All insurances count:', filteredInsurances.length);
    }
    
    // Add filtered insurances to the select
    if (filteredInsurances.length === 0 && filterByIsland && filterByIsland.trim() !== '') {
        const option = document.createElement('option');
        option.disabled = true;
        option.textContent = 'Aucune assurance pour cette île';
        selectEl.appendChild(option);
    } else {
        filteredInsurances.forEach(ins => {
            const option = document.createElement('option');
            option.value = ins.company_name;
            // Show island in parentheses if available
            const label = ins.island ? `${ins.company_name} (${ins.island})` : ins.company_name;
            option.textContent = label;
            selectEl.appendChild(option);
        });
    }
    
    // Add "Autre" option
    const otherOption = document.createElement('option');
    otherOption.value = 'Autre';
    otherOption.textContent = '➕ Autre...';
    selectEl.appendChild(otherOption);
    
    // Restore previous value if it still exists
    selectEl.value = currentValue;
    console.log('updateInsuranceSelect completed. Total options:', selectEl.options.length);
}
