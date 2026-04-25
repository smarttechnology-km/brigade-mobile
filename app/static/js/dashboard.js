// Script pour le dashboard
var vehicleTypeChart = window.vehicleTypeChart || null;
window.vehicleTypeChart = vehicleTypeChart;
var vehicleStatusChart = window.vehicleStatusChart || null;
window.vehicleStatusChart = vehicleStatusChart;

// Initialiser les graphiques au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    // If Chart.js failed to load, show a helpful message early
    if (typeof Chart === 'undefined'){
        console.error('Chart.js non chargé: la variable `Chart` est introuvable.');
        showDashboardError('Librairie Chart.js non chargée — vérifiez la console Network pour `chart.min.js`.');
        // still attempt to load stats (numbers) but skip charts creation
    }
    loadDashboardData();
    // Actualiser les données toutes les 30 secondes
    setInterval(loadDashboardData, 30000);
    
    // country filter binding for admin
    const countryFilterEl = document.getElementById('dashboard-country-filter');
    if(countryFilterEl){
        countryFilterEl.addEventListener('change', function(){
            loadDashboardData(0, this.value);
        });
    }
});

/**
 * Charger les données du dashboard via l'API avec retry pour les erreurs 502
 */
function loadDashboardData(retryCount = 0, country = null) {
    const maxRetries = 2;
    const retryDelay = 2000; // 2 secondes entre les tentatives
    
    let url = '/api/vehicles/stats';
    if(country) url += '?country=' + encodeURIComponent(country);
    
    fetch(url, { credentials: 'same-origin' })
        .then(async response => {
            if(!response.ok){
                let body = '';
                try{ body = await response.text(); }catch(e){}
                
                // Si c'est une erreur 502 et qu'on n'a pas dépassé les retry max, attendre et réessayer
                if(response.status === 502 && retryCount < maxRetries){
                    console.warn(`Erreur 502. Nouvelle tentative ${retryCount + 1}/${maxRetries}...`);
                    setTimeout(() => loadDashboardData(retryCount + 1), retryDelay);
                    return;
                }
                
                throw new Error('HTTP ' + response.status + ' ' + (response.statusText || '') + ' - ' + body);
            }
            return response.json();
        })
        .then(data => {
            if (data === undefined) return; // Retry en cours
            clearDashboardError();
            try{
                // Compare to last fetched stats to avoid unnecessary re-renders
                const last = window._lastDashboardStats || null;
                const curKey = JSON.stringify({by_type: data.by_type || [], by_status: data.by_status || [], total: data.total_vehicles || 0});
                if(last && last.key === curKey){
                    // no change -> skip heavy chart updates
                    console.debug('Dashboard stats unchanged; skipping charts update');
                } else {
                    // store and update
                    window._lastDashboardStats = { key: curKey, data: data };
                    updateStatistics(data);
                    updateCharts(data);
                }
            }catch(e){
                console.error('Erreur comparaison stats:', e);
                updateStatistics(data);
                updateCharts(data);
            }
        })
        .catch(error => {
            console.error('Erreur lors du chargement des statistiques:', error);
            showDashboardError('Impossible de charger les statistiques: ' + (error.message || String(error)) + ' (le serveur reprend du service, veuillez patienter...)');
        });

    loadVehiclesList(retryCount, country);
}

/**
 * Mettre à jour les statistiques affichées
 */
function updateStatistics(data) {
    document.getElementById('total-vehicles').textContent = data.total_vehicles;
    
    // Trouver les compteurs par statut
    const statusMap = {};
    data.by_status.forEach(item => {
        statusMap[item.status] = item.count;
    });
    
    document.getElementById('active-vehicles').textContent = statusMap['active'] || 0;
    document.getElementById('inactive-vehicles').textContent = statusMap['inactive'] || 0;
    document.getElementById('suspended-vehicles').textContent = statusMap['suspended'] || 0;
}

/**
 * Mettre à jour les graphiques
 */
function updateCharts(data) {
    updateTypeChart(data.by_type);
    updateStatusChart(data.by_status);
}

/**
 * Mettre à jour le graphique des types de véhicules
 */
