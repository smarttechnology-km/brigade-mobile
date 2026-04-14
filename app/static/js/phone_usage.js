let checkoutModalInstance = null;
let checkinModalInstance = null;
let pendingCheckinId = null;
let showAllHistory = false;
let usagesCache = [];
let usersCache = [];

document.addEventListener('DOMContentLoaded', function() {
    loadUsers();
    loadStats();
    loadUsageHistory();
    setupEventListeners();
});

function loadUsers() {
    fetch('/api/users/list').then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    }).then(data => {
        usersCache = data.users || [];
    }).catch(err => { console.error('load users failed', err); });
}

function setupEventListeners() {
    const checkoutBtn = document.getElementById('btn-checkout-phone');
    if (checkoutBtn) {
        checkoutBtn.addEventListener('click', openCheckoutModal);
    }

    const confirmCheckoutBtn = document.getElementById('btn-confirm-checkout');
    if (confirmCheckoutBtn) {
        confirmCheckoutBtn.addEventListener('click', submitCheckout);
    }

    const confirmCheckinBtn = document.getElementById('btn-confirm-checkin');
    if (confirmCheckinBtn) {
        confirmCheckinBtn.addEventListener('click', submitCheckin);
    }

    const toggleHistoryBtn = document.getElementById('btn-toggle-history');
    if (toggleHistoryBtn) {
        toggleHistoryBtn.addEventListener('click', toggleHistory);
    }

    const searchInput = document.getElementById('search-usage-code');
    const clearBtn = document.getElementById('btn-clear-search');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            filterUsageByCode(this.value);
        });
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            document.getElementById('search-usage-code').value = '';
            filterUsageByCode('');
        });
    }
}

function loadStats() {
    fetch('/api/phone-usage/stats')
        .then(r => r.json())
        .then(data => {
            document.getElementById('stat-total').textContent = data.total_phones;
            document.getElementById('stat-active').textContent = data.active_phones;
            document.getElementById('stat-inactive').textContent = data.inactive_phones;
            document.getElementById('stat-borrowed').textContent = data.phones_currently_checked_out;
        })
        .catch(err => console.error('Erreur chargement stats:', err));
}

function loadUsageHistory() {
    const url = showAllHistory 
        ? '/api/phone-usage/list?show_all=true'
        : '/api/phone-usage/list';
    
    fetch(url)
        .then(r => r.json())
        .then(data => {
            usagesCache = data;
            renderUsageTable(data);
        })
        .catch(err => console.error('Erreur chargement historique:', err));
}

function toggleHistory() {
    showAllHistory = !showAllHistory;
    const btn = document.getElementById('btn-toggle-history');
    
    if (showAllHistory) {
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-warning');
        btn.innerHTML = '<i class="fas fa-filter-circle-xmark"></i> Téléphones empruntés seulement';
    } else {
        btn.classList.remove('btn-warning');
        btn.classList.add('btn-secondary');
        btn.innerHTML = '<i class="fas fa-list"></i> Tous les enregistrements';
    }
    
    loadUsageHistory();
}

function renderUsageTable(usages) {
    const tbody = document.getElementById('usage-tbody');
    
    if (!usages || usages.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">Aucun enregistrement</td></tr>';
        return;
    }

    tbody.innerHTML = usages.map(u => {
        const duration = u.checkin_at_str ? calculateDuration(u.checkout_at, u.checkin_at) : '-';
        const statusBadge = u.is_active 
            ? '<span class="badge bg-warning">En cours</span>' 
            : '<span class="badge bg-secondary">Retourné</span>';

        return `
            <tr>
                <td>
                    <div class="fw-semibold"><a href="#" class="text-decoration-none text-primary" onclick="viewUserFromUsage(${u.user_id}); return false;" style="cursor: pointer;">${u.user_username}</a></div>
                    <small class="text-muted">${u.user_email}</small>
                </td>
                <td>
                    <a href="/phone/${u.phone_id}/history?return_to=/phone-usage" class="text-decoration-none fw-bold text-primary">${u.phone_code}</a>
                    <div><small class="text-muted">${u.phone_brand} ${u.phone_model}</small></div>
                </td>
                <td>${u.checkout_at_str || '-'}</td>
                <td>${u.checkin_at_str || '-'}</td>
                <td>${duration}</td>
                <td>${statusBadge}</td>
                <td>
                    ${u.is_active 
                        ? `<button class="btn btn-sm btn-outline-success" title="Retourner" onclick="openCheckinModal(${u.id}, '${u.phone_code}', '${u.user_username}')"><i class="fas fa-sign-in-alt"></i></button>
                           <button class="btn btn-sm btn-outline-info" title="QR Code" onclick="showPhoneQRCode(${u.phone_id}, '${u.phone_code}')"><i class="fas fa-qrcode"></i></button>`
                        : `<button class="btn btn-sm btn-outline-info" title="QR Code" onclick="showPhoneQRCode(${u.phone_id}, '${u.phone_code}')"><i class="fas fa-qrcode"></i></button>`
                    }
                </td>
            </tr>
        `;
    }).join('');
}

