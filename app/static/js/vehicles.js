var vehicleModalInstance = window.vehicleModalInstance || null;
window.vehicleModalInstance = vehicleModalInstance;
var vehiclesCache = window.vehiclesCache || [];
window.vehiclesCache = vehiclesCache;
var searchDebounceTimer = window.searchDebounceTimer || null;
window.searchDebounceTimer = searchDebounceTimer;
var KNOWN_VEHICLE_TYPES = window.KNOWN_VEHICLE_TYPES || ['voiture','taxi','moto','camion','minibus','ambulance','suv'];
window.KNOWN_VEHICLE_TYPES = KNOWN_VEHICLE_TYPES;
var KNOWN_USAGE_TYPES = window.KNOWN_USAGE_TYPES || ['Personnelle','Taxi','Transport public'];
window.KNOWN_USAGE_TYPES = KNOWN_USAGE_TYPES.concat(['Location','Véhicule de service','Véhicule utilitaire','Transport scolaire','Transport touristique','Auto-école']);

// Pagination variables
var currentVehiclesDisplayed = window.currentVehiclesDisplayed || [];
window.currentVehiclesDisplayed = currentVehiclesDisplayed;
var currentPageVehicles = window.currentPageVehicles || 1;
window.currentPageVehicles = currentPageVehicles;
var VEHICLES_PER_PAGE = window.VEHICLES_PER_PAGE || 20;
window.VEHICLES_PER_PAGE = VEHICLES_PER_PAGE;

function setupVehicleTypeToggle(){
    const selectEl = document.getElementById('vehicle_type_select');
    const otherEl = document.getElementById('vehicle_type_other');
    const hiddenEl = document.getElementById('vehicle_type');
    if(!selectEl) return;
    // set initial visibility
    if(selectEl.value === 'other'){
        if(otherEl) otherEl.classList.remove('d-none');
    } else {
        if(otherEl) otherEl.classList.add('d-none');
    }

    selectEl.addEventListener('change', function(){
        if(selectEl.value === 'other'){
            if(otherEl){ otherEl.classList.remove('d-none'); otherEl.required = true; }
            if(hiddenEl) hiddenEl.value = otherEl ? otherEl.value.trim() : '';
        } else {
            if(otherEl){ otherEl.classList.add('d-none'); otherEl.required = false; otherEl.value = ''; }
            if(hiddenEl) hiddenEl.value = selectEl.value;
        }
    });

    if(otherEl){
        otherEl.addEventListener('input', function(){
            if(selectEl.value === 'other' && hiddenEl){ hiddenEl.value = otherEl.value.trim(); }
        });
    }
}

