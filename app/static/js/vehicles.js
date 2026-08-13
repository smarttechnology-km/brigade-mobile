var vehicleModalInstance = window.vehicleModalInstance || null;
window.vehicleModalInstance = vehicleModalInstance;

// Active tab for status filtering
var activeVehicleTab = 'all';

window.generateLicensePlate = async function() {
    const btn = document.getElementById('btn-gen-plate');
    const input = document.getElementById('license_plate');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }

    const digits = () => Math.floor(Math.random() * 10);
    const letter = () => 'ABCDEFGHJKLMNPQRSTUVWXYZ'[Math.floor(Math.random() * 23)];
    const FORBIDDEN = ['71','72','73'];
    const gen = () => {
        let suffix;
        do { suffix = '' + digits() + digits(); } while (FORBIDDEN.includes(suffix));
        return '' + digits() + digits() + digits() + letter() + letter() + suffix;
    };

    try {
        for (let attempt = 0; attempt < 10; attempt++) {
            const plate = gen();
            const res = await fetch('/api/vehicles/check-plate?plate=' + plate, { credentials: 'same-origin' });
            if (!res.ok) break;
            const data = await res.json();
            if (!data.exists) {
                input.value = plate;
                break;
            }
        }
    } catch(e) { /* silently ignore network error */ }

    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-magic"></i>'; }
};
var vehiclesCache = window.vehiclesCache || [];
window.vehiclesCache = vehiclesCache;
var searchDebounceTimer = window.searchDebounceTimer || null;
window.searchDebounceTimer = searchDebounceTimer;
var KNOWN_VEHICLE_TYPES = window.KNOWN_VEHICLE_TYPES || ['voiture','taxi','moto','camion','minibus','ambulance','suv'];
window.KNOWN_VEHICLE_TYPES = KNOWN_VEHICLE_TYPES;
var KNOWN_FUEL_TYPES = window.KNOWN_FUEL_TYPES || ['Essence','Gazoil','Electric'];
window.KNOWN_FUEL_TYPES = KNOWN_FUEL_TYPES;
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

