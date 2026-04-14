document.addEventListener('DOMContentLoaded', function(){
    // Pagination variables
    window.finesCurrentPage = 1;
    window.finesCurrentItems = [];
    window.FINES_PER_PAGE = 20;
    
    // initial load
    loadFineTypes();
    // apply possible URL query params (e.g. ?q=ABC-123)
    try{
        const params = new URLSearchParams(window.location.search);
        const qparam = params.get('q');
        const paidParam = params.get('paid');
        if(qparam){
            const el = document.getElementById('fines-search'); if(el) el.value = qparam;
            // if search was prefilled from URL, ensure clear button is visible
            try{ const cb = document.getElementById('clear-fines-search'); if(cb) cb.style.display = (qparam && qparam.length) ? 'inline-block' : 'none'; }catch(e){}
            if(paidParam === 'true' || paidParam === 'false'){
                // set active filter button to reflect paid param
                try{
                    const filterGroup = document.getElementById('fines-filter-group');
                    if(filterGroup){
                        filterGroup.querySelectorAll('button[data-filter]').forEach(b=>b.classList.remove('active'));
                        const btnType = (paidParam === 'true') ? 'paid' : 'unpaid';
                        const btn = filterGroup.querySelector(`button[data-filter="${btnType}"]`);
                        if(btn) btn.classList.add('active');
                    }
                }catch(e){}
                loadFines(qparam.trim(), paidParam === 'true');
            } else {
                loadFines(qparam.trim(), null);
            }
        } else {
            loadFines();
        }
    }catch(e){
        loadFines();
    }
    const form = document.getElementById('fines-create-form');
    if(form) form.addEventListener('submit', submitFineFromForm);
    // clear/reset controls
    const clearPlateBtn = document.getElementById('clear-fine-plate');
    if(clearPlateBtn){
        clearPlateBtn.addEventListener('click', function(){
            const el = document.getElementById('fine-vehicle-plate');
            if(el){ el.value = ''; el.focus(); }
            // clear validation state
            const vid = document.getElementById('fine-vehicle-id'); if(vid) vid.value = '';
            const status = document.getElementById('fine-plate-status'); if(status) { status.textContent=''; status.className='text-muted small'; }
            const createBtn = document.getElementById('create-fine-btn'); if(createBtn) createBtn.disabled = true;
        });
    }
    const resetFormBtn = document.getElementById('reset-fine-form');
    if(resetFormBtn){
        resetFormBtn.addEventListener('click', function(){
            const frm = document.getElementById('fines-create-form');
            if(frm) frm.reset();
            const vid = document.getElementById('fine-vehicle-id'); if(vid) vid.value = '';
            const status = document.getElementById('fine-plate-status'); if(status) { status.textContent=''; status.className='text-muted small'; }
            const createBtn = document.getElementById('create-fine-btn'); if(createBtn) createBtn.disabled = true;
        });
    }
    const typeForm = document.getElementById('fine-type-form');
    if(typeForm) typeForm.addEventListener('submit', submitFineTypeForm);
    // reload fine types when the modal is shown (keeps list fresh)
    const modalEl = document.getElementById('fine-types-modal');
    if(modalEl){
        modalEl.addEventListener('show.bs.modal', function(){
            try{ 
                // reset form to add mode when opening modal
                document.getElementById('fine-type-form').reset();
                document.getElementById('fine-type-id').value = '';
                toggleFineTypeFormAddMode(true);
                loadFineTypes();
            }catch(e){console.error(e);} 
        });
    }

    // search box binding (debounced)
    const searchEl = document.getElementById('fines-search');
    let searchTimer = null;
    if(searchEl){
        searchEl.addEventListener('input', function(e){
            const q = e.target.value || '';
            if(searchTimer) clearTimeout(searchTimer);
            searchTimer = setTimeout(()=>{
                // respect current filter selection
                const filter = document.querySelector('#fines-filter-group .active');
                const fval = filter ? filter.dataset.filter : 'all';
                if(fval === 'paid') loadFines(q.trim(), true);
                else if(fval === 'unpaid') loadFines(q.trim(), false);
                else loadFines(q.trim(), null);
            }, 250);
            // toggle clear button visibility
            try{
                const cb = document.getElementById('clear-fines-search'); if(cb) cb.style.display = (q && q.length) ? 'inline-block' : 'none';
            }catch(e){}
        });
    }

    // clear search button handler — fully reset filters and data
    const clearSearchBtn = document.getElementById('clear-fines-search');
    if(clearSearchBtn){
        clearSearchBtn.addEventListener('click', function(){
            const el = document.getElementById('fines-search');
            if(el){ el.value = ''; el.focus(); }
            // hide button
            clearSearchBtn.style.display = 'none';
            // reset filter buttons to 'all'
            try{
                const fg = document.getElementById('fines-filter-group');
                if(fg){
                    fg.querySelectorAll('button[data-filter]').forEach(b=>b.classList.remove('active'));
                    const allBtn = fg.querySelector('button[data-filter="all"]');
                    if(allBtn) allBtn.classList.add('active');
                }
            }catch(e){ console.error('Erreur reset filtres', e); }
            // remove query params from URL so link becomes /fines
            try{ history.replaceState(null, '', '/fines'); }catch(e){}
            // reload full unfiltered list (reinitialise les données)
            loadFines('', null);
        });
    }

    // Plate input validation: check if vehicle exists in DB
    const plateEl = document.getElementById('fine-vehicle-plate');
    const plateStatusEl = document.getElementById('fine-plate-status');
    const vehicleIdEl = document.getElementById('fine-vehicle-id');
    const createBtnEl = document.getElementById('create-fine-btn');
    let plateTimer = null;
    function checkPlateExists(plate){
        if(!plate || plate.trim().length===0){
            if(vehicleIdEl) vehicleIdEl.value = '';
            if(plateStatusEl){ plateStatusEl.textContent = ''; plateStatusEl.className='text-muted small'; }
            if(createBtnEl) createBtnEl.disabled = true;
            return;
        }
        fetch(`/api/vehicles/query?q=${encodeURIComponent(plate)}`)
            .then(r=>{ if(!r.ok) throw new Error('Recherche véhicule échouée'); return r.json(); })
            .then(list=>{
                if(!Array.isArray(list) || list.length===0){
                    if(vehicleIdEl) vehicleIdEl.value = '';
                    if(plateStatusEl){ plateStatusEl.textContent = 'Véhicule introuvable'; plateStatusEl.className='text-danger small'; }
                    if(createBtnEl) createBtnEl.disabled = true;
                    return;
                }
                const plateLower = plate.toLowerCase();
                let vehicle = list.find(v => v.license_plate && v.license_plate.toLowerCase() === plateLower) || list[0];
                if(vehicle){
                    if(vehicleIdEl) vehicleIdEl.value = vehicle.id;
                    if(plateStatusEl){ plateStatusEl.textContent = `Véhicule trouvé: ${vehicle.license_plate}` + (vehicle.owner_name ? ` — ${vehicle.owner_name}` : ''); plateStatusEl.className='text-success small'; }
                    if(createBtnEl) createBtnEl.disabled = false;
                } else {
                    if(vehicleIdEl) vehicleIdEl.value = '';
                    if(plateStatusEl){ plateStatusEl.textContent = 'Véhicule introuvable'; plateStatusEl.className='text-danger small'; }
                    if(createBtnEl) createBtnEl.disabled = true;
                }
            }).catch(err=>{
                console.error('Erreur vérification immatriculation', err);
                if(vehicleIdEl) vehicleIdEl.value = '';
                if(plateStatusEl){ plateStatusEl.textContent = 'Erreur vérification'; plateStatusEl.className='text-danger small'; }
                if(createBtnEl) createBtnEl.disabled = true;
            });
    }
    if(plateEl){
        plateEl.addEventListener('input', function(e){
            const v = e.target.value || '';
            if(plateTimer) clearTimeout(plateTimer);
            plateTimer = setTimeout(()=>{ checkPlateExists(v.trim()); }, 400);
        });
        plateEl.addEventListener('blur', function(e){ checkPlateExists((e.target.value||'').trim()); });
    }

    // filter buttons (Tous / Payées / Impayées)
    const filterGroup = document.getElementById('fines-filter-group');
    if(filterGroup){
        filterGroup.addEventListener('click', function(e){
            const btn = e.target.closest('button[data-filter]');
            if(!btn) return;
            // toggle active class
            filterGroup.querySelectorAll('button[data-filter]').forEach(b=>b.classList.remove('active'));
            btn.classList.add('active');
            const f = btn.dataset.filter;
            const q = (document.getElementById('fines-search')||{value:''}).value.trim();
            if(f === 'paid') loadFines(q, true);
            else if(f === 'unpaid') loadFines(q, false);
            else loadFines(q, null);
        });
    }
});