function setupUsageTypeToggle(){
    const selectEl = document.getElementById('usage_type_select');
    const otherEl = document.getElementById('usage_type_other');
    const hiddenEl = document.getElementById('usage_type');
    if(!selectEl) return;
    // set initial visibility
    if(selectEl.value === 'autre'){
        if(otherEl) otherEl.classList.remove('d-none');
    } else {
        if(otherEl) otherEl.classList.add('d-none');
    }

    selectEl.addEventListener('change', function(){
        if(selectEl.value === 'autre'){
            if(otherEl){ otherEl.classList.remove('d-none'); otherEl.required = true; }
            if(hiddenEl) hiddenEl.value = otherEl ? otherEl.value.trim() : '';
        } else {
            if(otherEl){ otherEl.classList.add('d-none'); otherEl.required = false; otherEl.value = ''; }
            if(hiddenEl) hiddenEl.value = selectEl.value;
        }
    });

    if(otherEl){
        otherEl.addEventListener('input', function(){
            if(selectEl.value === 'autre' && hiddenEl){ hiddenEl.value = otherEl.value.trim(); }
        });
    }
}

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOMContentLoaded: vehicles.js loaded');
    
    // Only load the full vehicles table on the dedicated vehicles page
    // (the vehicles page includes a #btn-add-vehicle button). On the
    // dashboard we include this script only to reuse modal helpers, so
    // avoid replacing the dashboard table rows.
    const addBtn = document.getElementById('btn-add-vehicle');
    console.log('btn-add-vehicle found:', addBtn ? 'YES' : 'NO');
    
    if (addBtn) {
        // we're on the vehicles management page — load and bind add button
        console.log('Loading vehicles...');
        loadVehicles();
        
        // wire search input if present
        const searchInput = document.getElementById('vehicle-search');
        if (searchInput) {
            searchInput.addEventListener('input', function(e){
                const q = e.target.value || '';
                // debounce to avoid rapid re-renders
                if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
                searchDebounceTimer = setTimeout(()=>{
                    loadVehicles();
                }, 200);
            });
        }
        
        // wire status filter if present
        const statusFilter = document.getElementById('status-filter');
        if (statusFilter) {
            statusFilter.addEventListener('change', function() {
                loadVehicles();
            });
        }
        
        addBtn.addEventListener('click', function() {
            openVehicleModal();
        });
    }

    // always wire the vehicle-type select toggle if present (works on dashboard and vehicles pages)
    setupVehicleTypeToggle();

    // always wire the usage-type select toggle if present (works on dashboard and vehicles pages)
    setupUsageTypeToggle();

    const saveBtn = document.getElementById('save-vehicle-btn');
    if (saveBtn) saveBtn.addEventListener('click', saveVehicle);

    // Ensure we clean up modal when it is hidden (covers cancel/backdrop click)
    const modalEl = document.getElementById('vehicleModal');
    if (modalEl) {
        modalEl.addEventListener('hidden.bs.modal', function (event) {
            // cleanup resources after modal hidden
            cleanupModalResources();
        });
    }

    // If ?edit=<id> is present, open modal for editing that vehicle
    try{
        const params = new URLSearchParams(window.location.search);
        const editId = params.get('edit');
        if(editId){
            // fetch vehicle and open modal
            fetch(`/api/vehicles/${editId}`)
                .then(r => {
                    if(!r.ok) throw new Error('Véhicule non trouvé');
                    return r.json();
                })
                .then(v => {
                    // ensure table is loaded before opening modal
                    // open modal with vehicle data
                    openVehicleModal(v);
                    // remove edit param from URL without reloading
                    params.delete('edit');
                    const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
                    window.history.replaceState({}, document.title, newUrl);
                })
                .catch(err => {
                    console.error('Impossible d\'ouvrir l\'édition:', err);
                });
        }
    }catch(e){ console.error(e); }
});

function loadVehicles() {
    console.log('loadVehicles called');
    
    // Build query parameters based on current filter values
    const params = new URLSearchParams();
    
    // Get search query
    const searchInput = document.getElementById('vehicle-search');
    if (searchInput && searchInput.value.trim()) {
        params.append('q', searchInput.value.trim());
    }
    
    // Get status filter
    const statusFilter = document.getElementById('status-filter');
    if (statusFilter && statusFilter.value) {
        params.append('status', statusFilter.value);
    }
    
    const url = params.toString() ? `/api/vehicles/query?${params.toString()}` : '/api/vehicles/query';
    
    fetch(url, { credentials: 'same-origin' })
        .then(r => {
            console.log('Response status:', r.status);
            if (!r.ok) {
                console.error('Erreur HTTP:', r.status);
                throw new Error(`HTTP ${r.status}`);
            }
            return r.json();
        })
        .then(data => {
            console.log('Data received from API:', data);
            vehiclesCache = data || [];
            console.log('vehiclesCache updated with ' + vehiclesCache.length + ' vehicles');
            renderVehiclesTable(vehiclesCache);
        })
        .catch(err => {
            console.error('Erreur chargement véhicules:', err);
            const tbody = document.getElementById('vehicles-tbody');
            if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">Erreur lors du chargement. Vérifiez votre connexion.</td></tr>';
        });
}

function renderVehiclesTable(vehicles) {
    // Store the vehicles to display and reset to page 1
    currentVehiclesDisplayed = vehicles || [];
    currentPageVehicles = 1;
    displayVehiclesPage();
}