function setupFuelTypeToggle(){
    const selectEl = document.getElementById('fuel_type_select');
    const otherEl = document.getElementById('fuel_type_other');
    const hiddenEl = document.getElementById('fuel_type');
    if(!selectEl) return;

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

function setupInsuranceCompanyToggle(){
    const selectEl = document.getElementById('insurance_company');
    const otherEl = document.getElementById('insurance_company_other');
    if(!selectEl) return;
    // set initial visibility
    if(selectEl.value === 'Autre'){
        if(otherEl) otherEl.classList.remove('d-none');
    } else {
        if(otherEl) otherEl.classList.add('d-none');
    }

    selectEl.addEventListener('change', function(){
        if(selectEl.value === 'Autre'){
            if(otherEl){ otherEl.classList.remove('d-none'); otherEl.required = true; }
        } else {
            if(otherEl){ otherEl.classList.add('d-none'); otherEl.required = false; otherEl.value = ''; }
        }
    });

    if(otherEl){
        otherEl.addEventListener('input', function(){
            if(selectEl.value === 'Autre' && selectEl){ selectEl.value = otherEl.value.trim(); }
        });
    }
}

function setupIslandInsuranceFilter(){
    const islandEl = document.getElementById('owner_island');
    if(!islandEl) return;

    islandEl.addEventListener('change', function(){
        const selectedIsland = islandEl.value;
        console.log('Island changed to:', selectedIsland);
        // Update insurance select with filtering by island
        if (typeof updateInsuranceSelect === 'function') {
            console.log('Calling updateInsuranceSelect with:', selectedIsland);
            updateInsuranceSelect(selectedIsland);
        } else {
            console.error('updateInsuranceSelect is not defined');
        }
        // Also refresh work zone options when island changes
        _refreshWorkZoneOptions();
    });
}

var WORK_ZONE_BY_ISLAND = {
    'Grande Comore': [
        'Centre-ville (Moroni)',
        'Mitsamiouli',
        'Mbéni',
        'Foumbouni',
        'Sima',
        'Ntsoudjini',
        'Autre région'
    ],
    'Anjouan': [
        'Centre-ville (Mutsamudu)',
        'Domoni',
        'Ouani',
        'Sima',
        'Koni',
        'Bambao',
        'Autre région'
    ],
    'Moheli': [
        'Centre-ville (Fomboni)',
        'Nioumachoua',
        'Djando',
        'Miringoni',
        'Ouallah',
        'Autre région'
    ]
};

function _refreshWorkZoneOptions(currentZone){
    var islandEl = document.getElementById('owner_island');
    var zoneEl = document.getElementById('work_zone');
    var otherEl = document.getElementById('work_zone_other');
    if(!zoneEl) return;
    var island = islandEl ? islandEl.value : '';
    zoneEl.innerHTML = '<option value="">-- Sélectionner une zone --</option>';
    var allZones = [];
    if(island && WORK_ZONE_BY_ISLAND[island]){
        // Specific island selected: flat list
        var zones = WORK_ZONE_BY_ISLAND[island];
        zones.forEach(function(z){
            var opt = document.createElement('option');
            opt.value = z; opt.textContent = z;
            zoneEl.appendChild(opt);
        });
        allZones = zones;
    } else {
        // No island: grouped by island with <optgroup>
        ['Grande Comore','Anjouan','Moheli'].forEach(function(ile){
            var grp = document.createElement('optgroup');
            grp.label = '🏝️ ' + ile;
            WORK_ZONE_BY_ISLAND[ile].forEach(function(z){
                var opt = document.createElement('option');
                opt.value = z; opt.textContent = z;
                grp.appendChild(opt);
                allZones.push(z);
            });
            zoneEl.appendChild(grp);
        });
    }
    // restore saved zone
    if(currentZone && currentZone !== ''){
        if(allZones.indexOf(currentZone) !== -1){
            zoneEl.value = currentZone;
            if(otherEl){ otherEl.classList.add('d-none'); otherEl.value = ''; }
        } else {
            zoneEl.value = 'Autre région';
            if(otherEl){ otherEl.classList.remove('d-none'); otherEl.value = currentZone; }
        }
    } else {
        if(otherEl){ otherEl.classList.add('d-none'); otherEl.value = ''; }
    }
}

function setupWorkZoneToggle(){
    var usageEl = document.getElementById('usage_type_select');
    var insuranceEl = document.getElementById('insurance_company');
    var groupEl = document.getElementById('work_zone_group');
    if(!usageEl || !groupEl) return;

    function _isTaxiLike(){
        return usageEl.value === 'Taxi' || usageEl.value === 'Transport public';
    }
    function _hasInsurance(){
        if(!insuranceEl) return false;
        var val = insuranceEl.value;
        return val && val !== '';
    }

    function _update(){
        if(_isTaxiLike() && _hasInsurance()){
            _refreshWorkZoneOptions();
            groupEl.classList.remove('d-none');
        } else {
            groupEl.classList.add('d-none');
            var zoneEl = document.getElementById('work_zone');
            var otherEl = document.getElementById('work_zone_other');
            if(zoneEl) zoneEl.value = '';
            if(otherEl){ otherEl.classList.add('d-none'); otherEl.value = ''; }
        }
    }

    usageEl.addEventListener('change', _update);
    if(insuranceEl) insuranceEl.addEventListener('change', _update);

    // Show/hide free-text input when "Autre région" is selected
    var zoneEl = document.getElementById('work_zone');
    if(zoneEl){
        zoneEl.addEventListener('change', function(){
            var otherEl = document.getElementById('work_zone_other');
            if(!otherEl) return;
            if(zoneEl.value === 'Autre région'){
                otherEl.classList.remove('d-none');
                otherEl.focus();
            } else {
                otherEl.classList.add('d-none');
                otherEl.value = '';
            }
        });
    }

    _update();
}

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOMContentLoaded: vehicles.js loaded');
    
    // Load insurances early so filtering by island works in vehicle modal
    if (typeof loadInsurances === 'function') {
        loadInsurances();
    }
    
    // Only load the full vehicles table on the dedicated vehicles page
    // (the vehicles page includes a #vehicles-tbody element). On the
    // dashboard we include this script only to reuse modal helpers, so
    // avoid replacing the dashboard table rows.
    const vehiclesTbody = document.getElementById('vehicles-tbody');
    const paginationControls = document.getElementById('pagination-controls');

    if (vehiclesTbody && paginationControls) {
        // we're on the vehicles management page — load table
        loadVehicles();

        // ── Real-time sync via lightweight last-update polling ──
        let _lastKey = null;
        function _checkVehicleUpdates() {
            if (document.hidden) return;
            fetch('/api/vehicles/last-update', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null)
                .then(d => {
                    if (!d) return;
                    const key = d.last_update + '|' + d.total;
                    if (_lastKey === null) { _lastKey = key; return; }
                    if (key !== _lastKey) { _lastKey = key; loadVehicles(); }
                })
                .catch(() => {});
        }
        setInterval(_checkVehicleUpdates, 5000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) _checkVehicleUpdates(); });
        
        // Load insurances for the vehicle form
        if (typeof loadInsurances === 'function') {
            loadInsurances();
        }
        
        // wire search input if present
        const searchInput = document.getElementById('vehicle-search');
        if (searchInput) {
            searchInput.addEventListener('input', function(e){
                const q = e.target.value || '';
                // debounce to avoid rapid re-renders
                if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
                searchDebounceTimer = setTimeout(()=>{
                    filterAndRenderVehicles(q);
                }, 200);
            });
        }
        
        // wire country filter if present
        const countryFilter = document.getElementById('country-filter');
        if (countryFilter) {
            countryFilter.addEventListener('change', function() {
                loadVehicles();
            });
        }
        
        const addBtn = document.getElementById('btn-add-vehicle');
        if (addBtn) {
            addBtn.addEventListener('click', function() {
                openVehicleModal();
            });
        }

        // Wire status tabs
        document.querySelectorAll('#vehicle-status-tabs .nav-link').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('#vehicle-status-tabs .nav-link').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                activeVehicleTab = this.getAttribute('data-tab');
                applyTabFilter();
            });
        });
    }

    // Duplicate plate notice
    const plateInput = document.getElementById('license_plate');
    const plateDupNotice = document.getElementById('plate-duplicate-notice');
    if (plateInput && plateDupNotice) {
        let _plateCheckTimer = null;
        function checkPlateDuplicate() {
            const val = plateInput.value.trim();
            if (!val) { plateDupNotice.classList.add('d-none'); return; }
            fetch('/api/vehicles/check-plate?plate=' + encodeURIComponent(val), { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : null)
                .then(d => {
                    if (d && d.exists) plateDupNotice.classList.remove('d-none');
                    else plateDupNotice.classList.add('d-none');
                })
                .catch(() => plateDupNotice.classList.add('d-none'));
        }
        plateInput.addEventListener('blur', checkPlateDuplicate);
        plateInput.addEventListener('input', function() {
            clearTimeout(_plateCheckTimer);
            plateDupNotice.classList.add('d-none');
            _plateCheckTimer = setTimeout(checkPlateDuplicate, 600);
        });
    }

    // Auto-fill / notify owner name from phone lookup
    const phoneInput = document.getElementById('owner_phone');
    if (phoneInput) {
        let phoneTimer = null;
        function clearPhoneHint() {
            const hint = document.getElementById('owner-name-hint');
            if (hint) hint.classList.add('d-none');
        }
        phoneInput.addEventListener('input', function() {
            clearTimeout(phoneTimer);
            const phone = this.value.trim();
            if (phone.length < 6) { clearPhoneHint(); return; }
            phoneTimer = setTimeout(async function() {
                const vid = document.getElementById('vehicle-id').value;
                if (vid) return; // edition mode — skip
                try {
                    const res = await fetch('/api/vehicles/lookup-phone?phone=' + encodeURIComponent(phone), { credentials: 'same-origin' });
                    if (!res.ok) return;
                    const data = await res.json();
                    const nameInput = document.getElementById('owner_name');
                    const hint     = document.getElementById('owner-name-hint');
                    const hintText = document.getElementById('owner-name-hint-text');
                    if (data.found) {
                        if (nameInput && !nameInput.value.trim()) {
                            nameInput.value = data.owner_name;
                        }
                        // Auto-fill island without triggering the change event (to avoid clearing the plate)
                        const islandEl = document.getElementById('owner_island');
                        if (islandEl && !islandEl.value && data.owner_island) {
                            islandEl.value = data.owner_island;
                        }
                        const addressEl = document.getElementById('owner_address');
                        if (addressEl && !addressEl.value.trim() && data.owner_address) {
                            addressEl.value = data.owner_address;
                        }
                        const profEl = document.getElementById('cg_profession_proprietaire');
                        if (profEl && !profEl.value.trim() && data.profession) {
                            profEl.value = data.profession;
                        }
                        if (hint && hintText) {
                            hintText.textContent = 'Numéro associé à : ' + data.owner_name;
                            hint.classList.remove('d-none');
                        }
                    } else {
                        clearPhoneHint();
                    }
                } catch(e) {}
            }, 500);
        });
    }

    // always wire the vehicle-type select toggle if present (works on dashboard and vehicles pages)
    setupVehicleTypeToggle();

    // always wire the fuel-type select toggle if present (works on dashboard and vehicles pages)
    setupFuelTypeToggle();

    // always wire the usage-type select toggle if present (works on dashboard and vehicles pages)
    setupUsageTypeToggle();

    // always wire the insurance-company select toggle if present (works on dashboard and vehicles pages)
    setupInsuranceCompanyToggle();

    // Wire island select to filter insurances
    setupIslandInsuranceFilter();

    // Wire work zone visibility to usage type
    setupWorkZoneToggle();

    const saveBtn = document.getElementById('save-vehicle-btn');
    if (saveBtn) saveBtn.addEventListener('click', saveVehicle);

    // Ensure we clean up modal when it is hidden (covers cancel/backdrop click)
    const modalEl = document.getElementById('vehicleModal');
    if (modalEl) {
        // Clean up AFTER modal is completely hidden
        modalEl.addEventListener('hidden.bs.modal', function (event) {
            // Final cleanup resources after modal hidden
            cleanupModalResources();
            // Reset form for next use
            const vehicleForm = document.getElementById('vehicle-form');
            if (vehicleForm) vehicleForm.reset();
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
    
    // Get country filter
    const countryFilter = document.getElementById('country-filter');
    if (countryFilter && countryFilter.value) {
        params.append('country', countryFilter.value);
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

function updateTabCounts(all) {
    const set = (id, n) => { const el = document.getElementById(id); if (el) el.textContent = n; };
    set('tab-count-all',       all.length);
    set('tab-count-active',    all.filter(v => !v.qr_pending_approval && v.status === 'active').length);
    set('tab-count-inactive',  all.filter(v => !v.qr_pending_approval && v.status === 'inactive').length);
    set('tab-count-suspended', all.filter(v => !v.qr_pending_approval && v.status === 'suspended').length);
    set('tab-count-pending',   all.filter(v => v.qr_pending_approval).length);
}

function applyTabFilter() {
    const all = vehiclesCache || [];
    let filtered;
    if (activeVehicleTab === 'pending') {
        filtered = all.filter(v => v.qr_pending_approval);
    } else if (activeVehicleTab === 'active') {
        filtered = all.filter(v => !v.qr_pending_approval && v.status === 'active');
    } else if (activeVehicleTab === 'inactive') {
        filtered = all.filter(v => !v.qr_pending_approval && v.status === 'inactive');
    } else if (activeVehicleTab === 'suspended') {
        filtered = all.filter(v => !v.qr_pending_approval && v.status === 'suspended');
    } else {
        filtered = all;
    }
    currentVehiclesDisplayed = filtered;
    currentPageVehicles = 1;
    displayVehiclesPage();
}

function renderVehiclesTable(vehicles) {
    updateTabCounts(vehicles || []);
    applyTabFilter();
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
            <td>
              ${v.qr_pending_approval
                ? '<span class="badge bg-warning text-dark"><i class="fas fa-clock me-1"></i>En attente QR</span>'
                : `<span class="badge ${statusBadgeClass(v.status)}">${statusLabel(v.status)}</span>`}
            </td>
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
    // update counts on the full filtered set, then apply tab
    updateTabCounts(filtered);
    const tab = activeVehicleTab;
    let tabFiltered;
    if (tab === 'pending') tabFiltered = filtered.filter(v => v.qr_pending_approval);
    else if (tab === 'active') tabFiltered = filtered.filter(v => !v.qr_pending_approval && v.status === 'active');
    else if (tab === 'inactive') tabFiltered = filtered.filter(v => !v.qr_pending_approval && v.status === 'inactive');
    else if (tab === 'suspended') tabFiltered = filtered.filter(v => !v.qr_pending_approval && v.status === 'suspended');
    else tabFiltered = filtered;
    currentVehiclesDisplayed = tabFiltered;
    currentPageVehicles = 1;
    displayVehiclesPage();
}

function _setSaveBlocked(blocked) {
    const saveBtn = document.getElementById('save-vehicle-btn');
    const msg = document.getElementById('save-vehicle-blocked-msg');
    if (saveBtn) {
        saveBtn.disabled = blocked;
        saveBtn.classList.toggle('btn-primary', !blocked);
        saveBtn.classList.toggle('btn-secondary', blocked);
    }
    if (msg) msg.classList.toggle('d-none', !blocked);
}

function openVehicleModal(vehicle) {
    // Reset form FIRST
    document.getElementById('vehicle-form').reset();
    document.getElementById('vehicle-id').value = '';
    _autoFilledPlate = null;
    _plateAutoLocked = false;
    _setPlateAutoLocked(false);
    const _hint = document.getElementById('owner-name-hint');
    if (_hint) _hint.classList.add('d-none');
    const _plateDup = document.getElementById('plate-duplicate-notice');
    if (_plateDup) _plateDup.classList.add('d-none');
    const _vinHint = document.getElementById('vin-plate-hint');
    if (_vinHint) _vinHint.classList.add('d-none');
    const _finesSection = document.getElementById('vehicle-fines-section');
    if (_finesSection) _finesSection.classList.add('d-none');
    _setSaveBlocked(false);
    
    // Update modal title with icon
    const modalTitle = document.getElementById('vehicleModalLabel');
    const genBtn = document.getElementById('btn-gen-plate');
    // CG extra section: always visible, but badge/alert only shown on creation
    const cgSection        = document.getElementById('cg-extra-section');
    const cgPendingBadge   = document.getElementById('cg-pending-badge');
    const cgPendingAlert   = document.getElementById('cg-pending-alert');
    const _fieldVignette   = document.getElementById('field-vignette-expiry');
    const _fieldEmission   = document.getElementById('field-cg-date-emission');
    const _sectionAssurance = document.getElementById('section-assurance');
    if(vehicle) {
        modalTitle.innerHTML = '<i class="fas fa-edit me-2"></i><span>Éditer le véhicule</span>';
        if(genBtn) genBtn.style.display = 'none';
        if(cgSection)      cgSection.classList.remove('d-none');
        if(cgPendingBadge) cgPendingBadge.style.display = 'none';
        if(cgPendingAlert) cgPendingAlert.style.display = 'none';
        if(_fieldVignette)    _fieldVignette.style.display = '';
        if(_fieldEmission)    _fieldEmission.style.display = '';
        if(_sectionAssurance) _sectionAssurance.style.display = '';
    } else {
        modalTitle.innerHTML = '<i class="fas fa-car me-2"></i><span>Ajouter un véhicule</span>';
        if(genBtn) genBtn.style.display = '';
        if(cgSection)      cgSection.classList.remove('d-none');
        if(cgPendingBadge) cgPendingBadge.style.display = '';
        if(cgPendingAlert) cgPendingAlert.style.display = '';
        if(_fieldVignette)    _fieldVignette.style.display = 'none';
        if(_fieldEmission)    _fieldEmission.style.display = 'none';
        if(_sectionAssurance) _sectionAssurance.style.display = 'none';

        // Pre-select island and suggest plate for directeur_regional (or any user with a fixed country)
        var _preIsland = window.currentUserCountry || '';
        if (_preIsland) {
            var _islandSel = document.getElementById('owner_island');
            if (_islandSel) _islandSel.value = _preIsland;
        }
        // Suggest plate based on pre-selected island (runs after DOM update)
        setTimeout(function() {
            var _island = (document.getElementById('owner_island') || {}).value || '';
            if (_island && typeof window._suggestPlateForIsland === 'function') {
                window._suggestPlateForIsland(_island);
            }
        }, 0);
    }
    
    // ensure type controls are in known default state
    const selectEl = document.getElementById('vehicle_type_select');
    const otherEl = document.getElementById('vehicle_type_other');
    const hiddenEl = document.getElementById('vehicle_type');
    if(selectEl){ selectEl.value = KNOWN_VEHICLE_TYPES[0]; }
    if(otherEl){ otherEl.classList.add('d-none'); otherEl.value = ''; otherEl.required = false; }
    if(hiddenEl){ hiddenEl.value = ''; }

    // ensure fuel type controls are in known default state
    const fuelSelectEl = document.getElementById('fuel_type_select');
    const fuelOtherEl = document.getElementById('fuel_type_other');
    const fuelHiddenEl = document.getElementById('fuel_type');
    if(fuelSelectEl){ fuelSelectEl.value = KNOWN_FUEL_TYPES[0]; }
    if(fuelOtherEl){ fuelOtherEl.classList.add('d-none'); fuelOtherEl.value = ''; fuelOtherEl.required = false; }
    if(fuelHiddenEl){ fuelHiddenEl.value = ''; }

    // ensure usage type controls are in known default state
    const usageSelectEl = document.getElementById('usage_type_select');
    const usageOtherEl = document.getElementById('usage_type_other');
    const usageHiddenEl = document.getElementById('usage_type');
    if(usageSelectEl){ usageSelectEl.value = KNOWN_USAGE_TYPES[0]; }
    if(usageOtherEl){ usageOtherEl.classList.add('d-none'); usageOtherEl.value = ''; usageOtherEl.required = false; }
    if(usageHiddenEl){ usageHiddenEl.value = ''; }

    // ensure insurance company controls are in known default state
    const insuranceSelectEl = document.getElementById('insurance_company');
    const insuranceOtherEl = document.getElementById('insurance_company_other');
    if(insuranceSelectEl){ insuranceSelectEl.value = ''; }
    if(insuranceOtherEl){ insuranceOtherEl.classList.add('d-none'); insuranceOtherEl.value = ''; insuranceOtherEl.required = false; }

    // Load insurances first, then update select
    if (typeof loadInsurances === 'function') {
        loadInsurances().then(() => {
            // After insurances are loaded, update the select (no filter for new vehicles)
            if (typeof updateInsuranceSelect === 'function') {
                if (vehicle) {
                    // If editing, filter by selected island
                    const islandEl = document.getElementById('owner_island');
                    const selectedIsland = (islandEl && islandEl.value) ? islandEl.value : '';
                    updateInsuranceSelect(selectedIsland);
                } else {
                    // If adding new, keep select empty until island is selected
                    clearInsuranceSelect();
                }
            }
        });
    }

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

            // populate fuel type: if it's a known type use select, otherwise set 'other' and fill the free-text
            const fuelSelectEl = document.getElementById('fuel_type_select');
            const fuelOtherEl = document.getElementById('fuel_type_other');
            const fuelHiddenEl = document.getElementById('fuel_type');
            if(fuelSelectEl){
                const ft = (vehicle.fuel_type || '').toString().trim();
                if(ft === '') {
                    fuelSelectEl.value = KNOWN_FUEL_TYPES[0];
                    if(fuelOtherEl){ fuelOtherEl.classList.add('d-none'); fuelOtherEl.value = ''; fuelOtherEl.required = false; }
                    if(fuelHiddenEl) fuelHiddenEl.value = KNOWN_FUEL_TYPES[0];
                } else if(KNOWN_FUEL_TYPES.includes(ft)){
                    fuelSelectEl.value = ft;
                    if(fuelOtherEl){ fuelOtherEl.classList.add('d-none'); fuelOtherEl.value = ''; fuelOtherEl.required = false; }
                    if(fuelHiddenEl) fuelHiddenEl.value = ft;
                } else {
                    fuelSelectEl.value = 'other';
                    if(fuelOtherEl){ fuelOtherEl.classList.remove('d-none'); fuelOtherEl.value = ft; fuelOtherEl.required = true; }
                    if(fuelHiddenEl) fuelHiddenEl.value = ft;
                }
            } else if(fuelHiddenEl){
                fuelHiddenEl.value = vehicle.fuel_type || '';
            }
        // populate insurance company: if it's a known company use select, otherwise set 'Autre' and fill the free-text
        if(insuranceSelectEl){
            const ic = (vehicle.insurance_company || '').toString().trim();
            // Get known insurance companies from cache (if available, otherwise empty list)
            const knownInsuranceCompanies = typeof insurancesCache !== 'undefined' ? insurancesCache.map(i => i.company_name) : [];
            if(ic === '') {
                insuranceSelectEl.value = '';
                if(insuranceOtherEl){ insuranceOtherEl.classList.add('d-none'); insuranceOtherEl.value = ''; insuranceOtherEl.required = false; }
            } else if(knownInsuranceCompanies.includes(ic)){
                insuranceSelectEl.value = ic;
                if(insuranceOtherEl){ insuranceOtherEl.classList.add('d-none'); insuranceOtherEl.value = ''; insuranceOtherEl.required = false; }
            } else {
                insuranceSelectEl.value = 'Autre';
                if(insuranceOtherEl){ insuranceOtherEl.classList.remove('d-none'); insuranceOtherEl.value = ic || ''; insuranceOtherEl.required = true; }
            }
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
        if(document.getElementById('vignette_expiry')) document.getElementById('vignette_expiry').value = vehicle.vignette_expiry || vehicle.registration_expiry || '';
        if(document.getElementById('insurance_expiry')) document.getElementById('insurance_expiry').value = vehicle.insurance_expiry || '';
        if(document.getElementById('fiscal_class')) document.getElementById('fiscal_class').value = vehicle.fiscal_class || '';
        if(document.getElementById('cv_class')) document.getElementById('cv_class').value = vehicle.cv_class || '';
        // Populate work zone: show if Taxi/Transport public + insurance set, OR if a value already exists (set by insurance)
        var workZoneGroup = document.getElementById('work_zone_group');
        var workZoneEl = document.getElementById('work_zone');
        var workZoneOtherEl = document.getElementById('work_zone_other');
        var ut2 = (vehicle.usage_type || '').toString();
        var hasIns = !!(vehicle.insurance_company && vehicle.insurance_company.trim() !== '');
        var hasZone = !!(vehicle.work_zone && vehicle.work_zone.trim() !== '');
        if(workZoneGroup && workZoneEl){
            if(((ut2 === 'Taxi' || ut2 === 'Transport public') && hasIns) || hasZone){
                _refreshWorkZoneOptions(vehicle.work_zone || '');
                workZoneGroup.classList.remove('d-none');
            } else {
                workZoneGroup.classList.add('d-none');
                workZoneEl.value = '';
                if(workZoneOtherEl){ workZoneOtherEl.classList.add('d-none'); workZoneOtherEl.value = ''; }
            }
        }

        // Afficher la plaque sous le champ VIN
        const vinHint = document.getElementById('vin-plate-hint');
        const vinPlateVal = document.getElementById('vin-plate-value');
        if(vinHint && vinPlateVal && vehicle.license_plate) {
            vinPlateVal.textContent = vehicle.license_plate;
            vinHint.classList.remove('d-none');
        } else if(vinHint) {
            vinHint.classList.add('d-none');
        }

        // Populate CarteGrise extra fields
        const cg = vehicle.carte_grise || {};
        const _cgSet = (id, val) => { const el = document.getElementById(id); if(el) el.value = val || ''; };
        _cgSet('cg_carrosserie',           cg.carrosserie);
        _cgSet('cg_places_assises',        cg.places_assises);
        _cgSet('cg_poids_total_autorise',  cg.poids_total_autorise);
        _cgSet('cg_poids_a_vide',          cg.poids_a_vide);
        _cgSet('cg_charge_utile_ptc',      cg.charge_utile_ptc);
        _cgSet('cg_profession_proprietaire', cg.profession_proprietaire);
        _cgSet('cg_date_emission',         cg.date_emission);
        _cgSet('cg_observation',           cg.observation);

        // Afficher uniquement les amendes non payées
        const finesSection = document.getElementById('vehicle-fines-section');
        const finesList = document.getElementById('vehicle-fines-list');
        const finesLink = document.getElementById('vehicle-fines-link');
        const unpaidFines = (vehicle.fines || []).filter(f => !f.paid);
        if(finesSection && finesList) {
            if(unpaidFines.length > 0) {
                finesSection.classList.remove('d-none');
                finesList.innerHTML = unpaidFines.map(f => {
                    const date = f.issued_at ? f.issued_at.substring(0,10) : '';
                    return `<div class="d-flex align-items-center justify-content-between border rounded px-3 py-2 mb-2 bg-light">
                        <div>
                            <span class="fw-semibold">${f.fine_type || f.description || 'Amende'}</span>
                            <span class="badge bg-danger ms-1">Non payée</span>
                            <div class="text-muted small">${date} — ${f.amount ? Number(f.amount).toLocaleString() + ' KMF' : ''}</div>
                        </div>
                        <a href="/fines?q=${encodeURIComponent(vehicle.license_plate)}" class="btn btn-sm btn-outline-danger ms-2" target="_blank">
                            <i class="fas fa-external-link-alt me-1"></i>Voir
                        </a>
                    </div>`;
                }).join('');
                if(finesLink) finesLink.href = `/fines?q=${encodeURIComponent(vehicle.license_plate)}&paid=false`;
                _setSaveBlocked(true);
            } else {
                finesSection.classList.add('d-none');
                _setSaveBlocked(false);
            }
        }
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

    // compute insurance company from select/other controls
    const insuranceSelectEl = document.getElementById('insurance_company');
    const insuranceOtherEl = document.getElementById('insurance_company_other');
    let insuranceCompanyValue = '';
    if(insuranceSelectEl){
        if(insuranceSelectEl.value === 'Autre') insuranceCompanyValue = insuranceOtherEl ? insuranceOtherEl.value.trim() : '';
        else insuranceCompanyValue = insuranceSelectEl.value;
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
        fuel_type: (function(){
            const fuelSelectEl = document.getElementById('fuel_type_select');
            const fuelOtherEl = document.getElementById('fuel_type_other');
            const fuelHiddenEl = document.getElementById('fuel_type');
            if(fuelSelectEl){
                if(fuelSelectEl.value === 'other') return fuelOtherEl ? fuelOtherEl.value.trim() : (fuelHiddenEl ? fuelHiddenEl.value.trim() : '');
                return fuelSelectEl.value;
            }
            return fuelHiddenEl ? fuelHiddenEl.value.trim() : '';
        })(),
        usage_type: usageTypeValue,
        color: document.getElementById('color').value.trim(),
        status: document.getElementById('status').value,
        notes: document.getElementById('notes').value.trim(),
        owner_address: document.getElementById('owner_address') ? document.getElementById('owner_address').value.trim() : '',
        vignette_expiry: document.getElementById('vignette_expiry') ? document.getElementById('vignette_expiry').value : '',
        insurance_company: insuranceCompanyValue,
        fiscal_class: document.getElementById('fiscal_class') ? document.getElementById('fiscal_class').value : '',
        cv_class: document.getElementById('cv_class') ? document.getElementById('cv_class').value : '',
        work_zone: (function(){
            var grp = document.getElementById('work_zone_group');
            if (!grp || grp.classList.contains('d-none')) return undefined;
            var wz = document.getElementById('work_zone');
            var wzOther = document.getElementById('work_zone_other');
            if(!wz) return undefined;
            if(wz.value === 'Autre région') return wzOther ? wzOther.value.trim() : '';
            return wz.value;
        })()
    };

    if(document.getElementById('insurance_expiry')){
        payload.insurance_expiry = document.getElementById('insurance_expiry').value || '';
    }

    const _cgGet = (id) => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    const cgPayload = {
        carrosserie:             _cgGet('cg_carrosserie'),
        places_assises:          _cgGet('cg_places_assises'),
        poids_total_autorise:    _cgGet('cg_poids_total_autorise'),
        poids_a_vide:            _cgGet('cg_poids_a_vide'),
        charge_utile_ptc:        _cgGet('cg_charge_utile_ptc'),
        profession_proprietaire: _cgGet('cg_profession_proprietaire'),
        date_emission:           document.getElementById('cg_date_emission') ? document.getElementById('cg_date_emission').value : '',
        observation:             _cgGet('cg_observation'),
    };

    // Include CG fields in the main payload so the PUT handler saves them atomically
    Object.assign(payload, cgPayload);

    if (!vid) {
        payload.pending_approval = true;
    }

    if (!payload.license_plate || !payload.owner_name || !payload.owner_phone || !payload.vehicle_type) {
        alert('Veuillez remplir les champs requis, y compris le numéro de téléphone');
        return;
    }

    function saveCgData(vehicleId) {
        return fetch(`/api/vehicles/${vehicleId}/save-cg`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(cgPayload)
        }).catch(() => {});
    }

    if (vid) {
        // update
        fetch(`/api/vehicles/${vid}`, {
            method: 'PUT',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(async r => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(data.error || `Erreur ${r.status}`);
            return data;
        }).then(() => {
            saveCgData(vid);
            safeHideModal();
            loadVehicles();
        }).catch(err => {
            alert(err.message || 'Erreur lors de la mise à jour');
        });
    } else {
        // create
        fetch('/api/vehicles', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(async r => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(data.error || `Erreur ${r.status}`);
            return data;
        }).then(data => {
            const newId = data.vehicle ? data.vehicle.id : (data.id || null);
            if (newId) saveCgData(newId);
            safeHideModal();
            loadVehicles();
        }).catch(err => {
            alert(err.message || 'Erreur lors de la création');
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
            const qrBtn = document.getElementById('download-qr-btn');
            if(qrBtn) qrBtn.href = `/api/vehicles/${id}/qrcode/pdf`;
            const sheetBtn = document.getElementById('download-sheet-btn');
            if(sheetBtn) sheetBtn.href = `/api/vehicles/${id}/sheet.pdf`;
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
        
        // ensure body scroll is restored completely
        document.body.classList.remove('modal-open');
        document.body.style.paddingRight = '';
        document.body.style.overflow = '';
        
        // also check for and remove any remaining modal-open classes
        document.querySelectorAll('.modal-open').forEach(el => {
            el.classList.remove('modal-open');
        });
        
        // restore overflow on html element if needed
        document.documentElement.style.overflow = '';
        
        // Force scroll to be re-enabled
        document.body.style.touchAction = 'auto';
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
        .then(async r => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                throw new Error(data.error || 'Impossible de supprimer le véhicule');
            }
            return data;
        })
        .then(() => loadVehicles())
        .catch(err => {
            console.error('Erreur suppression:', err);
            alert(err.message || 'Impossible de supprimer le véhicule');
        });
}

function capitalizeFirst(s){ if(!s) return ''; return s.charAt(0).toUpperCase()+s.slice(1);}
function statusBadgeClass(s){ if(s==='active') return 'bg-success'; if(s==='inactive') return 'bg-danger'; if(s==='suspended') return 'bg-warning text-dark'; return 'bg-secondary'; }
function statusLabel(s){ if(s==='active') return 'Actif'; if(s==='inactive') return 'Inactif'; if(s==='suspended') return 'Suspendu'; return s; }

// Lookup VIN en live dans le modal d'édition
(function(){
    let _vinTimer = null;
    document.addEventListener('DOMContentLoaded', function(){
        const vinInput = document.getElementById('vin');
        const vinHint = document.getElementById('vin-plate-hint');
        const vinPlateVal = document.getElementById('vin-plate-value');
        if(!vinInput || !vinHint || !vinPlateVal) return;

        vinInput.addEventListener('input', function(){
            clearTimeout(_vinTimer);
            const val = this.value.trim();
            if(!val) {
                vinHint.classList.add('d-none');
                const s = document.getElementById('vehicle-fines-section');
                if(s) s.classList.add('d-none');
                _setSaveBlocked(false);
                return;
            }
            _vinTimer = setTimeout(function(){
                fetch('/api/vehicles/lookup-vin?vin=' + encodeURIComponent(val))
                    .then(r => r.json())
                    .then(d => {
                        const v = d.vehicle;
                        if(v) {
                            vinPlateVal.textContent = v.license_plate + (v.owner_name ? ' — ' + v.owner_name : '');
                            vinHint.classList.remove('d-none');
                            // Mettre à jour la section amendes pour ce véhicule
                            const finesSection = document.getElementById('vehicle-fines-section');
                            const finesList = document.getElementById('vehicle-fines-list');
                            const finesLink = document.getElementById('vehicle-fines-link');
                            const unpaid = (v.fines || []).filter(f => !f.paid);
                            if(finesSection && finesList) {
                                if(unpaid.length > 0) {
                                    finesSection.classList.remove('d-none');
                                    finesList.innerHTML = unpaid.map(f => {
                                        const date = f.issued_at ? f.issued_at.substring(0,10) : '';
                                        return `<div class="d-flex align-items-center justify-content-between border rounded px-3 py-2 mb-2 bg-light">
                                            <div>
                                                <span class="fw-semibold">${f.fine_type || f.description || 'Amende'}</span>
                                                <span class="badge bg-danger ms-1">Non payée</span>
                                                <div class="text-muted small">${date} — ${f.amount ? Number(f.amount).toLocaleString() + ' KMF' : ''}</div>
                                            </div>
                                            <a href="/fines?q=${encodeURIComponent(v.license_plate)}&paid=false" class="btn btn-sm btn-outline-danger ms-2" target="_blank">
                                                <i class="fas fa-external-link-alt me-1"></i>Voir
                                            </a>
                                        </div>`;
                                    }).join('');
                                    if(finesLink) finesLink.href = `/fines?q=${encodeURIComponent(v.license_plate)}&paid=false`;
                                    _setSaveBlocked(true);
                                } else {
                                    finesSection.classList.add('d-none');
                                    _setSaveBlocked(false);
                                }
                            }
                        } else {
                            vinHint.classList.add('d-none');
                            const s = document.getElementById('vehicle-fines-section');
                            if(s) s.classList.add('d-none');
                            _setSaveBlocked(false);
                        }
                    })
                    .catch(() => {
                        vinHint.classList.add('d-none');
                        const s = document.getElementById('vehicle-fines-section');
                        if(s) s.classList.add('d-none');
                        _setSaveBlocked(false);
                    });
            }, 400);
        });
    });
})();

// ── Plate Settings ────────────────────────────────────────────────

var _plateSettings = {};

var _ISLAND_KEY_MAP = {
    'gc': 'Grande Comore',
    'an': 'Anjouan',
    'mo': 'Moheli'
};

function _updatePlatePreview(key) {
    var island = _ISLAND_KEY_MAP[key];
    var suffix = {'Grande Comore':'73','Anjouan':'71','Moheli':'72'}[island] || '';
    var num = parseInt(document.getElementById('ps-number-' + key)?.value || 1);
    var l1 = document.getElementById('ps-letter1-' + key)?.value || 'A';
    var l2 = document.getElementById('ps-letter2-' + key)?.value || 'A';
    var el = document.querySelector('.ps-preview-' + key);
    if (!el) return;
    var enabled = document.getElementById('ps-enabled-' + key)?.checked;
    if (!enabled) { el.textContent = '—'; return; }
    el.textContent = String(num).padStart(3,'0') + l1 + l2 + suffix;
}

function _loadPlateSettingsIntoModal(data) {
    Object.keys(_ISLAND_KEY_MAP).forEach(function(key) {
        var island = _ISLAND_KEY_MAP[key];
        var s = data[island];
        if (!s) return;
        var enabledEl  = document.getElementById('ps-enabled-' + key);
        var numberEl   = document.getElementById('ps-number-' + key);
        var letter1El  = document.getElementById('ps-letter1-' + key);
        var letter2El  = document.getElementById('ps-letter2-' + key);
        if (enabledEl)  enabledEl.checked = !!s.enabled;
        if (numberEl)   numberEl.value = s.current_number || 1;
        if (letter1El)  letter1El.value = s.principal_letter || 'A';
        if (letter2El)  letter2El.value = s.current_second_letter || 'A';
        _updatePlatePreview(key);

        // wire live preview
        [numberEl, letter1El, letter2El, enabledEl].forEach(function(el) {
            if (el && !el._platePreviewWired) {
                el._platePreviewWired = true;
                el.addEventListener('change', function() { _updatePlatePreview(key); });
                el.addEventListener('input',  function() { _updatePlatePreview(key); });
            }
        });
    });
}

window.savePlateSettings = function(key, island) {
    var enabledEl = document.getElementById('ps-enabled-' + key);
    var numberEl  = document.getElementById('ps-number-' + key);
    var l1El      = document.getElementById('ps-letter1-' + key);
    var l2El      = document.getElementById('ps-letter2-' + key);
    var msgEl     = document.getElementById('ps-save-msg');

    var payload = {
        enabled:               enabledEl?.checked || false,
        current_number:        parseInt(numberEl?.value || 1),
        principal_letter:      (l1El?.value || 'A').toUpperCase(),
        current_second_letter: (l2El?.value || 'A').toUpperCase(),
    };

    fetch('/api/vehicles/plate-settings/' + encodeURIComponent(island), {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.success) {
            if (d.settings) _plateSettings[island] = d.settings;
            _updatePlatePreview(key);
            if (msgEl) {
                msgEl.className = 'alert alert-success mt-3';
                msgEl.textContent = 'Paramètres enregistrés pour ' + island + '.';
                setTimeout(function() { msgEl.className = 'alert d-none mt-3'; }, 3000);
            }
        } else {
            if (msgEl) {
                msgEl.className = 'alert alert-danger mt-3';
                msgEl.textContent = d.error || 'Erreur lors de la sauvegarde.';
            }
        }
    })
    .catch(function() {
        if (msgEl) {
            msgEl.className = 'alert alert-danger mt-3';
            msgEl.textContent = 'Erreur réseau.';
        }
    });
};

// Load settings when the modal opens; hide tabs the current user can't manage
(function() {
    var modalEl = document.getElementById('plateSettingsModal');
    if (!modalEl) return;

    var _ISLAND_BY_KEY = {'gc':'Grande Comore','an':'Anjouan','mo':'Moheli'};

    function _restrictTabs() {
        var isDR = window.currentUserDgrtrType === 'directeur_regional';
        if (!isDR) return; // admin sees all tabs
        var userIsland = window.currentUserCountry || '';
        Object.keys(_ISLAND_BY_KEY).forEach(function(key) {
            var tabBtn  = document.getElementById('ps-' + key + '-tab');
            var tabPane = document.getElementById('ps-' + key);
            if (!tabBtn) return;
            if (_ISLAND_BY_KEY[key] === userIsland) {
                tabBtn.classList.add('active');
                if (tabPane) { tabPane.classList.add('show', 'active'); }
            } else {
                tabBtn.style.display = 'none';
                if (tabPane) { tabPane.classList.remove('show', 'active'); }
            }
        });
    }

    modalEl.addEventListener('show.bs.modal', function() {
        _restrictTabs();
        fetch('/api/vehicles/plate-settings', { credentials: 'same-origin' })
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(data) {
                if (!data) return;
                _plateSettings = data;
                _loadPlateSettingsIntoModal(data);
            })
            .catch(function() {});
    });
})();

// Auto-fill plate when island is selected in add-vehicle modal
var _autoFilledPlate = null;
var _plateAutoLocked = false;

function _setPlateAutoLocked(locked) {
    _plateAutoLocked = locked;
    var plateInput = document.getElementById('license_plate');
    var btn        = document.getElementById('btn-gen-plate');
    var icon       = document.getElementById('btn-gen-plate-icon');
    if (!plateInput || !btn) return;
    if (locked) {
        plateInput.setAttribute('readonly', 'readonly');
        plateInput.style.backgroundColor = '';
        btn.title = 'Modifier l\'immatriculation';
        btn.classList.remove('btn-outline-secondary', 'btn-outline-warning');
        btn.classList.add('btn-outline-warning');
        if (icon) { icon.className = 'fas fa-lock'; }
    } else {
        plateInput.removeAttribute('readonly');
        if (_autoFilledPlate) {
            // suggest restore button
            btn.title = 'Restaurer la suggestion automatique';
            btn.classList.remove('btn-outline-secondary', 'btn-outline-warning');
            btn.classList.add('btn-outline-secondary');
            if (icon) { icon.className = 'fas fa-redo'; }
        } else {
            // no suggestion active — random generator
            btn.title = 'Générer une immatriculation unique';
            btn.classList.remove('btn-outline-secondary', 'btn-outline-warning');
            btn.classList.add('btn-outline-secondary');
            if (icon) { icon.className = 'fas fa-magic'; }
        }
    }
}

window.handleGenPlateBtn = function() {
    if (_plateAutoLocked) {
        // Unlock so user can edit manually
        _setPlateAutoLocked(false);
        var plateInput = document.getElementById('license_plate');
        if (plateInput) plateInput.focus();
    } else if (_autoFilledPlate) {
        // Restore the suggestion and re-lock
        var plateInput = document.getElementById('license_plate');
        if (plateInput) plateInput.value = _autoFilledPlate;
        _setPlateAutoLocked(true);
        var notice = document.getElementById('plate-duplicate-notice');
        if (notice) notice.classList.add('d-none');
    } else {
        // No suggestion active — behave as random generator
        generateLicensePlate();
    }
};

window._suggestPlateForIsland = function(island) {
    if (!island) return;
    fetch('/api/vehicles/next-plate?island=' + encodeURIComponent(island), { credentials: 'same-origin' })
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(d) {
            var plateInput = document.getElementById('license_plate');
            var vid = document.getElementById('vehicle-id');
            if (!plateInput || (vid && vid.value)) return; // skip for edit mode
            if (d && d.plate) {
                if (!plateInput.value || plateInput.value === _autoFilledPlate) {
                    plateInput.value = d.plate;
                    _autoFilledPlate = d.plate;
                    _setPlateAutoLocked(true);
                    var notice = document.getElementById('plate-duplicate-notice');
                    if (notice) notice.classList.add('d-none');
                }
            } else {
                // Auto mode off or no plate available — unlock
                _autoFilledPlate = null;
                _setPlateAutoLocked(false);
            }
        })
        .catch(function() {});
};

(function() {
    var islandSel = document.getElementById('owner_island');
    if (!islandSel) return;
    islandSel.addEventListener('change', function() {
        var vid = document.getElementById('vehicle-id');
        if (vid && vid.value) return; // don't interfere with edit mode
        var plateInput = document.getElementById('license_plate');
        var wasLocked = _plateAutoLocked;
        _autoFilledPlate = null;
        _setPlateAutoLocked(false);
        // Only clear the plate if it was auto-filled (locked), not manually typed by the user
        if (plateInput && wasLocked) plateInput.value = '';
        window._suggestPlateForIsland(this.value);
    });
})();
