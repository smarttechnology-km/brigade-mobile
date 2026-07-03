var phoneModalInstance = window.phoneModalInstance || null;
window.phoneModalInstance = phoneModalInstance;
var phonesCache = window.phonesCache || [];
window.phonesCache = phonesCache;

document.addEventListener('DOMContentLoaded', function() {
    // Load phones on page load
    const addBtn = document.getElementById('btn-add-phone');
    if (addBtn) {
        loadPhones();
        addBtn.addEventListener('click', function() {
            openPhoneModal();
        });
    }

    const saveBtn = document.getElementById('save-phone-btn');
    if (saveBtn) saveBtn.addEventListener('click', savePhone);

    // Search functionality
    const searchInput = document.getElementById('search-phone-code');
    const clearBtn = document.getElementById('btn-clear-search');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            filterPhonesByCode(this.value);
        });
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            document.getElementById('search-phone-code').value = '';
            filterPhonesByCode('');
        });
    }

    // Country filter listener for admin
    const countryFilter = document.getElementById('phones-country-filter');
    if (countryFilter) {
        countryFilter.addEventListener('change', loadPhones);
    }

    // Ensure we clean up modal when it is hidden
    const modalEl = document.getElementById('phoneModal');
    if (modalEl) {
        modalEl.addEventListener('hidden.bs.modal', function (event) {
            cleanupModalResources();
        });
    }
});

function loadPhones() {
    const countryFilter = document.getElementById('phones-country-filter');
    const country = countryFilter ? countryFilter.value : '';
    const url = country ? `/api/phones/list?country=${encodeURIComponent(country)}` : '/api/phones/list';
    fetch(url)
        .then(r => r.json())
        .then(data => {
            phonesCache = (data.phones && Array.isArray(data.phones)) ? data.phones : (Array.isArray(data) ? data : []);
            renderPhonesTable(phonesCache);
        })
        .catch(err => console.error('Erreur chargement téléphones:', err));
}

function renderPhonesTable(phones) {
    const tbody = document.getElementById('phones-tbody');
    if (!phones || phones.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Aucun téléphone</td></tr>';
        return;
    }
    tbody.innerHTML = phones.map((p, i) => `
        <tr>
            <td><a href="/phone/${p.id}/history?return_to=/phones" class="text-decoration-none fw-bold text-primary">${p.phone_code}</a></td>
            <td><strong>${p.brand}</strong></td>
            <td>${p.model}</td>
            <td>${p.color || '-'}</td>
            <td><span class="badge ${statusBadgeClass(p.status)}">${statusLabel(p.status)}</span></td>
            <td>${p.created_at_str || ''}</td>
            <td>
                <button class="btn btn-sm btn-outline-info" title="QR Code" onclick="showPhoneQRCode(${p.id}, '${p.phone_code}')"><i class="fas fa-qrcode"></i></button>
                <button class="btn btn-sm btn-outline-warning" title="Éditer" onclick="editPhone(${p.id})"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" title="Supprimer" onclick="removePhone(${p.id})"><i class="fas fa-trash"></i></button>
            </td>
        </tr>
    `).join('');
}

function filterPhonesByCode(searchTerm) {
    const filtered = phonesCache.filter(phone => 
        phone.phone_code.toLowerCase().includes(searchTerm.toLowerCase())
    );
    renderPhonesTable(filtered);
}

function openPhoneModal(phone) {
    // reset form
    document.getElementById('phone-form').reset();
    document.getElementById('phone-id').value = '';
    document.getElementById('display-phone-code').value = '';
    
    // Update modal title with icon
    const modalTitle = document.getElementById('phoneModalLabel');
    if(phone) {
        modalTitle.innerHTML = '<i class="fas fa-edit me-2"></i><span>Éditer le téléphone</span>';
    } else {
        modalTitle.innerHTML = '<i class="fas fa-mobile-alt me-2"></i><span>Ajouter un téléphone</span>';
    }

    if (phone) {
        document.getElementById('phone-id').value = phone.id;
        document.getElementById('display-phone-code').value = phone.phone_code || '-';
        document.getElementById('brand').value = phone.brand;
        document.getElementById('model').value = phone.model;
        document.getElementById('color').value = phone.color || '';
        if(document.getElementById('island')) document.getElementById('island').value = phone.island || '';
        document.getElementById('status').value = phone.status || 'active';
        document.getElementById('notes').value = phone.notes || '';
    }

    // initialize and show modal
    phoneModalInstance = new bootstrap.Modal(document.getElementById('phoneModal'));
    phoneModalInstance.show();
}