function displayVehiclesPage() {
    const vehicles = currentVehiclesDisplayed;
    const tbody = document.getElementById('vehicles-tbody');
    if (!tbody) {
        console.error('ERROR: #vehicles-tbody not found in DOM');
        return;
    }
    
    if (!vehicles || vehicles.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Aucun véhicule</td></tr>';
        updatePaginationInfo(0, 0, 0);
        return;
    }
    
    console.log('displayVehiclesPage: ' + vehicles.length + ' vehicles total, page ' + currentPageVehicles);
    
    // Calculate pagination
    const totalPages = Math.ceil(vehicles.length / VEHICLES_PER_PAGE);
    const startIdx = (currentPageVehicles - 1) * VEHICLES_PER_PAGE;
    const endIdx = Math.min(startIdx + VEHICLES_PER_PAGE, vehicles.length);
    const vehiclesOnPage = vehicles.slice(startIdx, endIdx);
    
    console.log('Displaying vehicles ' + startIdx + ' to ' + endIdx);
    
    // Render table rows
    tbody.innerHTML = vehiclesOnPage.map((v, i) => `
        <tr>
            <td>${startIdx + i + 1}</td>
            <td><strong>${v.license_plate}</strong></td>
            <td>${v.owner_name}</td>
            <td>${capitalizeFirst(v.vehicle_type)}</td>
            <td><span class="badge ${statusBadgeClass(v.status)}">${statusLabel(v.status)}</span></td>
            <td>${v.registration_date || ''}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" title="Détails" onclick="viewVehicle('${v.track_token}')"><i class="fas fa-eye"></i></button>
                <button class="btn btn-sm btn-outline-warning" title="Éditer" onclick="editVehicle(${v.id})"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" title="Supprimer" onclick="removeVehicle(${v.id})"><i class="fas fa-trash"></i></button>
            </td>
        </tr>
    `).join('');
    
    // Update pagination info
    updatePaginationInfo(startIdx + 1, endIdx, vehicles.length, currentPageVehicles, totalPages);
    updatePaginationButtons(currentPageVehicles, totalPages);
}

function updatePaginationInfo(start, end, total, currentPage, totalPages) {
    const startEl = document.getElementById('pagination-start');
    const endEl = document.getElementById('pagination-end');
    const totalEl = document.getElementById('pagination-total');
    const pageInfoEl = document.getElementById('page-info');
    
    if (startEl && endEl && totalEl) {
        startEl.textContent = total === 0 ? 0 : start;
        endEl.textContent = end;
        totalEl.textContent = total;
    }
    
    if (pageInfoEl && currentPage && totalPages) {
        pageInfoEl.textContent = `Page ${currentPage} sur ${totalPages}`;
    }
}

function updatePaginationButtons(currentPage, totalPages) {
    const prevBtn = document.querySelector('#pagination-controls li:first-child a');
    const nextBtn = document.querySelector('#pagination-controls li:last-child a');
    
    if (prevBtn) {
        if (currentPage <= 1) {
            prevBtn.parentElement.classList.add('disabled');
        } else {
            prevBtn.parentElement.classList.remove('disabled');
        }
    }
    
    if (nextBtn) {
        if (currentPage >= totalPages) {
            nextBtn.parentElement.classList.add('disabled');
        } else {
            nextBtn.parentElement.classList.remove('disabled');
        }
    }
}

