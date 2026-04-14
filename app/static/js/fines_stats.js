document.addEventListener('DOMContentLoaded', function(){
    loadFinesStats(false);
});

// Variable globale pour stocker toutes les données
let allStatsData = null;

async function loadFinesStats(forceRefresh = false) {
    try {
        // Charger directement sans vérifier le cache

        // Afficher les spinners de chargement
        showLoadingSpinners(true);

        const response = await fetch('/api/vehicles/fines/stats');

        if (!response.ok) {
            throw new Error(`Erreur HTTP: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();

        // Vérifier si la réponse contient une erreur
        if (data.error) {
            throw new Error(data.error);
        }

        // Stocker les données complètes
        allStatsData = data;

        // Masquer les spinners
        showLoadingSpinners(false);

        // Mettre à jour l'interface
        updateUIWithData(data);

        // Afficher un message de succès
        if (window.showSuccess) {
            window.showSuccess('Statistiques chargées avec succès');
        }

    } catch (error) {
        // Masquer les spinners en cas d'erreur
        showLoadingSpinners(false);

        console.error('Erreur lors du chargement des statistiques:', error);
        showError('Erreur lors du chargement des données: ' + error.message);
    }
}

function updateUIWithData(data) {
    // Mettre à jour les cartes générales
    updateGeneralStats(data.general);

    // Créer les graphiques
    createMonthlyChart(data.monthly);
    createPaymentChart(data.general);
    createOfficersChart(data.officers);
    createReasonsChart(data.reasons);

    // Remplir le tableau des agents
    populateOfficersTable(data.officers);
}

function showLoadingSpinners(show) {
    const spinners = ['total-fines-spinner', 'paid-fines-spinner', 'unpaid-fines-spinner', 'total-amount-spinner'];
    spinners.forEach(id => {
        const spinner = document.getElementById(id);
        if (spinner) {
            spinner.classList.toggle('d-none', !show);
        }
    });
}

function updateGeneralStats(general) {
    document.getElementById('total-fines').textContent = general.total_fines;
    document.getElementById('paid-fines').textContent = general.paid_fines;
    document.getElementById('unpaid-fines').textContent = general.unpaid_fines;
    document.getElementById('total-amount').textContent = formatCurrency(general.total_amount);
}

function createMonthlyChart(monthlyData) {
    const ctx = document.getElementById('monthlyChart').getContext('2d');

    const labels = monthlyData.map(item => {
        const date = new Date(item.month + '-01');
        return date.toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });
    });

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Total Amandes',
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
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
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
}

function createPaymentChart(general) {
    const ctx = document.getElementById('paymentChart').getContext('2d');

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
                legend: {
                    position: 'bottom',
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((context.parsed / total) * 100).toFixed(1);
                            return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                        }
                    }
                }
            }
        }
    });
}

function createOfficersChart(officersData) {
    const ctx = document.getElementById('officersChart').getContext('2d');

    // Prendre seulement le top 10
    const topOfficers = officersData.slice(0, 10);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: topOfficers.map(item => item.name),
            datasets: [{
                label: 'Nombre d\'Amandes',
                data: topOfficers.map(item => item.count),
                backgroundColor: 'rgba(0, 123, 255, 0.8)',
                borderColor: '#007bff',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                },
                x: {
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            }
        }
    });
}

function createReasonsChart(reasonsData) {
    const ctx = document.getElementById('reasonsChart').getContext('2d');

    // Prendre seulement le top 10
    const topReasons = reasonsData.slice(0, 10);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: topReasons.map(item => item.reason.length > 30 ? item.reason.substring(0, 30) + '...' : item.reason),
            datasets: [{
                label: 'Nombre d\'Amandes',
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
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

function populateOfficersTable(officersData) {
    const tbody = document.getElementById('officers-tbody');

    if (officersData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Aucune donnée disponible</td></tr>';
        return;
    }

    tbody.innerHTML = officersData.map(officer => {
        const average = officer.count > 0 ? (officer.total_amount / officer.count) : 0;
        return `
            <tr>
                <td><strong>${officer.name}</strong></td>
                <td>${officer.count}</td>
                <td>${formatCurrency(officer.total_amount)}</td>
                <td>${formatCurrency(average)}</td>
            </tr>
        `;
    }).join('');
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: 'KMF',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
}

function showError(message) {
    // Utiliser le système de toast si disponible, sinon alert
    if (window.showError) {
        window.showError(message);
    } else {
        alert('Erreur: ' + message);
    }
}