document.addEventListener('DOMContentLoaded', function() {
    const today = new Date().toISOString().split('T')[0];
    const dateInput = document.getElementById('report-date');
    if (dateInput) {
        dateInput.value = today;
        loadDailyReport();
    }
    
    // Set generated date and time
    setGeneratedDateTime();
});

function setGeneratedDateTime() {
    const now = new Date();
    const dateStr = now.toLocaleDateString('fr-FR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
    document.getElementById('report-generated-date').textContent = dateStr;
    document.getElementById('footer-date').textContent = dateStr;
}

function loadDailyReport() {
    const dateInput = document.getElementById('report-date');
    const reportDate = dateInput.value;

    if (!reportDate) {
        alert('Veuillez sélectionner une date pour le rapport');
        return;
    }

    // Format date for display
    const reportDateObj = new Date(reportDate + 'T00:00:00');
    const dateDisplay = reportDateObj.toLocaleDateString('fr-FR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
    document.getElementById('report-date-display').textContent = dateDisplay;

    const url = `/api/vehicles/vignette-daily-report?date=${reportDate}`;

    fetch(url, {
        credentials: 'same-origin'
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(error => { throw new Error(error.error || 'Erreur'); });
        }
        return response.json();
    })
    .then(data => {
        displayDailyReport(data);
    })
    .catch(error => {
        console.error('Erreur rapport journalier:', error);
        alert('Impossible de charger le rapport journalier');
    });
}

function displayDailyReport(data) {
    // Update KPIs
    document.getElementById('kpi-paid').textContent = data.total_paid || 0;
    document.getElementById('kpi-revenue').textContent = formatKMF(data.total_revenue);
    document.getElementById('kpi-penalties').textContent = formatKMF(data.total_penalties);
    document.getElementById('kpi-fines').textContent = formatKMF(data.total_fines);

    // Update summary section
    document.getElementById('summary-revenue').textContent = formatKMF(data.total_revenue);
    document.getElementById('summary-penalties').textContent = formatKMF(data.total_penalties);
    document.getElementById('summary-fines').textContent = formatKMF(data.total_fines);
    
    const grandTotal = (data.total_revenue || 0) + (data.total_penalties || 0) + (data.total_fines || 0);
    document.getElementById('summary-total').textContent = formatKMF(grandTotal);
    const kpiQr = document.getElementById('kpi-qr');
    if (kpiQr) kpiQr.textContent = formatKMF(data.total_qr || 0);

    // Update table
    const tbody = document.getElementById('report-vehicles-body');
    
    if (!data.vehicles || !data.vehicles.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; padding: 20px; color: #999;">
                    <i class="fas fa-inbox me-2"></i>Aucun véhicule trouvé pour cette date.
                </td>
            </tr>
        `;
        return;
    }

    // Sort by updated_at (most recent first) so newly added/renewed vehicles appear at top
    data.vehicles.sort((a, b) => {
        const dateA = new Date(a.updated_at || 0);
        const dateB = new Date(b.updated_at || 0);
        return dateB - dateA; // Descending order (most recent first)
    });

    tbody.innerHTML = data.vehicles.map(vehicle => `
        <tr>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-weight: bold;">${vehicle.license_plate}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; text-align: center;">${vehicle.payment_date}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; text-align: right;">${formatKMF(vehicle.vignette_price)}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; text-align: right; color: #f39c12;">${formatKMF(vehicle.penalty_amount)}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; text-align: right; color: #e74c3c;">${formatKMF(vehicle.fines_amount)}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; text-align: right; color: ${vehicle.qr_amount > 0 ? '#0dcaf0' : '#aaa'};">${vehicle.qr_amount > 0 ? formatKMF(vehicle.qr_amount) : '-'}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; text-align: right; font-weight: bold; color: #27ae60;">${formatKMF(vehicle.total)}</td>
        </tr>
    `).join('');
    
    // Update footer totals
    const totalRevenue = data.total_revenue || 0;
    const totalPenalties = data.total_penalties || 0;
    const totalFines = data.total_fines || 0;
    const totalQr = data.total_qr || 0;
    const total = totalRevenue + totalPenalties + totalFines;

    document.getElementById('footer-revenue').textContent = formatKMF(totalRevenue);
    document.getElementById('footer-penalties').textContent = formatKMF(totalPenalties);
    document.getElementById('footer-fines').textContent = formatKMF(totalFines);
    const footerQr = document.getElementById('footer-qr');
    if (footerQr) footerQr.textContent = totalQr > 0 ? formatKMF(totalQr) : '-';
    document.getElementById('footer-total').textContent = formatKMF(total);
}

function printReport() {
    const reportDate = document.getElementById('report-date').value;
    if (!reportDate) {
        alert('Veuillez sélectionner une date pour le rapport');
        return;
    }
    // Open in a new tab for printing/PDF download
    window.open(`/vignette-daily-report-print?date=${reportDate}`, '_blank');
}

function formatKMF(amount) {
    if (amount === null || amount === undefined) {
        return '0 KMF';
    }
    const num = parseFloat(amount) || 0;
    return num.toLocaleString('fr-KM') + ' KMF';
}
