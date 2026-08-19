document.addEventListener('DOMContentLoaded', function() {
    // Set default dates
    setDefaultDates();
    
    // Load initial stats
    loadFinanceStats();
    
    // Setup event listeners
    document.getElementById('finance-period').addEventListener('change', function() {
        if (this.value === 'custom') {
            document.getElementById('finance-start-date').disabled = false;
            document.getElementById('finance-end-date').disabled = false;
        } else {
            document.getElementById('finance-start-date').disabled = true;
            document.getElementById('finance-end-date').disabled = true;
            setDefaultDates();
            loadFinanceStats();
        }
    });
});

function setDefaultDates() {
    const period = document.getElementById('finance-period').value;
    const endDate = new Date();
    const startDate = new Date();
    
    if (period === 'custom') {
        // Don't set dates for custom period
        return;
    }
    
    const days = parseInt(period) || 30;
    startDate.setDate(startDate.getDate() - days);
    
    document.getElementById('finance-start-date').value = startDate.toISOString().split('T')[0];
    document.getElementById('finance-end-date').value = endDate.toISOString().split('T')[0];
}

function loadFinanceStats() {
    const startDate = document.getElementById('finance-start-date').value;
    const endDate = document.getElementById('finance-end-date').value;
    
    if (!startDate || !endDate) {
        alert('Veuillez sélectionner une date de début et de fin');
        return;
    }
    
    const url = `/api/vehicles/vignette-finance-stats?start_date=${startDate}&end_date=${endDate}`;
    
    fetch(url, {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    })
    .then(data => {
        displayFinanceStats(data);
        loadVehiclesTable(startDate, endDate);
    })
    .catch(err => {
        console.error('Error loading finance stats:', err);
        alert('Erreur lors du chargement des statistiques');
    });
}

function displayFinanceStats(data) {
    // Update main statistics
    document.getElementById('stat-active-vignettes').textContent = data.total_active_vignettes || 0;
    document.getElementById('stat-renewed-vignettes').textContent = data.renewed_vignettes || 0;
    document.getElementById('stat-penalties').textContent = formatKMF(data.total_penalties);
    const statQr = document.getElementById('stat-qr-revenue');
    if (statQr) statQr.textContent = formatKMF(data.total_qr_revenue || 0);
    document.getElementById('stat-total-revenue').textContent = formatKMF(data.total_revenue);
    
    // Update detailed breakdown
    const breakdown = document.getElementById('finance-breakdown');
    breakdown.innerHTML = `
        <tr>
            <td class="fw-semibold">
                <i class="fas fa-ticket-alt text-success me-2"></i>Revenus Vignettes
            </td>
            <td class="text-end">
                <strong>${formatKMF(data.total_vignette_revenue)}</strong>
            </td>
        </tr>
        <tr>
            <td class="fw-semibold">
                <i class="fas fa-exclamation-triangle text-warning me-2"></i>Pénalités de Retard
            </td>
            <td class="text-end">
                <strong class="text-warning">${formatKMF(data.total_penalties)}</strong>
            </td>
        </tr>
        <tr>
            <td class="fw-semibold">
                <i class="fas fa-gavel text-danger me-2"></i>Amendes Impayées
            </td>
            <td class="text-end">
                <strong class="text-danger">${formatKMF(data.total_fines)}</strong>
            </td>
        </tr>
        ${(data.total_qr_revenue || 0) > 0 ? `
        <tr>
            <td class="fw-semibold">
                <i class="fas fa-qrcode text-info me-2"></i>Tarif QR Code
            </td>
            <td class="text-end">
                <strong class="text-info">${formatKMF(data.total_qr_revenue)}</strong>
            </td>
        </tr>
        ` : ''}
        <tr class="table-active">
            <td class="fw-semibold text-success">
                <i class="fas fa-coins me-2"></i>Total Collecté
            </td>
            <td class="text-end">
                <strong class="text-success" style="font-size: 1.1em;">${formatKMF(data.total_revenue)}</strong>
            </td>
        </tr>
    `;
}

function loadVehiclesTable(startDate, endDate) {
    const url = `/api/vehicles/vignette-finance-vehicles?start_date=${startDate}&end_date=${endDate}`;
    
    fetch(url, {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    })
    .then(vehicles => {
        displayVehiclesTable(vehicles);
    })
    .catch(err => {
        console.error('Error loading vehicles:', err);
    });
}

function displayVehiclesTable(vehicles) {
    const tbody = document.getElementById('finance-vehicles-table');
    
    if (!vehicles || vehicles.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-4">
                    <i class="fas fa-inbox me-2"></i>Aucun véhicule trouvé
                </td>
            </tr>
        `;
        return;
    }
    
    // Sort by updated_at (most recent first) so newly added/renewed vehicles appear at top
    vehicles.sort((a, b) => {
        const dateA = new Date(a.updated_at || 0);
        const dateB = new Date(b.updated_at || 0);
        return dateB - dateA; // Descending order (most recent first)
    });
    
    tbody.innerHTML = vehicles.map(v => `
        <tr>
            <td class="fw-semibold">${v.license_plate}</td>
            <td>${v.payment_date}</td>
            <td class="text-end">${formatNumberKMF(v.vignette_price)}</td>
            <td class="text-end ${v.penalty_amount > 0 ? 'text-warning' : ''}">${formatNumberKMF(v.penalty_amount)}</td>
            <td class="text-end ${v.fines_amount > 0 ? 'text-danger' : ''}">${formatNumberKMF(v.fines_amount)}</td>
            <td class="text-end ${v.qr_amount > 0 ? 'text-info fw-semibold' : 'text-muted'}">${v.qr_amount > 0 ? formatNumberKMF(v.qr_amount) : '-'}</td>
            <td class="text-end fw-semibold ${v.total > 0 ? 'text-success' : ''}">${formatNumberKMF(v.total)}</td>
        </tr>
    `).join('');
}

function formatKMF(amount) {
    if (!amount) return '0 KMF';
    const num = parseFloat(amount);
    return num.toLocaleString('fr-KM') + ' KMF';
}

function formatNumberKMF(amount) {
    if (!amount) return '0 KMF';
    const num = parseFloat(amount);
    return num.toLocaleString('fr-KM') + ' KMF';
}

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('fr-FR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}
