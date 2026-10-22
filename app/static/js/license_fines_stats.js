// ── Statistiques des amendes de permis (onglet "Permis de conduire") ──

document.addEventListener('DOMContentLoaded', function () {
    const permisTabBtn = document.getElementById('tab-stats-permis-btn');
    if (permisTabBtn) {
        let loadedOnce = false;
        permisTabBtn.addEventListener('shown.bs.tab', function () {
            if (!loadedOnce) {
                loadedOnce = true;
                loadLicenseFinesStats();
            }
        });
    }
});

async function loadLicenseFinesStats(country = null) {
    try {
        let url = '/api/licenses/fines/stats';
        if (country) url += '?country=' + encodeURIComponent(country);

        const response = await fetch(url);
        if (!response.ok) throw new Error(`Erreur HTTP: ${response.status}`);
        const data = await response.json();
        if (data.error) throw new Error(data.error);

        lfUpdateGeneralStats(data.general);
        lfCreateMonthlyChart(data.monthly);
        lfCreatePaymentChart(data.general);
        lfCreateOfficersChart(data.officers);
        lfCreateReasonsChart(data.reasons);
        lfPopulateOfficersTable(data.officers);
    } catch (error) {
        console.error('Erreur lors du chargement des statistiques (permis):', error);
    }
}

function lfUpdateGeneralStats(general) {
    document.getElementById('lf-total-fines').textContent = general.total_fines;
    document.getElementById('lf-paid-fines').textContent = general.paid_fines;
    document.getElementById('lf-unpaid-fines').textContent = general.unpaid_fines;
    document.getElementById('lf-paid-amount').textContent = lfFormatCurrency(general.paid_amount);
    document.getElementById('lf-paid-amount-ratio').textContent = '/ ' + lfFormatCurrency(general.total_amount);
}

function lfCreateMonthlyChart(monthlyData) {
    const ctx = document.getElementById('lf-monthlyChart').getContext('2d');
    const labels = monthlyData.map(item => {
        const date = new Date(item.month + '-01');
        return date.toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });
    });

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Total Amendes',
                data: monthlyData.map(item => item.total),
                borderColor: '#007bff',
                backgroundColor: 'rgba(0, 123, 255, 0.1)',
                tension: 0.4,
                fill: true
            }, {
                label: 'Payées',
                data: monthlyData.map(item => item.paid),
                borderColor: '#28a745',
                backgroundColor: 'rgba(40, 167, 69, 0.1)',
                tension: 0.4,
                fill: true
            }, {
                label: 'Impayées',
                data: monthlyData.map(item => item.unpaid),
                borderColor: '#ffc107',
                backgroundColor: 'rgba(255, 193, 7, 0.1)',
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' }, tooltip: { mode: 'index', intersect: false } },
            scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }
        }
    });
}

function lfCreatePaymentChart(general) {
    const ctx = document.getElementById('lf-paymentChart').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Payées', 'Impayées'],
            datasets: [{
                data: [general.paid_fines, general.unpaid_fines],
                backgroundColor: ['#28a745', '#ffc107'],
                borderWidth: 2,
                borderColor: '#ffffff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total ? ((context.parsed / total) * 100).toFixed(1) : '0.0';
                            return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                        }
                    }
                }
            }
        }
    });
}

function lfCreateOfficersChart(officersData) {
    const ctx = document.getElementById('lf-officersChart').getContext('2d');
    const topOfficers = officersData.slice(0, 10);
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: topOfficers.map(item => item.name),
            datasets: [{
                label: "Nombre d'Amendes",
                data: topOfficers.map(item => item.count),
                backgroundColor: 'rgba(0, 123, 255, 0.8)',
                borderColor: '#007bff',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, ticks: { stepSize: 1 } },
                x: { ticks: { maxRotation: 45, minRotation: 45 } }
            }
        }
    });
}

function lfCreateReasonsChart(reasonsData) {
    const ctx = document.getElementById('lf-reasonsChart').getContext('2d');
    const topReasons = reasonsData.slice(0, 10);
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: topReasons.map(item => item.reason.length > 30 ? item.reason.substring(0, 30) + '...' : item.reason),
            datasets: [{
                label: "Nombre d'Amendes",
                data: topReasons.map(item => item.count),
                backgroundColor: 'rgba(255, 193, 7, 0.8)',
                borderColor: '#ffc107',
                borderWidth: 1
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } }
        }
    });
}

function lfPopulateOfficersTable(officersData) {
    const tbody = document.getElementById('lf-officers-tbody');
    if (!officersData.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Aucune donnée disponible</td></tr>';
        return;
    }
    tbody.innerHTML = officersData.map(officer => {
        const average = officer.count > 0 ? (officer.total_amount / officer.count) : 0;
        return `
            <tr>
                <td><strong>${officer.name}</strong></td>
                <td>${officer.count}</td>
                <td>${lfFormatCurrency(officer.total_amount)}</td>
                <td>${lfFormatCurrency(average)}</td>
            </tr>
        `;
    }).join('');
}

function lfFormatCurrency(amount) {
    return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: 'KMF',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
}
