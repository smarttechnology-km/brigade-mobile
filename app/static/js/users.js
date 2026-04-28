document.addEventListener('DOMContentLoaded', function(){
    loadUsers();
    const btnNew = document.getElementById('btn-new-user'); if(btnNew) btnNew.addEventListener('click', openNewUserModal);
    const saveBtn = document.getElementById('save-user-btn'); if(saveBtn) saveBtn.addEventListener('click', saveUser);
    const historyFilterBtn = document.getElementById('user-history-filter-btn'); if(historyFilterBtn) historyFilterBtn.addEventListener('click', applyUserHistoryFilter);
    const historyResetBtn = document.getElementById('user-history-reset-btn'); if(historyResetBtn) historyResetBtn.addEventListener('click', resetUserHistoryFilter);
    const historyDayFilter = document.getElementById('user-history-day-filter'); if(historyDayFilter) historyDayFilter.addEventListener('keydown', function(ev){ if(ev.key === 'Enter'){ applyUserHistoryFilter(); } });
    
    // Role change listener to show/hide country/region fields
    const roleSelect = document.getElementById('u-role');
    if(roleSelect) roleSelect.addEventListener('change', updateCountryRegionVisibility);
    
    // Country change listener to populate regions
    const countrySelect = document.getElementById('u-country');
    if(countrySelect) countrySelect.addEventListener('change', updateRegions);
    
    // search input with debounce
    const searchInput = document.getElementById('users-search');
    if(searchInput){
        let t = null;
        searchInput.addEventListener('input', function(){
            if(t) clearTimeout(t);
            t = setTimeout(()=>{
                const q = (this.value || '').trim().toLowerCase();
                if(!q){ renderUsers(usersCache); return; }
                const filtered = usersCache.filter(u=>{
                    return (u.username||'').toLowerCase().includes(q)
                        || (u.full_name||'').toLowerCase().includes(q)
                        || (u.email||'').toLowerCase().includes(q)
                        || (u.phone||'').toLowerCase().includes(q)
                        || (u.country||'').toLowerCase().includes(q)
                        || (u.region||'').toLowerCase().includes(q);
                });
                renderUsers(filtered);
            }, 250);
        });
    }
});

// Regions data for each country
const regionsData = {
    'Grande Comores': ['Moroni', 'Koimbani', 'Foumbouni', 'Mitsamiouli', 'Iconi'],
    'Anjouan': ['Mutsamudu', 'Domoni', 'Tsembéhou', 'Sima'],
    'Moheli': ['Fomboni', 'Nioumachoua']
};

function updateCountryRegionVisibility(){
    const role = document.getElementById('u-role').value;
    const countrySection = document.getElementById('country-section');
    const regionSection = document.getElementById('region-section');
    
    if(role === 'administrateur'){
        // Admin: hide both country and region
        countrySection.style.display = 'none';
        regionSection.style.display = 'none';
    } else if(role === 'judiciaire'){
        // Judiciaire: show country only
        countrySection.style.display = '';
        regionSection.style.display = 'none';
    } else if(role === 'policier'){
        // Policier: show both country and region
        countrySection.style.display = '';
        regionSection.style.display = '';
    }
}

function updateRegions(){
    const country = document.getElementById('u-country').value;
    const regionSelect = document.getElementById('u-region');
    regionSelect.innerHTML = '<option value="">Sélectionner une région</option>';
    if(country && regionsData[country]){
        regionsData[country].forEach(region => {
            const option = document.createElement('option');
            option.value = region;
            option.textContent = region;
            regionSelect.appendChild(option);
        });
    }
}

let usersCache = [];