function loadFines(){
    // default: no query
    loadFinesWithParams('', null);
}

function loadFines(q, paid){
    loadFinesWithParams(q || '', paid === undefined ? null : paid);
}

function loadFinesWithParams(q, paid){
    let url = '/api/vehicles/fines/all';
    const parts = [];
    if(q) parts.push('q=' + encodeURIComponent(q));
    if(paid !== null && paid !== undefined) parts.push('paid=' + (paid ? 'true' : 'false'));
    if(parts.length) url += '?' + parts.join('&');

    fetch(url)
        .then(r=>r.json())
        .then(data=>{
            renderFinesTable(data);
        }).catch(err=>{
            console.error('Erreur chargement amandes',err);
                document.getElementById('fines-tbody').innerHTML = '<tr><td colspan="8" class="text-center text-muted">Erreur chargement</td></tr>';
        });
}

function renderFinesTable(items){
    const tbody = document.getElementById('fines-tbody');
    if(!items || items.length===0){
           tbody.innerHTML = '<tr><td colspan="8" class="text-center">Aucune amande</td></tr>';
           updateFinesPaginationInfo(0, 0, 0);
        return;
    }
    
    // Store items and reset to page 1
    window.finesCurrentItems = items;
    window.finesCurrentPage = 1;
    displayFinesPage();
}