function goToPreviousPage() {
    if (currentPageVehicles > 1) {
        currentPageVehicles--;
        displayVehiclesPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function goToNextPage() {
    const totalPages = Math.ceil(currentVehiclesDisplayed.length / VEHICLES_PER_PAGE);
    if (currentPageVehicles < totalPages) {
        currentPageVehicles++;
        displayVehiclesPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function filterAndRenderVehicles(query){
    if(!query){
        renderVehiclesTable(vehiclesCache);
        return;
    }
    const q = query.toLowerCase();
    const filtered = vehiclesCache.filter(v => {
        return (v.license_plate && v.license_plate.toLowerCase().includes(q)) ||
               (v.owner_name && v.owner_name.toLowerCase().includes(q)) ||
               (v.vehicle_type && v.vehicle_type.toLowerCase().includes(q)) ||
               (v.vin && v.vin.toLowerCase().includes(q));
    });
    renderVehiclesTable(filtered);
}

function openVehicleModal(vehicle) {
    // Reset form FIRST
    document.getElementById('vehicle-form').reset();
    document.getElementById('vehicle-id').value = '';
    
    // Update modal title with icon
    const modalTitle = document.getElementById('vehicleModalLabel');
    if(vehicle) {
        modalTitle.innerHTML = '<i class="fas fa-edit me-2"></i><span>Éditer le véhicule</span>';
    } else {
        modalTitle.innerHTML = '<i class="fas fa-car me-2"></i><span>Ajouter un véhicule</span>';
    }
    
    // ensure type controls are in known default state
    const selectEl = document.getElementById('vehicle_type_select');
    const otherEl = document.getElementById('vehicle_type_other');
    const hiddenEl = document.getElementById('vehicle_type');
    if(selectEl){ selectEl.value = KNOWN_VEHICLE_TYPES[0]; }
    if(otherEl){ otherEl.classList.add('d-none'); otherEl.value = ''; otherEl.required = false; }
    if(hiddenEl){ hiddenEl.value = ''; }

    // ensure usage type controls are in known default state
    const usageSelectEl = document.getElementById('usage_type_select');
    const usageOtherEl = document.getElementById('usage_type_other');
    const usageHiddenEl = document.getElementById('usage_type');
    if(usageSelectEl){ usageSelectEl.value = KNOWN_USAGE_TYPES[0]; }
    if(usageOtherEl){ usageOtherEl.classList.add('d-none'); usageOtherEl.value = ''; usageOtherEl.required = false; }
    if(usageHiddenEl){ usageHiddenEl.value = ''; }

    if (vehicle) {
        document.getElementById('vehicle-id').value = vehicle.id;
        document.getElementById('license_plate').value = vehicle.license_plate;
        document.getElementById('owner_name').value = vehicle.owner_name;
        document.getElementById('owner_phone').value = vehicle.owner_phone || '';
        // Fill owner_island with EXACT check after reset
        const islandEl = document.getElementById('owner_island');
        if(islandEl) { 
            islandEl.value = (vehicle.owner_island && vehicle.owner_island.trim()) ? vehicle.owner_island : '';
            console.log('Setting owner_island to:', islandEl.value, 'from vehicle:', vehicle.owner_island);
        }
        // populate vehicle type: if it's a known type use select, otherwise set 'other' and fill the free-text
        if(selectEl){
            const vt = (vehicle.vehicle_type || '').toString();
            if(KNOWN_VEHICLE_TYPES.includes(vt.toLowerCase())){
                selectEl.value = vt.toLowerCase();
                if(otherEl){ otherEl.classList.add('d-none'); otherEl.value = ''; otherEl.required = false; }
                if(hiddenEl) hiddenEl.value = vt.toLowerCase();
            } else {
                selectEl.value = 'other';
                if(otherEl){ otherEl.classList.remove('d-none'); otherEl.value = vt || ''; otherEl.required = true; }
                if(hiddenEl) hiddenEl.value = vt || '';
            }
        } else {
            if(hiddenEl) hiddenEl.value = vehicle.vehicle_type || '';
        }
        // populate usage type: if it's a known type use select, otherwise set 'autre' and fill the free-text
        if(usageSelectEl){
            const ut = (vehicle.usage_type || '').toString();
            if(KNOWN_USAGE_TYPES.includes(ut)){
                usageSelectEl.value = ut;
                if(usageOtherEl){ usageOtherEl.classList.add('d-none'); usageOtherEl.value = ''; usageOtherEl.required = false; }
                if(usageHiddenEl) usageHiddenEl.value = ut;
            } else {
                usageSelectEl.value = 'autre';
                if(usageOtherEl){ usageOtherEl.classList.remove('d-none'); usageOtherEl.value = ut || ''; usageOtherEl.required = true; }
                if(usageHiddenEl) usageHiddenEl.value = ut || '';
            }
        } else {
            if(usageHiddenEl) usageHiddenEl.value = vehicle.usage_type || '';
        }
        document.getElementById('color').value = vehicle.color || '';
        document.getElementById('status').value = vehicle.status || 'active';
        document.getElementById('notes').value = vehicle.notes || '';
        // new fields
        if(document.getElementById('make')) document.getElementById('make').value = vehicle.make || '';
        if(document.getElementById('model')) document.getElementById('model').value = vehicle.model || '';
        if(document.getElementById('year')) document.getElementById('year').value = vehicle.year || '';
        if(document.getElementById('vin')) document.getElementById('vin').value = vehicle.vin || '';
        if(document.getElementById('owner_address')) document.getElementById('owner_address').value = vehicle.owner_address || '';
        if(document.getElementById('registration_expiry')) document.getElementById('registration_expiry').value = vehicle.registration_expiry || '';
        if(document.getElementById('insurance_company')) document.getElementById('insurance_company').value = vehicle.insurance_company || '';
        if(document.getElementById('insurance_expiry')) document.getElementById('insurance_expiry').value = vehicle.insurance_expiry || '';
    }

    // initialize and show modal (store instance globally)
    vehicleModalInstance = new bootstrap.Modal(document.getElementById('vehicleModal'));
    vehicleModalInstance.show();
}

function saveVehicle() {
    const vid = document.getElementById('vehicle-id').value;
    // compute vehicle type from select/other controls
    const selectEl = document.getElementById('vehicle_type_select');
    const otherEl = document.getElementById('vehicle_type_other');
    const hiddenEl = document.getElementById('vehicle_type');
    let vehicleTypeValue = '';
    if(selectEl){
        if(selectEl.value === 'other') vehicleTypeValue = otherEl ? otherEl.value.trim() : (hiddenEl ? hiddenEl.value.trim() : '');
        else vehicleTypeValue = selectEl.value;
    } else if(hiddenEl){
        vehicleTypeValue = hiddenEl.value.trim();
    }

    // compute usage type from select/other controls
    const usageSelectEl = document.getElementById('usage_type_select');
    const usageOtherEl = document.getElementById('usage_type_other');
    const usageHiddenEl = document.getElementById('usage_type');
    let usageTypeValue = '';
    if(usageSelectEl){
        if(usageSelectEl.value === 'autre') usageTypeValue = usageOtherEl ? usageOtherEl.value.trim() : (usageHiddenEl ? usageHiddenEl.value.trim() : '');
        else usageTypeValue = usageSelectEl.value;
    } else if(usageHiddenEl){
        usageTypeValue = usageHiddenEl.value.trim();
    }

    const payload = {
        license_plate: document.getElementById('license_plate').value.trim(),
        owner_name: document.getElementById('owner_name').value.trim(),
        owner_phone: document.getElementById('owner_phone').value.trim(),
        owner_island: document.getElementById('owner_island') ? document.getElementById('owner_island').value : '',
        make: document.getElementById('make') ? document.getElementById('make').value.trim() : '',
        model: document.getElementById('model') ? document.getElementById('model').value.trim() : '',
        year: document.getElementById('year') ? document.getElementById('year').value.trim() : '',
        vin: document.getElementById('vin') ? document.getElementById('vin').value.trim() : '',
        vehicle_type: vehicleTypeValue,
        usage_type: usageTypeValue,
        color: document.getElementById('color').value.trim(),
        status: document.getElementById('status').value,
        notes: document.getElementById('notes').value.trim(),
        owner_address: document.getElementById('owner_address') ? document.getElementById('owner_address').value.trim() : '',
        registration_expiry: document.getElementById('registration_expiry') ? document.getElementById('registration_expiry').value : ''
    };

    // optional insurance company
    if(document.getElementById('insurance_company')){
        payload.insurance_company = document.getElementById('insurance_company').value.trim();
    }
    if(document.getElementById('insurance_expiry')){
        payload.insurance_expiry = document.getElementById('insurance_expiry').value || '';
    }

    if (!payload.license_plate || !payload.owner_name || !payload.vehicle_type) {
        alert('Veuillez remplir les champs requis');
        return;
    }

    if (vid) {
        // update
        fetch(`/api/vehicles/${vid}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) throw r;
            return r.json();
        }).then(() => {
            safeHideModal();
            loadVehicles();
        }).catch(async err => {
            const text = err.json ? await err.json() : {error: 'Erreur'};
            alert(text.error || 'Erreur lors de la mise à jour');
        });
    } else {
        // create
        fetch('/api/vehicles', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) throw r;
            return r.json();
        }).then((created) => {
            // created contains the new vehicle data
            safeHideModal();
            loadVehicles();
            try{ if(created && created.id) showQRCodeFor(created.id); }catch(e){}
        }).catch(async err => {
            const text = err.json ? await err.json() : {error: 'Erreur'};
            alert(text.error || 'Erreur lors de la création');
        });
    }
}

let currentQrUrl = null;
let currentLicensePlate = null;
let currentVehicleId = null;

function showQRCodeFor(id){
    currentVehicleId = id;
    // First fetch vehicle data to get license plate
    fetch(`/api/vehicles/${id}`)
        .then(r => r.json())
        .then(vehicle => {
            currentLicensePlate = vehicle.license_plate;
            // Update license plate display in modal
            const licensePlateDisplay = document.getElementById('license-plate-display');
            if(licensePlateDisplay) {
                licensePlateDisplay.textContent = vehicle.license_plate;
            }
            // Now fetch the QR code
            return fetch(`/api/vehicles/${id}/qrcode`);
        })
        .then(r => {
            if(!r.ok) throw new Error('Erreur génération QR');
            return r.blob();
        }).then(blob => {
            if(currentQrUrl) URL.revokeObjectURL(currentQrUrl);
            currentQrUrl = URL.createObjectURL(blob);
            const img = document.getElementById('qr-image');
            if(img) img.src = currentQrUrl;
            const qrModalEl = document.getElementById('qrModal');
            if(qrModalEl){
                const modal = new bootstrap.Modal(qrModalEl);
                modal.show();
                // cleanup when hidden
                qrModalEl.addEventListener('hidden.bs.modal', function(){
                    if(currentQrUrl){ URL.revokeObjectURL(currentQrUrl); currentQrUrl = null; }
                    const img = document.getElementById('qr-image'); if(img) img.src = '';
                }, {once:true});
            }
        }).catch(err => {
            console.error('Erreur affichage QR:', err);
        });
}

function printQRCode(){
    const img = document.getElementById('qr-image');
    if(!img || !img.src){
        alert('QR Code non disponible');
        return;
    }
    const printWindow = window.open('', '', 'height=500,width=500');
    if(printWindow){
        const licensePlateHtml = currentLicensePlate ? `<p style="font-size: 18px; font-weight: bold; margin-top: 10px; margin-bottom: 0; color: #333;">${currentLicensePlate}</p>` : '';
        printWindow.document.write(`
            <html>
                <head>
                    <title>QR Code de suivi</title>
                    <style>
                        body { display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; font-family: Arial, sans-serif; }
                        .qr-container { text-align: center; }
                        .qr-container img { max-width: 400px; height: auto; margin: 20px 0; }
                        .qr-container p { margin: 10px 0; color: #666; }
                    </style>
                </head>
                <body>
                    <div class="qr-container">
                        <img src="${img.src}" alt="QR Code" />
                        ${licensePlateHtml}
                    </div>
                </body>
            </html>
        `);
        printWindow.document.close();
        setTimeout(() => {
            printWindow.print();
        }, 250);
    }
}

function downloadQRCodePDF(){
    if(!currentVehicleId){
        alert('Véhicule non disponible');
        return;
    }
    const link = document.createElement('a');
    link.href = `/api/vehicles/${currentVehicleId}/qrcode/pdf`;
    link.download = `${currentLicensePlate || 'qrcode'}_qrcode.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Hide modal safely and remove any lingering backdrop/classes
 */
function safeHideModal(){
    try{
        if(vehicleModalInstance){
            vehicleModalInstance.hide();
            // dispose after short delay to allow hide animation
            setTimeout(()=>{
                try{
                    vehicleModalInstance.dispose();
                }catch(e){}
                vehicleModalInstance = null;
                cleanupModalResources();
            }, 250);
        } else {
            // fallback: try to hide via getInstance
            const inst = bootstrap.Modal.getInstance(document.getElementById('vehicleModal'));
            if(inst) inst.hide();
            cleanupModalResources();
        }
    }catch(e){
        console.error('Erreur lors de la fermeture du modal', e);
    }
}

function cleanupModalResources(){
    try{
        // dispose instance if exists
        try{ if(vehicleModalInstance) vehicleModalInstance.dispose(); }catch(e){}
        vehicleModalInstance = null;
        // remove any backdrop element left
        const backdrop = document.querySelector('.modal-backdrop');
        if(backdrop && backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
        // ensure body scroll is restored
        document.body.classList.remove('modal-open');
        document.body.style.paddingRight = '';
    }catch(e){
        console.error('Erreur during modal cleanup', e);
    }
}

function editVehicle(id) {
    fetch(`/api/vehicles/${id}`)
        .then(r => r.json())
        .then(v => openVehicleModal(v))
        .catch(err => console.error('Erreur get vehicle:', err));
}

// Ouvrir la page publique de suivi dans le même onglet
function viewVehicle(trackToken){
    if(!trackToken) return;
    const url = `/track/${trackToken}`;
    window.location.href = url;
}

function removeVehicle(id) {
    if (!confirm('Confirmer la suppression de ce véhicule ?')) return;
    fetch(`/api/vehicles/${id}`, {method: 'DELETE'})
        .then(r => r.json())
        .then(() => loadVehicles())
        .catch(err => console.error('Erreur suppression:', err));
}

function capitalizeFirst(s){ if(!s) return ''; return s.charAt(0).toUpperCase()+s.slice(1);} 
function statusBadgeClass(s){ if(s==='active') return 'bg-success'; if(s==='inactive') return 'bg-danger'; if(s==='suspended') return 'bg-warning text-dark'; return 'bg-secondary'; }
function statusLabel(s){ if(s==='active') return 'Actif'; if(s==='inactive') return 'Inactif'; if(s==='suspended') return 'Suspendu'; return s; }