function loadUsers(){
    fetch('/api/users/list').then(r=>{
        if(!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    }).then(data=>{
        // API returns array directly
        usersCache = Array.isArray(data) ? data : (data.users || []);
        renderUsers(usersCache);
    }).catch(err=>{ 
        console.error('load users failed', err); 
        const tbody = document.getElementById('users-tbody'); 
        if(tbody) tbody.innerHTML = '<tr><td colspan="11" class="text-center text-danger">Erreur chargement</td></tr>'; 
    });
}

function renderUsers(list){
    const tbody = document.getElementById('users-tbody'); 
    if(!tbody) return;
    
    if(!list || list.length===0){ 
        tbody.innerHTML = '<tr><td colspan="11" class="text-center">Aucun utilisateur</td></tr>'; 
        return; 
    }
    
    tbody.innerHTML = list.map((u,i)=>`<tr>
            <td>${i+1}</td>
            <td>${escapeHtml(u.username||'')}</td>
            <td>${escapeHtml(u.full_name||'')}</td>
            <td>${escapeHtml(u.email||'')}</td>
            <td>${escapeHtml(u.phone||'')}</td>
            <td>${escapeHtml(u.country||'')}</td>
            <td>${escapeHtml(u.region||'')}</td>
            <td>${escapeHtml(u.role||'')}</td>
            <td>${u.is_active ? '<span class="badge bg-success">Actif</span>' : '<span class="badge bg-secondary">Inactif</span>'}</td>
            <td>${escapeHtml(u.created_at||'')}</td>
            <td>
              <button class="btn btn-sm btn-outline-primary me-1" data-edit="${u.id}" title="Éditer">
                <i class="fas fa-edit"></i>
              </button>
              <button class="btn btn-sm btn-outline-danger" data-uid="${u.id}" title="Supprimer">
                <i class="fas fa-trash"></i>
              </button>
            </td>
        </tr>`).join('');
    
    tbody.querySelectorAll('button[data-uid]').forEach(b=>b.addEventListener('click', deleteUser));
    tbody.querySelectorAll('button[data-edit]').forEach(b=>b.addEventListener('click', function(){ openEditUser(this.dataset.edit); }));
}

// small helper to avoid HTML injection
function escapeHtml(s){
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function openNewUserModal(){
    document.getElementById('u-id').value='';
    document.getElementById('u-username').value='';
    document.getElementById('u-fullname').value='';
    document.getElementById('u-email').value='';
    document.getElementById('u-phone').value='';
    document.getElementById('u-country').value='';
    document.getElementById('u-region').value='';
    document.getElementById('u-password').value='';
    document.getElementById('u-password-confirm').value='';
    document.getElementById('u-role').value='policier';
    document.getElementById('u-active').checked = true;
    document.getElementById('user-error').textContent='';
    updateCountryRegionVisibility(); // Update visibility based on role
    updateRegions(); // Update region options
    
    // Update modal title
    const modalTitle = document.getElementById('modal-title-text');
    if(modalTitle) modalTitle.textContent = 'Nouvel Utilisateur';
    
    // Show password as required for new user
    const pwdReq = document.getElementById('pwd-required');
    const pwdConfReq = document.getElementById('pwd-confirm-required');
    if(pwdReq) pwdReq.style.display = 'inline';
    if(pwdConfReq) pwdConfReq.style.display = 'inline';
    
    const modal = new bootstrap.Modal(document.getElementById('userModal'));
    modal.show();
}

function openEditUser(id){
    const u = usersCache.find(x=>String(x.id)===String(id));
    if(!u) return alert('Utilisateur introuvable');
    document.getElementById('u-id').value = u.id;
    document.getElementById('u-username').value = u.username;
    document.getElementById('u-fullname').value = u.full_name || '';
    document.getElementById('u-email').value = u.email || '';
    document.getElementById('u-phone').value = u.phone || '';
    document.getElementById('u-country').value = u.country || '';
    document.getElementById('u-region').value = u.region || '';
    updateRegions(); // Populate regions based on selected country
    document.getElementById('u-password').value = '';
    document.getElementById('u-password-confirm').value = '';
    document.getElementById('u-role').value = u.role || 'policier';
    document.getElementById('u-active').checked = !!u.is_active;
    document.getElementById('user-error').textContent='';
    updateCountryRegionVisibility(); // Update visibility based on role
    
    // Update modal title
    const modalTitle = document.getElementById('modal-title-text');
    if(modalTitle) modalTitle.textContent = 'Modifier Utilisateur';
    
    // Hide password required indicators for edit
    const pwdReq = document.getElementById('pwd-required');
    const pwdConfReq = document.getElementById('pwd-confirm-required');
    if(pwdReq) pwdReq.style.display = 'none';
    if(pwdConfReq) pwdConfReq.style.display = 'none';
    
    // Show/hide history tab based on role (only for non-administrators)
    const historyTabContainer = document.getElementById('user-history-tab-container');
    const historyDayFilter = document.getElementById('user-history-day-filter');
    const historyFilterLabel = document.getElementById('user-history-filter-label');
    if(historyTabContainer){
        if(u.role === 'administrateur'){
            historyTabContainer.style.display = 'none';
        } else {
            historyTabContainer.style.display = '';
            if(historyDayFilter) historyDayFilter.value = '';
            if(historyFilterLabel) historyFilterLabel.textContent = 'Aucun filtre appliqué';
            // Load user history
            loadUserHistory(u.id);
        }
    }
    
    const modal = new bootstrap.Modal(document.getElementById('userModal'));
    modal.show();
}

function loadUserHistory(userId, day=''){
    const tbody = document.getElementById('user-history-tbody');
    const historyFilterLabel = document.getElementById('user-history-filter-label');
    if(!tbody) return;
    
    tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Chargement...</td></tr>';
    if(historyFilterLabel){
        historyFilterLabel.textContent = day ? `Filtre actif : ${day}` : 'Aucun filtre appliqué';
    }
    const url = day ? `/api/users/${userId}/history?day=${encodeURIComponent(day)}` : `/api/users/${userId}/history`;
    
    fetch(url)
        .then(r=>{
            if(!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(history=>{
            if(!history || history.length === 0){
                tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Aucun historique</td></tr>';
                return;
            }
            tbody.innerHTML = history.map(h=>`<tr>
                <td><small>${escapeHtml(h.created_at)}</small></td>
                <td><strong>${escapeHtml(h.action)}</strong></td>
                <td><small>${escapeHtml(h.details || '-')}</small></td>
            </tr>`).join('');
        })
        .catch(err=>{
            console.error('Failed to load user history:', err);
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-danger">Erreur chargement historique</td></tr>';
        });
}

function applyUserHistoryFilter(){
    const userId = document.getElementById('u-id').value;
    if(!userId) return;
    const dayFilter = document.getElementById('user-history-day-filter');
    const day = dayFilter ? dayFilter.value.trim() : '';
    loadUserHistory(userId, day);
}

function resetUserHistoryFilter(){
    const userId = document.getElementById('u-id').value;
    if(!userId) return;
    const dayFilter = document.getElementById('user-history-day-filter');
    if(dayFilter) dayFilter.value = '';
    loadUserHistory(userId);
}

function saveUser(){
        const id = document.getElementById('u-id').value;
        const username = document.getElementById('u-username').value.trim();
        const full_name = document.getElementById('u-fullname').value.trim();
        const email = document.getElementById('u-email').value.trim();
        const phone = document.getElementById('u-phone').value.trim();
        const country = document.getElementById('u-country').value.trim();
        const region = document.getElementById('u-region').value.trim();
        const password = document.getElementById('u-password').value;
        const password_confirm = document.getElementById('u-password-confirm').value;
        const role = document.getElementById('u-role').value;
        const is_active = !!document.getElementById('u-active').checked;
        const err = document.getElementById('user-error'); err.textContent='';
        if(!username){ err.textContent = 'Nom d\'utilisateur requis'; return; }
        if(password && password !== password_confirm){ err.textContent = 'Les mots de passe ne correspondent pas'; return; }

        const payload = { username, role, full_name, email, phone, is_active };
        
        // Add country/region based on role
        if(role === 'policier'){
            payload.country = country;
            payload.region = region;
        } else if(role === 'judiciaire'){
            payload.country = country;
            payload.region = ''; // Don't send region for judiciaire
        }
        // For admin, don't send country or region
        
        if(password) payload.password = password;

        const url = id ? `/api/users/${id}/update` : '/api/users/create';
        fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) })
      .then(r=>{
        if(!r.ok) return r.json().then(x=>{ throw x; }); return r.json();
      }).then(res=>{
        const modalEl = document.getElementById('userModal'); const bs = bootstrap.Modal.getInstance(modalEl); if(bs) bs.hide(); loadUsers();
      }).catch(e=>{ err.textContent = e.error || 'Erreur enregistrement utilisateur'; });
}

function deleteUser(ev){
    const id = this.dataset.uid;
    if(!confirm('Supprimer cet utilisateur ?')) return;
    fetch(`/api/users/${id}/delete`, { method:'POST' }).then(r=>{
        if(!r.ok) return r.json().then(x=>{ throw x; }); return r.json();
    }).then(res=>{ loadUsers(); }).catch(e=>{ alert(e.error || 'Erreur suppression'); });
}