function displayFinesPage() {
    const items = window.finesCurrentItems || [];
    const tbody = document.getElementById('fines-tbody');
    
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">Aucune amande</td></tr>';
        updateFinesPaginationInfo(0, 0, 0);
        return;
    }
    
    // Calculate pagination
    const totalPages = Math.ceil(items.length / window.FINES_PER_PAGE);
    const startIdx = (window.finesCurrentPage - 1) * window.FINES_PER_PAGE;
    const endIdx = Math.min(startIdx + window.FINES_PER_PAGE, items.length);
    const itemsOnPage = items.slice(startIdx, endIdx);
    
    function formatDateTime(dt){
        if(!dt) return '';
        try{
            const d = new Date(dt);
            if(isNaN(d)) return dt;
            const pad = (n) => String(n).padStart(2, '0');
            const day = pad(d.getDate());
            const month = pad(d.getMonth() + 1);
            const year = d.getFullYear();
            const hours = pad(d.getHours());
            const minutes = pad(d.getMinutes());
            return `${day}/${month}/${year} ${hours}:${minutes}`;
        }catch(e){ return dt; }
    }

    tbody.innerHTML = itemsOnPage.map((f,i)=>{
        return `<tr class="fines-table-row">
            <td>${startIdx + i + 1}</td>
            <td><strong>${f.license_plate || f.vehicle_id}</strong></td>
            <td>${Math.round(f.amount)} KMF</td>
            <td>${f.reason}</td>
            <td>${f.officer||''}</td>
            <td>${formatDateTime(f.issued_at)}</td>
            <td>${f.paid ? '<span class="status-badge-paid">Payée</span>' : '<span class="status-badge-unpaid">Impayée</span>'}</td>
            <td>
              ${f.track_token ? `<a class="btn btn-sm btn-outline-primary me-1" href="/track/${f.track_token}"><i class="fas fa-location-arrow me-1"></i>Track</a>` : ''}
            </td>
            </tr>`;
    }).join('');
    
    // Update pagination info
    updateFinesPaginationInfo(startIdx + 1, endIdx, items.length, window.finesCurrentPage, totalPages);
    updateFinesPaginationButtons(window.finesCurrentPage, totalPages);
}

function updateFinesPaginationInfo(start, end, total, currentPage, totalPages) {
    const startEl = document.getElementById('fines-pagination-start');
    const endEl = document.getElementById('fines-pagination-end');
    const totalEl = document.getElementById('fines-pagination-total');
    const pageInfoEl = document.getElementById('fines-page-info');
    
    if (startEl && endEl && totalEl) {
        startEl.textContent = total === 0 ? 0 : start;
        endEl.textContent = end;
        totalEl.textContent = total;
    }
    
    if (pageInfoEl && currentPage && totalPages) {
        pageInfoEl.textContent = 'Page ' + currentPage + ' sur ' + totalPages;
    }
}

