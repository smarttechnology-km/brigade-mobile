/**
 * Insurance Accounts Management
 */

let insuranceAccountsCache = [];
let insurancesForAccounts = [];
let editingInsuranceAccountId = null;

document.addEventListener('DOMContentLoaded', function() {
    console.log('Insurance accounts script loaded');
    
    const settingsModal = document.getElementById('settingsModal');
    if (settingsModal) {
        settingsModal.addEventListener('show.bs.modal', function() {
            loadInsuranceAccounts();
            loadInsurancesForSelect();
        });
    }
});

function loadInsurancesForSelect() {
    console.log('Loading insurances for select...');
    fetch('/api/vehicles/insurances', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) throw new Error('Failed to load insurances');
        return r.json();
    })
    .then(data => {
        insurancesForAccounts = data.insurances || [];
        populateAccountInsuranceSelect();
    })
    .catch(err => console.error('Error loading insurances:', err));
}

function populateAccountInsuranceSelect() {
    const select = document.getElementById('account_insurance_select');
    if (!select) return;
    
    select.innerHTML = '<option value="">-- Sélectionner une Compagnie --</option>' +
        insurancesForAccounts.map(ins => 
            `<option value="${ins.id}">${ins.company_name} (${ins.island || 'N/A'})</option>`
        ).join('');
}

function loadInsuranceAccounts() {
    console.log('Loading insurance accounts...');
    fetch('/api/vehicles/insurance-accounts', {
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) {
            // Non-admin users don't have access
            console.log('Current user is not admin');
            document.getElementById('insurance-accounts-tab').style.display = 'none';
            return null;
        }
        return r.json();
    })
    .then(data => {
        if (!data) return;
        insuranceAccountsCache = data.accounts || [];
        console.log('Loaded ' + insuranceAccountsCache.length + ' insurance accounts');
        renderInsuranceAccountsTable();
    })
    .catch(err => {
        console.error('Error loading insurance accounts:', err);
        document.getElementById('insurance-accounts-tab').style.display = 'none';
    });
}