function updateTypeChart(typeData) {
    if (typeof Chart === 'undefined'){
        console.error('Chart.js non disponible — saut de création du graphique des types.');
        return;
    }
    // ensure canvas exists (may have been replaced by a placeholder)
    let canvas = document.getElementById('vehicleTypeChart');
    const container = canvas ? canvas.parentElement : document.querySelector('#vehicleTypeChart')?.parentElement;
    if(!canvas && container){
        container.innerHTML = '<canvas id="vehicleTypeChart"></canvas>';
        canvas = document.getElementById('vehicleTypeChart');
    }
    const ctx = canvas ? canvas.getContext('2d') : null;

    // defensive: ensure we have an array
    if(!Array.isArray(typeData)) typeData = [];
    // keep original types lowercased for stable mapping
    const typeKeys = typeData.map(item => (item.type || 'non spécifié').toLowerCase());
    const labels = typeData.map(item => capitalizeFirst(item.type || 'Non spécifié'));
    const counts = typeData.map(item => item.count);

    // fixed color map per vehicle type to ensure consistent colors regardless of API ordering
    const colorMap = {
        'suv': '#007bff',
        'voiture': '#6f42c1',
        'moto': '#17a2b8',
        'camion': '#fd7e14',
        'bus': '#20c997',
        'van': '#ffc107',
        'pickup': '#dc3545',
        'non spécifié': '#6c757d'
    };
    const defaultColors = ['#007bff', '#28a745', '#ffc107', '#dc3545', '#17a2b8', '#6f42c1', '#fd7e14', '#20c997'];
    const backgroundColors = typeKeys.map((t, i) => colorMap[t] || defaultColors[i % defaultColors.length]);

    if (vehicleTypeChart) {
        try{
            // update existing chart data instead of destroying to avoid visual flicker
            vehicleTypeChart.data.labels = labels;
            vehicleTypeChart.data.datasets[0].data = counts;
            vehicleTypeChart.data.datasets[0].backgroundColor = backgroundColors;
            vehicleTypeChart.update();
            return;
        }catch(e){
            try{ vehicleTypeChart.destroy(); }catch(e){}
            vehicleTypeChart = null;
        }
    }

    // if there's no data, show a placeholder element instead of creating an empty chart
    if(!labels || labels.length === 0 || counts.reduce((a,b)=>a+(b||0),0) === 0){
        try{
            if(container) container.innerHTML = '<div class="text-center text-muted py-5">Aucune donnée</div>';
        }catch(e){ console.error('Erreur affichage placeholder type chart', e); }
        return;
    }

    try{
    vehicleTypeChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: counts,
                backgroundColor: backgroundColors,
                borderColor: '#fff',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 15,
                        font: { size: 12 }
                    }
                }
            }
        }
    });
    }catch(e){ console.error('Erreur création type chart', e); }
    // expose instance to window for debugging and reuse
    try{ window.vehicleTypeChart = vehicleTypeChart; }catch(e){}
}

/**
 * Mettre à jour le graphique des statuts
 */