function calculateDuration(checkoutIso, checkinIso) {
    const checkout = new Date(checkoutIso);
    const checkin = new Date(checkinIso);
    const diff = checkin - checkout;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    return `${hours}h ${minutes}m`;
}

function openCheckoutModal() {
    // Load available phones and users
    Promise.all([
        fetch('/api/phones/list').then(r => r.json()),
        fetch('/api/users/list').then(r => r.json())
    ])
    .then(([phonesData, usersData]) => {
        const phones = (phonesData.phones && Array.isArray(phonesData.phones)) ? phonesData.phones : (Array.isArray(phonesData) ? phonesData : []);
        const users = (usersData.users && Array.isArray(usersData.users)) ? usersData.users : (Array.isArray(usersData) ? usersData : []);
        // Only show available phones (not currently checked out)
        const availablePhones = phones.filter(p => {
            // Check if phone is currently checked out
            return !document.querySelector(`[data-phone-id="${p.id}"][data-active="true"]`);
        });

        const userSelect = document.getElementById('user-select');
        const phoneSelect = document.getElementById('phone-select');

        // Populate users (policiers only)
        userSelect.innerHTML = '<option value="">-- Sélectionner un policier --</option>';
        users.filter(u => u.role === 'policier').forEach(user => {
            userSelect.innerHTML += `<option value="${user.id}">${user.username} (${user.email})</option>`;
        });

        // Populate phones
        phoneSelect.innerHTML = '<option value="">-- Sélectionner un téléphone --</option>';
        phones.filter(p => p.status === 'active').forEach(phone => {
            phoneSelect.innerHTML += `<option value="${phone.id}">${phone.phone_code} - ${phone.brand} ${phone.model}</option>`;
        });

        checkoutModalInstance = new bootstrap.Modal(document.getElementById('checkoutModal'));
        checkoutModalInstance.show();
    })
    .catch(err => {
        alert('Erreur lors du chargement des données');
        console.error(err);
    });
}

function submitCheckout() {
    const userId = document.getElementById('user-select').value;
    const phoneId = document.getElementById('phone-select').value;
    const notes = document.getElementById('checkout-notes').value.trim();

    if (!userId || !phoneId) {
        alert('Veuillez sélectionner un policier et un téléphone');
        return;
    }

    fetch('/api/phone-usage/checkout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            user_id: parseInt(userId),
            phone_id: parseInt(phoneId),
            notes: notes
        })
    })
    .then(r => {
        if (!r.ok) throw r;
        return r.json();
    })
    .then(() => {
        if (checkoutModalInstance) checkoutModalInstance.hide();
        document.getElementById('checkout-form').reset();
        loadStats();
        loadUsageHistory();
    })
    .catch(async err => {
        const text = err.json ? await err.json() : {error: 'Erreur'};
        alert(text.error || 'Erreur lors de l\'emprunt');
    });
}

function toggleHistory() {
    showAllHistory = !showAllHistory;
    const btn = document.getElementById('btn-toggle-history');
    const searchInput = document.getElementById('search-usage-code');
    
    if (showAllHistory) {
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-warning');
        btn.innerHTML = '<i class="fas fa-filter-circle-xmark"></i> Téléphones empruntés seulement';
    } else {
        btn.classList.remove('btn-warning');
        btn.classList.add('btn-secondary');
        btn.innerHTML = '<i class="fas fa-list"></i> Tous les enregistrements';
    }
    
    // Clear search when toggling
    searchInput.value = '';
    loadUsageHistory();
}