function savePhone() {
    const pid = document.getElementById('phone-id').value;
    
    const payload = {
        brand: document.getElementById('brand').value.trim(),
        model: document.getElementById('model').value.trim(),
        color: document.getElementById('color').value.trim(),
        island: document.getElementById('island') ? document.getElementById('island').value : '',
        status: document.getElementById('status').value,
        notes: document.getElementById('notes').value.trim()
    };

    if (!payload.brand || !payload.model) {
        alert('Veuillez remplir les champs requis (Marque et Modèle)');
        return;
    }

    if (pid) {
        // update
        fetch(`/api/phones/${pid}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) throw r;
            return r.json();
        }).then(() => {
            safeHideModal();
            loadPhones();
        }).catch(async err => {
            const text = err.json ? await err.json() : {error: 'Erreur'};
            alert(text.error || 'Erreur lors de la mise à jour');
        });
    } else {
        // create
        fetch('/api/phones', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) throw r;
            return r.json();
        }).then(() => {
            safeHideModal();
            loadPhones();
        }).catch(async err => {
            const text = err.json ? await err.json() : {error: 'Erreur'};
            alert(text.error || 'Erreur lors de la création');
        });
    }
}

function safeHideModal(){
    try{
        if(phoneModalInstance){
            phoneModalInstance.hide();
            // dispose after short delay to allow hide animation
            setTimeout(()=>{
                try{
                    phoneModalInstance.dispose();
                }catch(e){}
                phoneModalInstance = null;
                cleanupModalResources();
            }, 250);
        } else {
            // fallback: try to hide via getInstance
            const inst = bootstrap.Modal.getInstance(document.getElementById('phoneModal'));
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
        try{ if(phoneModalInstance) phoneModalInstance.dispose(); }catch(e){}
        phoneModalInstance = null;
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

function editPhone(id) {
    fetch(`/api/phones/${id}`)
        .then(r => r.json())
        .then(p => openPhoneModal(p))
        .catch(err => console.error('Erreur get phone:', err));
}

function removePhone(id) {
    if (!confirm('Confirmer la suppression de ce téléphone ?')) return;
    fetch(`/api/phones/${id}`, {method: 'DELETE'})
        .then(r => r.json())
        .then(() => loadPhones())
        .catch(err => console.error('Erreur suppression:', err));
}

function statusBadgeClass(s){ 
    if(s==='active') return 'bg-success'; 
    if(s==='inactive') return 'bg-danger'; 
    return 'bg-secondary'; 
}

function statusLabel(s){ 
    if(s==='active') return 'Actif'; 
    if(s==='inactive') return 'Inactif'; 
    return s; 
}

function showPhoneQRCode(phoneId, phoneCode) {
    const modal = document.getElementById('qrcodeModal');
    const container = document.getElementById('qrcode-container');
    const downloadBtn = document.getElementById('download-qrcode-btn');
    
    // Set title
    document.getElementById('qrcodeModalLabel').textContent = `QR Code - ${phoneCode}`;
    
    // Load QR code image
    container.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Chargement...</span></div></div>';
    
    const img = document.createElement('img');
    img.src = `/api/phone/${phoneId}/qrcode`;
    img.alt = `QR Code ${phoneCode}`;
    img.style.maxWidth = '100%';
    img.style.maxHeight = '400px';
    img.onload = function() {
        container.innerHTML = '';
        container.appendChild(img);
    };
    img.onerror = function() {
        container.innerHTML = '<div class="alert alert-danger">Erreur lors du chargement du QR code</div>';
    };
    
    // Set download button
    downloadBtn.href = `/api/phone/${phoneId}/qrcode`;
    downloadBtn.download = `phone_${phoneCode}_qrcode.png`;
    
    // Show modal
    const qrcodeModal = new bootstrap.Modal(modal);
    qrcodeModal.show();
}