function updateStatusChart(statusData) {
    if (typeof Chart === 'undefined'){
        console.error('Chart.js non disponible — saut de création du graphique des statuts.');
        return;
    }
    // ensure canvas exists (may have been replaced by a placeholder)
    let canvas = document.getElementById('vehicleStatusChart');
    const container = canvas ? canvas.parentElement : document.querySelector('#vehicleStatusChart')?.parentElement;
    if(!canvas && container){
        container.innerHTML = '<canvas id="vehicleStatusChart"></canvas>';
        canvas = document.getElementById('vehicleStatusChart');
    }
    const ctx = canvas ? canvas.getContext('2d') : null;
    
    const statusLabels = {
        'active': 'Actif',
        'inactive': 'Inactif',
        'suspended': 'Suspendu'
    };
    
    if(!Array.isArray(statusData)) statusData = [];
    // Use a fixed order and color mapping so each status always has the same color
    const fixedOrder = ['active','inactive','suspended'];
    const colorMap = { 'active': '#28a745', 'inactive': '#dc3545', 'suspended': '#ffc107' };
    // Build a map for quick lookup
    const countsMap = {};
    statusData.forEach(item => { countsMap[item.status] = item.count; });
    const labels = fixedOrder.map(s => statusLabels[s] || s);
    const counts = fixedOrder.map(s => countsMap[s] || 0);
    const colors = fixedOrder.map(s => colorMap[s] || '#6c757d');
    
    if (vehicleStatusChart) {
        try{
            // update existing chart instance
            vehicleStatusChart.data.labels = labels;
            vehicleStatusChart.data.datasets[0].data = counts;
            vehicleStatusChart.data.datasets[0].backgroundColor = colors;
            vehicleStatusChart.update();
            return;
        }catch(e){
            try{ vehicleStatusChart.destroy(); }catch(e){}
            vehicleStatusChart = null;
        }
    }

    if(!labels || labels.length === 0 || counts.reduce((a,b)=>a+(b||0),0) === 0){
        try{
            if(container) container.innerHTML = '<div class="text-center text-muted py-5">Aucune donnée</div>';
        }catch(e){ console.error('Erreur affichage placeholder status chart', e); }
        return;
    }

    try{
    vehicleStatusChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
                datasets: [{
                label: 'Nombre de véhicules',
                data: counts,
                backgroundColor: colors,
                borderColor: colors,
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        padding: 15,
                        font: { size: 12 }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
    }catch(e){ console.error('Erreur création status chart', e); }
    try{ window.vehicleStatusChart = vehicleStatusChart; }catch(e){}
}

/**
 * Charger la liste des véhicules
 */
function loadVehiclesList(retryCount = 0, country = null) {
    const maxRetries = 2;
    const retryDelay = 2000; // 2 secondes entre les tentatives
    
    // hide table while loading to prevent flash of stale/partial content
    const table = document.getElementById('vehicles-table');
    // if server already provided initial vehicles, or we've already loaded once, don't hide
    const hasInitial = (window.hasInitialVehicles === true || window.hasInitialVehicles === 'true');
    const shouldHide = !hasInitial && !window._vehiclesLoaded;
    if (table && shouldHide) table.classList.add('invisible');

    let url = '/api/vehicles/list';
    if(country) url += '?country=' + encodeURIComponent(country);
    
    fetch(url, { credentials: 'same-origin' })
        .then(async response => {
            if(!response.ok){
                let body = '';
                try{ body = await response.text(); }catch(e){}
                
                // Si c'est une erreur 502 et qu'on n'a pas dépassé les retry max, attendre et réessayer
                if(response.status === 502 && retryCount < maxRetries){
                    console.warn(`Erreur 502 sur /api/vehicles/list. Nouvelle tentative ${retryCount + 1}/${maxRetries}...`);
                    setTimeout(() => loadVehiclesList(retryCount + 1, country), retryDelay);
                    return;
                }
                
                throw new Error('HTTP ' + response.status + ' ' + (response.statusText || '') + ' - ' + body);
            }
            return response.json();
        })
        .then(data => {
            if (data === undefined) return; // Retry en cours
            try{
                // Build a compact key for the first 10 vehicles to detect changes
                const keyItems = (data || []).slice(0, 10).map(v => ({
                    id: v.id,
                    lp: v.license_plate,
                    status: v.status,
                    owner: v.owner_name
                }));
                const key = JSON.stringify(keyItems);
                if(window._lastVehiclesKey && window._lastVehiclesKey === key){
                    console.debug('Vehicles list unchanged; skipping update');
                    // ensure table visible after first load
                    if (table && shouldHide) table.classList.remove('invisible');
                    window._vehiclesLoaded = true;
                    return;
                }
                window._lastVehiclesKey = key;
            }catch(e){
                console.error('Erreur calcul clé véhicules:', e);
            }

            displayVehiclesList(data);
            // show table after render if we hid it
            if (table && shouldHide) table.classList.remove('invisible');
            window._vehiclesLoaded = true;
        })
        .catch(error => {
            console.error('Erreur lors du chargement de la liste:', error);
            if (table && shouldHide) table.classList.remove('invisible');
            // mark as loaded to avoid hiding on subsequent intervals
            window._vehiclesLoaded = true;
        });
}

/**
 * Afficher la liste des véhicules dans le tableau
 */
function displayVehiclesList(vehicles) {
    const tbody = document.getElementById('vehicles-tbody');
    
    if (vehicles.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-4">
                    <i class="fas fa-inbox"></i> Aucun véhicule enregistré
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = vehicles.slice(0, 10).map(vehicle => `
        <tr>
            <td><strong>${vehicle.license_plate}</strong></td>
            <td>${vehicle.owner_name}</td>
            <td>
                ${renderTypeBadge(vehicle.vehicle_type)}
            </td>
            <td>
                <span class="badge ${getStatusBadgeClass(vehicle.status)}">
                    ${getStatusLabel(vehicle.status)}
                </span>
            </td>
            <td><small>${vehicle.registration_date}</small></td>
            <td>
                <button class="btn btn-sm btn-outline-primary" title="Détails" onclick="viewVehicle('${vehicle.track_token}')">
                    <i class="fas fa-eye"></i>
                </button>
                <!-- Fine action removed from dashboard; use /fines page -->
                <button class="btn btn-sm btn-outline-danger" title="Supprimer" onclick="deleteVehicleFromDashboard(${vehicle.id})">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

// Ouvrir la page publique de suivi dans un nouvel onglet
function viewVehicle(trackToken){
    if(!trackToken) return;
    const url = `/track/${trackToken}`;
    // navigate in the same tab instead of opening a new one
    window.location.href = url;
}

// Rediriger vers la page de gestion, en ouvrant le modal d'édition via query param
function editVehicleFromDashboard(id){
    if(!id) return;
    // Try to open the inline vehicle edit modal provided by vehicles.js
    try{
        fetch(`/api/vehicles/${id}`)
            .then(r => {
                if(!r.ok) throw new Error('Véhicule non trouvé');
                return r.json();
            })
            .then(v => {
                if(typeof openVehicleModal === 'function'){
                    openVehicleModal(v);
                } else {
                    // fallback: redirect to vehicles page with edit param
                    window.location.href = `/vehicles?edit=${id}`;
                }
            })
            .catch(err => {
                console.error('Erreur ouverture édition inline:', err);
                // fallback redirect
                window.location.href = `/vehicles?edit=${id}`;
            });
    }catch(e){
        console.error(e);
        window.location.href = `/vehicles?edit=${id}`;
    }
}

// Supprimer un véhicule depuis le dashboard
function deleteVehicleFromDashboard(id){
    if(!id) return;
    if(!confirm('Confirmer la suppression de ce véhicule ?')) return;
    fetch(`/api/vehicles/${id}`, { method: 'DELETE' })
        .then(resp => {
            if(!resp.ok) throw new Error('Erreur suppression');
            return resp.json();
        })
        .then(() => {
            // raffraîchir stats et liste
            loadDashboardData();
        })
        .catch(err => {
            console.error('Erreur suppression:', err);
            alert('Impossible de supprimer le véhicule');
        });
}

/**
 * Obtenir la classe CSS pour le badge de statut
 */
function getStatusBadgeClass(status) {
    const classes = {
        'active': 'bg-success',
        'inactive': 'bg-danger',
        'suspended': 'bg-warning text-dark'
    };
    return classes[status] || 'bg-secondary';
}

/**
 * Obtenir l'étiquette du statut en français
 */
function getStatusLabel(status) {
    const labels = {
        'active': 'Actif',
        'inactive': 'Inactif',
        'suspended': 'Suspendu'
    };
    return labels[status] || status;
}

/**
 * Retourne la couleur associée à un type de véhicule (hex)
 */
function getTypeColor(type){
    if(!type) return '#6c757d';
    const t = String(type).toLowerCase();
    const colorMap = {
        'suv': '#007bff',
        'voiture': '#6f42c1',
        'moto': '#17a2b8',
        'camion': '#fd7e14',
        'bus': '#20c997',
        'van': '#ffc107',
        'pickup': '#dc3545',
        'non spécifié': '#6c757d'
    };
    return colorMap[t] || '#6c757d';
}

function _hexToLuminance(hex){
    // remove #
    hex = String(hex||'#6c757d').replace('#','');
    if(hex.length===3) hex = hex.split('').map(c=>c+c).join('');
    const r = parseInt(hex.substring(0,2),16)/255;
    const g = parseInt(hex.substring(2,4),16)/255;
    const b = parseInt(hex.substring(4,6),16)/255;
    // relative luminance
    const a = [r,g,b].map(v=> v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4));
    return 0.2126*a[0] + 0.7152*a[1] + 0.0722*a[2];
}

function renderTypeBadge(type){
    const color = getTypeColor(type);
    const lum = _hexToLuminance(color);
    const textColor = lum > 0.5 ? '#212529' : '#ffffff';
    return `<span class="badge" style="background-color:${color}; color:${textColor};">${capitalizeFirst(type||'Non spécifié')}</span>`;
}

/**
 * Capitaliser la première lettre
 */
function capitalizeFirst(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
}

/**
 * Show a visible error banner on the dashboard when API calls fail
 */
function showDashboardError(msg){
    try{
        const container = document.querySelector('.container-fluid');
        if(!container) return;
        let el = document.getElementById('dashboard-error');
        if(!el){
            el = document.createElement('div');
            el.id = 'dashboard-error';
            el.className = 'alert alert-danger';
            el.style.marginBottom = '1rem';
            container.prepend(el);
        }
        el.textContent = msg;
    }catch(e){ console.error('Erreur affichage dashboard error', e); }
}

function clearDashboardError(){
    try{ const el = document.getElementById('dashboard-error'); if(el) el.remove(); }catch(e){}
}