function filterUsageByCode(searchTerm) {
    const filtered = usagesCache.filter(usage => 
        usage.phone_code.toLowerCase().includes(searchTerm.toLowerCase())
    );
    renderUsageTable(filtered);
}

function openCheckinModal(usageId, phoneCode, userName) {
    pendingCheckinId = usageId;
    document.getElementById('checkin-info').textContent = `Téléphone: ${phoneCode} - Policier: ${userName}`;
    
    checkinModalInstance = new bootstrap.Modal(document.getElementById('checkinModal'));
    checkinModalInstance.show();
}

function showPhoneQRCode(phoneId, phoneCode) {
    const modal = document.getElementById('qrcodeModal');
    if (!modal) {
        console.error('QR Code modal not found');
        return;
    }
    
    document.getElementById('qrcodeModalLabel').textContent = `QR Code - ${phoneCode}`;
    const container = document.getElementById('qrcode-container');
    container.innerHTML = '<p class="text-muted">Chargement du QR code...</p>';
    
    fetch(`/api/phone/${phoneId}/qrcode`)
        .then(r => {
            if (!r.ok) throw new Error('QR code not found');
            return r.blob();
        })
        .then(blob => {
            const url = URL.createObjectURL(blob);
            container.innerHTML = `<img src="${url}" style="max-width: 500px; max-height: 500px;" />`;
            
            // Setup download button
            const downloadBtn = document.getElementById('download-qrcode-btn');
            downloadBtn.href = url;
            downloadBtn.download = `qrcode_${phoneCode}.png`;
        })
        .catch(err => {
            console.error('Error loading QR code:', err);
            container.innerHTML = '<p class="text-danger">Erreur lors du chargement du QR code</p>';
        });
    
    const qrcodeModal = new bootstrap.Modal(modal);
    qrcodeModal.show();
}

function submitCheckin() {
    if (!pendingCheckinId) return;

    fetch(`/api/phone-usage/${pendingCheckinId}/checkin`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    })
    .then(r => {
        if (!r.ok) throw r;
        return r.json();
    })
    .then(() => {
        if (checkinModalInstance) checkinModalInstance.hide();
        pendingCheckinId = null;
        loadStats();
        loadUsageHistory();
    })
    .catch(async err => {
        const text = err.json ? await err.json() : {error: 'Erreur'};
        alert(text.error || 'Erreur lors du retour');
    });
}

// Refresh every 30 seconds
setInterval(() => {
    loadStats();
    loadUsageHistory();
}, 30000);

function viewUserFromUsage(userId) {
    // Fetch user details directly instead of relying on cache
    fetch(`/api/users/${userId}/details`)
        .then(r => {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(user => {
            if (!user) throw new Error('User not found');
            
            // Display user details in a read-only format
            document.getElementById('view-u-username').textContent = escapeHtml(user.username || '');
            document.getElementById('view-u-fullname').textContent = escapeHtml(user.full_name || '');
            document.getElementById('view-u-email').textContent = escapeHtml(user.email || '');
            document.getElementById('view-u-phone').textContent = escapeHtml(user.phone || '');
            document.getElementById('view-u-country').textContent = escapeHtml(user.country || '');
            document.getElementById('view-u-region').textContent = escapeHtml(user.region || '');
            document.getElementById('view-u-role').textContent = user.role ? (user.role === 'administrateur' ? '👤 Administrateur' : user.role === 'policier' ? '🚔 Policier' : '⚖️ Judiciaire') : '';
            document.getElementById('view-u-status').innerHTML = user.is_active ? '<span class="badge bg-success">Actif</span>' : '<span class="badge bg-secondary">Inactif</span>';
            document.getElementById('view-u-created').textContent = escapeHtml(user.created_at || '');
            
            const modal = new bootstrap.Modal(document.getElementById('viewUserModal'));
            modal.show();
        })
        .catch(err => {
            console.error('Error loading user:', err);
            alert('Erreur: ' + (err.message || 'Utilisateur introuvable'));
        });
}

function escapeHtml(s){
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