function renderInsuranceAccountsTable() {
    const tbody = document.getElementById('insurance-accounts-tbody');
    if (!tbody) return;
    
    if (insuranceAccountsCache.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Aucun compte d\'assurance</td></tr>';
        return;
    }
    
    tbody.innerHTML = insuranceAccountsCache.map(acc => `
        <tr>
            <td><strong>${acc.insurance_name || 'N/A'}</strong></td>
            <td>${acc.username}</td>
            <td>${acc.contact_person || '-'}</td>
            <td>${acc.contact_email || '-'}</td>
            <td>
                <span class="badge ${acc.is_active ? 'bg-success' : 'bg-danger'}">
                    ${acc.is_active ? 'Actif' : 'Inactif'}
                </span>
            </td>
            <td>
                <button class="btn btn-sm btn-outline-warning" onclick="editInsuranceAccount(${acc.id})" title="Éditer">
                    <i class="fas fa-edit"></i>
                </button>
                <button class="btn btn-sm ${acc.is_active ? 'btn-outline-secondary' : 'btn-outline-success'}" onclick="toggleInsuranceAccountStatus(${acc.id}, ${acc.is_active})" title="${acc.is_active ? 'Désactiver' : 'Activer'}">
                    <i class="fas ${acc.is_active ? 'fa-user-slash' : 'fa-user-check'}"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteInsuranceAccount(${acc.id})" title="Supprimer">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function addInsuranceAccount() {
    if (editingInsuranceAccountId) {
        updateInsuranceAccount(editingInsuranceAccountId);
        return;
    }

    const insuranceId = document.getElementById('account_insurance_select').value;
    const username = document.getElementById('account_username_input').value.trim();
    const password = document.getElementById('account_password_input').value.trim();
    const contactPerson = document.getElementById('account_contact_person_input').value.trim();
    const contactEmail = document.getElementById('account_contact_email_input').value.trim();
    const contactPhone = document.getElementById('account_contact_phone_input').value.trim();
    const isActive = !!document.getElementById('account_is_active_input').checked;
    
    if (!insuranceId || !username || !password) {
        alert('Veuillez remplir: Compagnie, Nom d\'utilisateur et Mot de passe');
        return;
    }
    
    const payload = {
        insurance_id: parseInt(insuranceId),
        username: username,
        password: password,
        contact_person: contactPerson,
        contact_email: contactEmail,
        contact_phone: contactPhone,
        is_active: isActive
    };
    
    fetch('/api/vehicles/insurance-accounts', {
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
        console.log('Insurance account added:', data);
        // Clear inputs
        document.getElementById('account_insurance_select').value = '';
        document.getElementById('account_username_input').value = '';
        document.getElementById('account_password_input').value = '';
        document.getElementById('account_contact_person_input').value = '';
        document.getElementById('account_contact_email_input').value = '';
        document.getElementById('account_contact_phone_input').value = '';
        document.getElementById('account_is_active_input').checked = true;
        // Reload accounts
        loadInsuranceAccounts();
    })
    .catch(err => {
        console.error('Error adding insurance account:', err);
        alert(err.error || 'Erreur lors de l\'ajout du compte');
    });
}

function editInsuranceAccount(id) {
    const account = insuranceAccountsCache.find(a => a.id === id);
    if (!account) return;
    
    // Pre-fill form
    const select = document.getElementById('account_insurance_select');
    // Find insurance ID by name
    const insurance = insurancesForAccounts.find(i => i.company_name === account.insurance_name);
    if (insurance) {
        select.value = insurance.id;
    }
    
    document.getElementById('account_username_input').value = account.username;
    document.getElementById('account_password_input').value = '';
    document.getElementById('account_password_input').placeholder = 'Laisser vide pour ne pas changer';
    document.getElementById('account_contact_person_input').value = account.contact_person || '';
    document.getElementById('account_contact_email_input').value = account.contact_email || '';
    document.getElementById('account_contact_phone_input').value = account.contact_phone || '';
    document.getElementById('account_is_active_input').checked = !!account.is_active;
    editingInsuranceAccountId = id;
    
    // Change button to update
    const addBtn = document.getElementById('insurance-account-submit-btn');
    if (addBtn) {
        addBtn.onclick = function() { addInsuranceAccount(); };
        addBtn.innerHTML = '<i class="fas fa-save me-1"></i>Mettre à jour';
    }
}

function updateInsuranceAccount(id) {
    const insuranceId = document.getElementById('account_insurance_select').value;
    const username = document.getElementById('account_username_input').value.trim();
    const contactPerson = document.getElementById('account_contact_person_input').value.trim();
    const contactEmail = document.getElementById('account_contact_email_input').value.trim();
    const contactPhone = document.getElementById('account_contact_phone_input').value.trim();
    const password = document.getElementById('account_password_input').value.trim();
    const isActive = !!document.getElementById('account_is_active_input').checked;

    if (!insuranceId || !username) {
        alert('Veuillez remplir: Compagnie et Nom d\'utilisateur');
        return;
    }
    
    const payload = {
        insurance_id: parseInt(insuranceId),
        username: username,
        contact_person: contactPerson,
        contact_email: contactEmail,
        contact_phone: contactPhone,
        is_active: isActive
    };
    
    // Only include password if provided
    if (password) {
        payload.password = password;
    }
    
    fetch(`/api/vehicles/insurance-accounts/${id}`, {
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
        console.log('Insurance account updated:', data);
        // Clear inputs
        document.getElementById('account_insurance_select').value = '';
        document.getElementById('account_username_input').value = '';
        document.getElementById('account_password_input').value = '';
        document.getElementById('account_contact_person_input').value = '';
        document.getElementById('account_contact_email_input').value = '';
        document.getElementById('account_contact_phone_input').value = '';
        document.getElementById('account_is_active_input').checked = true;
        editingInsuranceAccountId = null;
        // Reset button
        const addBtn = document.getElementById('insurance-account-submit-btn');
        if (addBtn) {
            addBtn.onclick = function() { addInsuranceAccount(); };
            addBtn.innerHTML = '<i class="fas fa-plus me-1"></i>Ajouter';
        }
        // Reload accounts
        loadInsuranceAccounts();
    })
    .catch(err => {
        console.error('Error updating insurance account:', err);
        alert(err.error || 'Erreur lors de la mise à jour');
    });
}

function toggleInsuranceAccountStatus(id, currentlyActive) {
    const action = currentlyActive ? 'désactiver' : 'activer';
    if (!confirm(`Voulez-vous ${action} ce compte d'assurance ?`)) {
        return;
    }

    fetch(`/api/vehicles/insurance-accounts/${id}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify({
            is_active: !currentlyActive
        })
    })
    .then(r => {
        if (!r.ok) return r.json().then(e => { throw e; });
        return r.json();
    })
    .then(() => {
        loadInsuranceAccounts();
    })
    .catch(err => {
        console.error('Error toggling insurance account status:', err);
        alert(err.error || 'Erreur lors du changement de statut');
    });
}

function deleteInsuranceAccount(id) {
    if (!confirm('Êtes-vous sûr de vouloir supprimer ce compte d\'assurance?')) {
        return;
    }
    
    fetch(`/api/vehicles/insurance-accounts/${id}`, {
        method: 'DELETE',
        credentials: 'same-origin'
    })
    .then(r => {
        if (!r.ok) return r.json().then(e => { throw e; });
        return r.json();
    })
    .then(data => {
        console.log('Insurance account deleted:', data);
        loadInsuranceAccounts();
    })
    .catch(err => {
        console.error('Error deleting insurance account:', err);
        alert(err.error || 'Erreur lors de la suppression');
    });
}
