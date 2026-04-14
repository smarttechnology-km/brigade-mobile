document.addEventListener('DOMContentLoaded', function() {
    if (typeof phoneId !== 'undefined') {
        loadPhoneHistory();
    }
    
    // Ajouter listener pour le clic sur le policier actuel
    document.addEventListener('click', function(e) {
        if (e.target.id === 'stat-current-user-link') {
            e.preventDefault();
            const userId = e.target.dataset.userId;
            if (userId) {
                openUserModal(userId);
            }
        }
    });
});

function loadPhoneHistory() {
    fetch(`/api/phone/${phoneId}/usage-history`)
        .then(r => {
            if (!r.ok) throw r;
            return r.json();
        })
        .then(data => {
            renderPhoneDetails(data.phone);
            renderStatistics(data.usages);
            renderHistoryTable(data.usages);
        })
        .catch(err => {
            console.error('Erreur chargement historique:', err);
            document.getElementById('history-tbody').innerHTML = '<tr><td colspan="7" class="text-center text-danger py-4">Erreur lors du chargement</td></tr>';
        });
}

function renderPhoneDetails(phone) {
    document.getElementById('phone-title').textContent = `${phone.phone_code} - ${phone.brand} ${phone.model}`;
    document.getElementById('detail-code').textContent = phone.phone_code;
    document.getElementById('detail-brand').textContent = phone.brand;
    document.getElementById('detail-model').textContent = phone.model;
    document.getElementById('detail-color').textContent = phone.color || '-';
    document.getElementById('detail-island').textContent = phone.island || '-';
    
    const statusBadge = phone.status === 'active'
        ? '<span class="badge bg-success"><i class="fas fa-check-circle me-1"></i>Actif</span>'
        : '<span class="badge bg-danger"><i class="fas fa-times-circle me-1"></i>Inactif</span>';
    document.getElementById('detail-status').innerHTML = statusBadge;
}

function renderStatistics(usages) {
    const totalUses = usages.length;
    const activeUse = usages.find(u => !u.checkin_at);
    
    document.getElementById('stat-total-uses').textContent = totalUses;
    document.getElementById('stat-active-use').textContent = activeUse ? 'Oui' : 'Non';
    
    // Calculate total time used
    let totalMinutes = 0;
    usages.forEach(u => {
        if (u.checkin_at) {
            const checkout = new Date(u.checkout_at);
            const checkin = new Date(u.checkin_at);
            totalMinutes += (checkin - checkout) / (1000 * 60);
        }
    });
    
    const hours = Math.floor(totalMinutes / 60);
    const minutes = Math.floor(totalMinutes % 60);
    document.getElementById('stat-total-time').textContent = `${hours}h ${minutes}m`;
    
    if (activeUse) {
        document.getElementById('stat-current-user').innerHTML = `<a href="#" id="stat-current-user-link" data-user-id="${activeUse.user_id}" class="text-primary" style="cursor:pointer;">${activeUse.user_username}</a>`;
    } else {
        document.getElementById('stat-current-user').textContent = '-';
    }
}

function renderHistoryTable(usages) {
    const tbody = document.getElementById('history-tbody');
    
    if (!usages || usages.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">Aucun historique d\'utilisation</td></tr>';
        return;
    }

    tbody.innerHTML = usages.map((u, index) => {
        const duration = u.checkin_at ? calculateDuration(u.checkout_at, u.checkin_at) : 'En cours...';
        const statusBadge = u.is_active 
            ? '<span class="badge bg-warning text-dark"><i class="fas fa-clock me-1"></i>En cours</span>' 
            : '<span class="badge bg-secondary"><i class="fas fa-check me-1"></i>Retourné</span>';

        return `
            <tr>
                <td><strong>${index + 1}</strong></td>
                <td>
                    <div class="fw-semibold">${u.user_username}</div>
                    <small class="text-muted">${u.user_role}</small>
                </td>
                <td>
                    <div>${u.checkout_at_str || '-'}</div>
                </td>
                <td>
                    <div>${u.checkin_at_str || '-'}</div>
                </td>
                <td>
                    <strong>${duration}</strong>
                </td>
                <td>
                    <small>${u.notes || '-'}</small>
                </td>
                <td>
                    ${statusBadge}
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

function openUserModal(userId) {
    fetch(`/api/users/${userId}/details`)
        .then(r => {
            if (!r.ok) throw new Error('Utilisateur non trouvé');
            return r.json();
        })
        .then(data => {
            // Les données sont retournées directement, pas dans une clé "user"
            const user = data;
            
            // Remplir les champs de la modal
            document.getElementById('modal-username').textContent = user.username;
            document.getElementById('modal-fullname').textContent = user.full_name || '-';
            document.getElementById('modal-email').textContent = user.email || '-';
            document.getElementById('modal-phone').textContent = user.phone || '-';
            document.getElementById('modal-country').textContent = user.country || '-';
            document.getElementById('modal-region').textContent = user.region || '-';
            
            // Traduire le rôle
            const roleMap = {
                'administrateur': '👤 Administrateur',
                'policier': '🚔 Policier',
                'judiciaire': '⚖️ Judiciaire'
            };
            document.getElementById('modal-role').textContent = roleMap[user.role] || user.role || '-';
            
            // Afficher le statut
            const statusBadge = user.is_active 
                ? '<span class="badge bg-success"><i class="fas fa-check-circle me-1"></i>Actif</span>'
                : '<span class="badge bg-danger"><i class="fas fa-times-circle me-1"></i>Inactif</span>';
            document.getElementById('modal-status').innerHTML = statusBadge;
            
            // Afficher la modal
            const modal = new bootstrap.Modal(document.getElementById('userDetailsModal'));
            modal.show();
        })
        .catch(err => {
            console.error('Erreur chargement user:', err);
            alert('Erreur lors du chargement des détails du policier');
        });
}