function updateFinesPaginationButtons(currentPage, totalPages) {
    const prevBtn = document.querySelector('#fines-pagination-controls li:first-child a');
    const nextBtn = document.querySelector('#fines-pagination-controls li:last-child a');
    
    if (prevBtn) {
        if (currentPage <= 1) {
            prevBtn.parentElement.classList.add('disabled');
        } else {
            prevBtn.parentElement.classList.remove('disabled');
        }
    }
    
    if (nextBtn) {
        if (currentPage >= totalPages) {
            nextBtn.parentElement.classList.add('disabled');
        } else {
            nextBtn.parentElement.classList.remove('disabled');
        }
    }
}

function finesGoToPreviousPage() {
    if (window.finesCurrentPage > 1) {
        window.finesCurrentPage--;
        displayFinesPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function finesGoToNextPage() {
    const totalPages = Math.ceil((window.finesCurrentItems || []).length / window.FINES_PER_PAGE);
    if (window.finesCurrentPage < totalPages) {
        window.finesCurrentPage++;
        displayFinesPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

// vehicle-select removed; users input immatriculation and we resolve via /api/vehicles/query

function loadFineTypes(){
    fetch('/api/vehicles/fines/types')
        .then(r=>r.json())
        .then(data=>{
            // populate select for creating fines
            const typeSel = document.getElementById('fine-type-select');
            if(typeSel){
                typeSel.innerHTML = '<option value="">-- Type d\'amande (optionnel) --</option>' + data.map(t=>`<option value="${t.id}" data-amount="${t.amount}" data-label="${t.label}">${t.label}</option>`).join('');
                typeSel.addEventListener('change', function(){
                    const opt = this.options[this.selectedIndex];
                    if(!opt || !opt.value) return;
                    const a = opt.dataset.amount;
                    const l = opt.dataset.label;
                    const amtEl = document.getElementById('fine-amount');
                    const reasonEl = document.getElementById('fine-reason');
                    if(amtEl) amtEl.value = a || '';
                    if(reasonEl) reasonEl.value = l || '';
                });
            }
            renderFineTypesTable(data);
        }).catch(err=>{
            console.error('Erreur chargement types amandes',err);
            const tbody = document.getElementById('fine-types-tbody');
            if(tbody) tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Erreur chargement</td></tr>';
        });
}

function renderFineTypesTable(items){
    const tbody = document.getElementById('fine-types-tbody');
    if(!tbody) return;
    if(!items || items.length===0){
        tbody.innerHTML = '<tr><td colspan="4" class="text-center">Aucun type</td></tr>';
        return;
    }
    tbody.innerHTML = items.map((t,i)=>`<tr>
        <td>${i+1}</td>
        <td>${t.label}</td>
        <td>${Math.round(t.amount)} KMF</td>
        <td>
          <button class="btn btn-sm btn-outline-secondary me-1" data-edit-type-id="${t.id}">Éditer</button>
          <button class="btn btn-sm btn-outline-danger" data-delete-type-id="${t.id}">Supprimer</button>
        </td>
    </tr>`).join('');
    // bind delete buttons
    document.querySelectorAll('[data-delete-type-id]').forEach(btn=>{
        btn.addEventListener('click', function(){
            const id = this.dataset.deleteTypeId;
            if(!confirm('Supprimer ce type d\'amande ?')) return;
            fetch(`/api/vehicles/fines/types/${id}`, { method: 'DELETE' })
                .then(r=>{ if(!r.ok) throw new Error('Erreur'); return r.json(); })
                .then(()=>{ loadFineTypes(); })
                .catch(err=>{ alert('Impossible de supprimer'); });
        });
    });
    // bind edit buttons
    document.querySelectorAll('[data-edit-type-id]').forEach(btn=>{
        btn.addEventListener('click', function(){
            const id = this.dataset.editTypeId;
            openEditFineType(id);
        });
    });
}

function submitFineTypeForm(e){
    e.preventDefault();
    const id = document.getElementById('fine-type-id').value;
    const label = document.getElementById('fine-type-label').value;
    const amount = document.getElementById('fine-type-amount').value;
    if(!label || !amount){ alert('Veuillez remplir label et montant'); return; }
    const payload = { label, amount };
    if(id){
        // Edit existing type
        fetch(`/api/vehicles/fines/types/${id}`, {
            method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        }).then(r=>{ if(!r.ok) return r.json().then(x=>{ throw x; }); return r.json(); })
        .then(res=>{ document.getElementById('fine-type-form').reset(); document.getElementById('fine-type-id').value=''; toggleFineTypeFormAddMode(true); loadFineTypes(); alert('Type mis à jour'); })
        .catch(err=>{ alert(err.error || 'Erreur mise à jour type'); });
    } else {
        // Create new type
        fetch('/api/vehicles/fines/types', {
            method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        }).then(r=>{ if(!r.ok) return r.json().then(x=>{ throw x; }); return r.json(); })
        .then(res=>{ document.getElementById('fine-type-form').reset(); loadFineTypes(); alert('Type ajouté'); })
        .catch(err=>{ alert(err.error || 'Erreur création type'); });
    }
}

// Cancel edit button handler
const fineTypeCancelBtn = document.getElementById('fine-type-cancel');
if(fineTypeCancelBtn){
    fineTypeCancelBtn.addEventListener('click', function(){
        document.getElementById('fine-type-form').reset();
        document.getElementById('fine-type-id').value = '';
        toggleFineTypeFormAddMode(true);
    });
}

function openEditFineType(id){
    // fetch single type details from list already loaded
    fetch('/api/vehicles/fines/types')
        .then(r=>{ if(!r.ok) throw new Error('Erreur'); return r.json(); })
        .then(list=>{
            const t = (list || []).find(x=>String(x.id)===String(id));
            if(!t) return alert('Type introuvable');
            document.getElementById('fine-type-id').value = t.id;
            document.getElementById('fine-type-label').value = t.label;
            document.getElementById('fine-type-amount').value = t.amount;
            toggleFineTypeFormAddMode(false);
        }).catch(err=>{ alert('Impossible de charger le type'); });
}

function toggleFineTypeFormAddMode(isAdd){
    const btn = document.querySelector('#fine-type-form button[type="submit"]');
    const cancel = document.getElementById('fine-type-cancel');
    if(btn) btn.textContent = isAdd ? 'Ajouter Type' : 'Enregistrer';
    if(cancel){
        if(isAdd) cancel.classList.add('d-none');
        else cancel.classList.remove('d-none');
    }
}

function submitFineFromForm(e){
    e.preventDefault();
    const plate = document.getElementById('fine-vehicle-plate').value.trim();
    const typeId = document.getElementById('fine-type-select').value;
    const amount = document.getElementById('fine-amount').value;
    const reason = document.getElementById('fine-reason').value;
    if(!plate || !amount || !reason){ alert('Veuillez remplir l\'immatriculation, le montant et le motif'); return; }
    // If a pre-validated vehicle id is present, use it directly
    const preVid = (document.getElementById('fine-vehicle-id')||{}).value;
    const payload = { amount, reason };
    const doPost = (vid) => fetch(`/api/vehicles/${vid}/fines`, {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify(payload)
            }).then(r=>{ if(!r.ok) return r.json().then(x=>{ throw x; }); return r.json(); });

    if(preVid){
        doPost(preVid).then(res=>{
            const form = document.getElementById('fines-create-form');
            if(form) form.reset();
            // reset validation UI
            const vidEl = document.getElementById('fine-vehicle-id'); if(vidEl) vidEl.value = '';
            const status = document.getElementById('fine-plate-status'); if(status){ status.textContent=''; status.className='text-muted small'; }
            const createBtn = document.getElementById('create-fine-btn'); if(createBtn) createBtn.disabled = true;
            loadFineTypes();
            loadFines();
            alert('Amande créée');
        }).catch(err=>{ alert(err.error || err.message || 'Erreur création amande'); });
        return;
    }

    // Resolve vehicle id by searching license plate (fallback)
    fetch(`/api/vehicles/query?q=${encodeURIComponent(plate)}`)
        .then(r=>{ if(!r.ok) throw new Error('Recherche véhicule échouée'); return r.json(); })
        .then(list=>{
            if(!Array.isArray(list) || list.length===0){
                throw { error: 'Véhicule non trouvé pour immatriculation: ' + plate };
            }
            // try to find exact match first
            const plateLower = plate.toLowerCase();
            let vehicle = list.find(v => v.license_plate && v.license_plate.toLowerCase() === plateLower) || list[0];
            const vid = vehicle.id;
            return doPost(vid);
        })
        .then(res=>{
            const form = document.getElementById('fines-create-form');
            if(form) form.reset();
            loadFineTypes();
            loadFines();
            alert('Amande créée');
        })
        .catch(err=>{ alert(err.error || err.message || 'Erreur création amande'); });
}
