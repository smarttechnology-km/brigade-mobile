document.addEventListener('DOMContentLoaded', function () {
  logDebug('[reports] loaded');

  const btnApply = document.getElementById('btn-apply-filters');
  const btnReset = document.getElementById('btn-reset-filters');
  const btnExport = document.getElementById('btn-export-csv');
  logDebug('[reports] controls: btnApply=' + !!btnApply + ' btnReset=' + !!btnReset + ' btnExport=' + !!btnExport);

  if (btnApply) btnApply.addEventListener('click', applyFilters);
  if (btnReset) btnReset.addEventListener('click', resetFilters);
  if (btnExport) btnExport.addEventListener('click', exportCsv);

  // small-screen duplicates (if present)
  const btnApplySm = document.getElementById('btn-apply-filters_sm');
  const btnResetSm = document.getElementById('btn-reset-filters_sm');
  const btnExportSm = document.getElementById('btn-export-csv_sm');
  if (btnApplySm) btnApplySm.addEventListener('click', applyFilters);
  if (btnResetSm) btnResetSm.addEventListener('click', resetFilters);
  if (btnExportSm) btnExportSm.addEventListener('click', exportCsv);

  // defaults
  const expDaysEl = document.getElementById('expiring-days');
  if (expDaysEl) expDaysEl.textContent = '30';

  // report kind toggles
  const kind = document.getElementById('report-kind');
  const finesQuick = document.getElementById('fines-quick-filters');
  if (kind) {
    kind.addEventListener('change', function () {
      // If any fines-related kind selected, show quick filters and set paid state accordingly
      if (this.value && this.value.indexOf('fines') === 0) {
        if (finesQuick) finesQuick.style.display = '';
        const paidEl = document.getElementById('filter-paid');
        const btnUnpaid = document.getElementById('fines-unpaid-btn');
        const btnPaid = document.getElementById('fines-paid-btn');
        if (this.value === 'fines_paid') {
          if (paidEl) paidEl.value = 'true';
          btnPaid && btnPaid.classList.add('active'); btnUnpaid && btnUnpaid.classList.remove('active');
        } else if (this.value === 'fines_unpaid') {
          if (paidEl) paidEl.value = 'false';
          btnUnpaid && btnUnpaid.classList.add('active'); btnPaid && btnPaid.classList.remove('active');
        } else {
          // generic 'fines' selection - default to unpaid if not set
          if (paidEl && !paidEl.value) paidEl.value = 'false';
          btnUnpaid && btnUnpaid.classList.add('active'); btnPaid && btnPaid.classList.remove('active');
        }
      } else {
        if (finesQuick) finesQuick.style.display = 'none';
      }
      setReportsHeader(this.value);
    });
    // initialize header state
    setReportsHeader(kind.value || 'vehicles');
    // if initial kind is any fines variant, set state
    if (kind.value && kind.value.indexOf('fines') === 0) {
      const paidEl = document.getElementById('filter-paid');
      const btnUnpaid = document.getElementById('fines-unpaid-btn');
      const btnPaid = document.getElementById('fines-paid-btn');
      if (kind.value === 'fines_paid') {
        if (paidEl) paidEl.value = 'true';
        btnPaid && btnPaid.classList.add('active'); btnUnpaid && btnUnpaid.classList.remove('active');
      } else if (kind.value === 'fines_unpaid') {
        if (paidEl) paidEl.value = 'false';
        btnUnpaid && btnUnpaid.classList.add('active'); btnPaid && btnPaid.classList.remove('active');
      } else {
        if (paidEl && !paidEl.value) paidEl.value = 'false';
        btnUnpaid && btnUnpaid.classList.add('active'); btnPaid && btnPaid.classList.remove('active');
      }
      if (finesQuick) finesQuick.style.display = '';
    }
  }

  // attach quick filter handlers
  const btnUnpaid = document.getElementById('fines-unpaid-btn');
  const btnPaid = document.getElementById('fines-paid-btn');
  if (btnUnpaid) btnUnpaid.addEventListener('click', function () {
    const paidEl = document.getElementById('filter-paid'); if (paidEl) paidEl.value = 'false';
    btnUnpaid.classList.add('active'); btnPaid && btnPaid.classList.remove('active');
    // ensure report kind is fines
    const kindEl = document.getElementById('report-kind'); if (kindEl) { kindEl.value = 'fines'; setReportsHeader('fines'); }
    applyFilters();
  });
  if (btnPaid) btnPaid.addEventListener('click', function () {
    const paidEl = document.getElementById('filter-paid'); if (paidEl) paidEl.value = 'true';
    btnPaid.classList.add('active'); btnUnpaid && btnUnpaid.classList.remove('active');
    const kindEl = document.getElementById('report-kind'); if (kindEl) { kindEl.value = 'fines'; setReportsHeader('fines'); }
    applyFilters();
  });
});

function collectFilters() {
  const start = document.getElementById('filter-start') ? document.getElementById('filter-start').value : '';
  const end = document.getElementById('filter-end') ? document.getElementById('filter-end').value : '';
  const type = document.getElementById('filter-type') ? document.getElementById('filter-type').value : '';
  const status = document.getElementById('filter-status') ? document.getElementById('filter-status').value : '';
  const q = document.getElementById('filter-q') ? document.getElementById('filter-q').value : '';
  const params = new URLSearchParams();
  if (start) params.append('start_date', start);
  if (end) params.append('end_date', end);
  if (type) params.append('type', type);
  if (status) params.append('status', status);
  if (q) params.append('q', q);
  return params;
}

// Safe fetch helper: ensures we get JSON and surfaces redirects/login pages
function fetchJson(url, opts) {
  return fetch(url, opts).then(r => {
    const ct = r.headers.get('content-type') || '';
    if (!r.ok) {
      // Common case: server redirected to login (302) or returned HTML login page
      if (r.status === 302 || r.redirected || ct.indexOf('text/html') !== -1) {
        throw new Error('Unauthorized or redirected to login (status ' + r.status + '). Please ensure you are logged in.');
      }
      throw new Error('HTTP error ' + r.status);
    }
    if (ct.indexOf('application/json') === -1) {
      throw new Error('Expected JSON response but got: ' + ct + ' (status ' + r.status + ')');
    }
    return r.json();
  });
}

// Debug helpers: append messages to the visible debug panel if present
function logDebug(msg) {
  try { console.log('[reports] ' + msg); } catch (e) { /* ignore */ }
}

function logError(msg) {
  try { console.error('[reports] ' + msg); } catch (e) { /* ignore */ }
}

function applyFilters() {
  const btnApply = document.getElementById('btn-apply-filters');
  const btnReset = document.getElementById('btn-reset-filters');
  const btnExport = document.getElementById('btn-export-csv');
  try {
    logDebug('[reports] applyFilters triggered - kind=' + (document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles'));
    // no debug panel (removed) — keep behavior silent
    if (btnApply) { btnApply.disabled = true; btnApply.dataset.orig = btnApply.innerHTML; btnApply.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Chargement'; }
    if (btnReset) btnReset.disabled = true;
    if (btnExport) btnExport.disabled = true;
  } catch (e) {
    logError('[reports] applyFilters startup error: ' + (e && e.message));
  }

  const kind = document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles';
  if (kind && kind.indexOf('fines') === 0) {
    // determine paid filter: explicit from kind, otherwise from filter-paid input
    let paid = '';
    if (kind === 'fines_paid') paid = 'true';
    else if (kind === 'fines_unpaid') paid = 'false';
    else paid = document.getElementById('filter-paid') ? document.getElementById('filter-paid').value : '';
    const q = document.getElementById('filter-q') ? document.getElementById('filter-q').value : '';
    const paidParam = paid ? `&paid=${paid}` : '';
    fetchJson(`/api/vehicles/fines/all?q=${encodeURIComponent(q)}${paidParam}`)
      .then(data => { renderFinesTable(data); updateFinesSummary(data); })
      .catch(err => { logError('Erreur chargement amandes: ' + (err && err.message)); alert('Erreur lors du chargement des amandes'); })
      .finally(() => { try { if (btnApply) { btnApply.disabled = false; btnApply.innerHTML = btnApply.dataset.orig || 'Appliquer'; } if (btnReset) btnReset.disabled = false; if (btnExport) btnExport.disabled = false; } catch (e) { logError('finally error: ' + (e && e.message)); } });
    return;
  }

  if (kind === 'expired') {
    const params = collectFilters(); params.append('expired', 'true');
    fetchJson(`/api/vehicles/query?${params.toString()}`)
      .then(data => { renderReportsTable(data); updateSummary(data); })
      .catch(err => { logError('Erreur chargement rapports: ' + (err && err.message)); alert('Erreur lors du chargement des rapports'); })
      .finally(() => { try { if (btnApply) { btnApply.disabled = false; btnApply.innerHTML = btnApply.dataset.orig || 'Appliquer'; } if (btnReset) btnReset.disabled = false; if (btnExport) btnExport.disabled = false; } catch (e) { logError('finally error: ' + (e && e.message)); } });
    return;
  }

  // default vehicles report
  const params = collectFilters();
  fetchJson(`/api/vehicles/query?${params.toString()}`)
    .then(data => { renderReportsTable(data); updateSummary(data); })
    .catch(err => { logError('Erreur chargement rapports: ' + (err && err.message)); alert('Erreur lors du chargement des rapports'); })
    .finally(() => { try { if (btnApply) { btnApply.disabled = false; btnApply.innerHTML = btnApply.dataset.orig || 'Appliquer'; } if (btnReset) btnReset.disabled = false; if (btnExport) btnExport.disabled = false; } catch (e) { logError('finally error: ' + (e && e.message)); } });
}

 function resetFilters() {
   const elems = ['filter-start', 'filter-end', 'filter-type', 'filter-status', 'filter-q', 'filter-paid'];
   elems.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
   // reset report kind to default
   try{
     const kindEl = document.getElementById('report-kind');
     if(kindEl){ kindEl.value = 'vehicles'; kindEl.dispatchEvent(new Event('change')); }
   }catch(e){ console.error('[reports] reset kind failed', e); }
   // after clearing filters, immediately apply them so the table shows results
   try{ if (typeof applyFilters === 'function') { applyFilters(); } else { const btnApply = document.getElementById('btn-apply-filters'); if(btnApply) btnApply.click(); } }catch(e){ console.error('resetFilters apply failed', e); }
 }

function renderReportsTable(items) {
  const tbody = document.getElementById('reports-tbody');
  if (!items || items.length === 0) { tbody.innerHTML = '<tr><td colspan="7" class="text-center">Aucun résultat</td></tr>'; return; }
  tbody.innerHTML = items.map((v, i) => `
    <tr>
      <td>${i+1}</td>
      <td><strong>${v.license_plate || ''}</strong></td>
      <td>${v.owner_name || ''}</td>
      <td>${capitalize(v.vehicle_type)}</td>
      <td>${capitalizeStatus(v.status)}</td>
      <td>${v.registration_expiry || ''}</td>
      <td>${v.created_at || ''}</td>
    </tr>`).join('');
}

function renderFinesTable(items) {
  const tbody = document.getElementById('reports-tbody');
  if (!items || items.length === 0) { tbody.innerHTML = '<tr><td colspan="7" class="text-center">Aucun résultat</td></tr>'; return; }
  tbody.innerHTML = items.map((f, i) => `
    <tr>
      <td>${i+1}</td>
      <td><strong>${f.license_plate || ''}</strong></td>
      <td>${f.reason || ''}</td>
      <td>${Math.round(f.amount || 0)} KMF</td>
      <td>${f.issued_at_str || f.issued_at || ''}</td>
      <td>${f.paid ? '<span class="badge bg-success">Payée</span>' : '<span class="badge bg-danger">Impayée</span>'}</td>
      <td>${f.receipt_number || ''}</td>
    </tr>`).join('');
}

function updateFinesSummary(items) {
  const total = items.length;
  const paid = items.filter(i => i.paid).length;
  const unpaid = total - paid;
  document.getElementById('rep-total').textContent = total;
  document.getElementById('rep-active').textContent = paid;
  document.getElementById('rep-suspended').textContent = unpaid;
  document.getElementById('rep-expiring').textContent = '—';
}

function setReportsHeader(kind) {
  const thead = document.getElementById('reports-thead'); if (!thead) return;
  if (kind === 'fines') {
    thead.innerHTML = `
      <tr>
        <th>#</th>
        <th>Immatriculation</th>
        <th>Motif</th>
        <th>Montant</th>
        <th>Émis le</th>
        <th>Statut</th>
        <th>Reçu</th>
      </tr>`;
  } else {
    thead.innerHTML = `
      <tr>
        <th>#</th>
        <th>Immatriculation</th>
        <th>Propriétaire</th>
        <th>Type</th>
        <th>Statut</th>
        <th>Expiration Vignette</th>
        <th>Enregistré</th>
      </tr>`;
  }
}

function updateSummary(items) {
  const total = items.length;
  const active = items.filter(i => i.status === 'active').length;
  const suspended = items.filter(i => i.status === 'suspended').length;
  const now = new Date();
  const future = new Date(); future.setDate(now.getDate() + 30);
  const expiring = items.filter(i => {
    if (!i.registration_expiry) return false;
    const d = new Date(i.registration_expiry);
    return d >= now && d <= future;
  }).length;
  document.getElementById('rep-total').textContent = total;
  document.getElementById('rep-active').textContent = active;
  document.getElementById('rep-suspended').textContent = suspended;
  document.getElementById('rep-expiring').textContent = expiring;
}

function exportCsv() {
  const kind = document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles';
  if (kind === 'fines') {
    const paid = document.getElementById('filter-paid') ? document.getElementById('filter-paid').value : '';
    const paidParam = paid ? `&paid=${paid}` : '';
    // request PDF instead of CSV
    window.location.href = `/api/vehicles/fines/all?export=pdf${paidParam}`;
    return;
  }
  const params = collectFilters();
  if (kind === 'expired') params.append('expired', 'true');
  // request PDF instead of CSV
  params.append('export', 'pdf');
  const url = `/api/vehicles/export?${params.toString()}`;
  window.location.href = url;
}

function capitalize(s) { if (!s) return ''; return s.charAt(0).toUpperCase() + s.slice(1); }
function capitalizeStatus(s) { if (s === 'active') return 'Actif'; if (s === 'inactive') return 'Inactif'; if (s === 'suspended') return 'Suspendu'; return s || ''; }
document.addEventListener('DOMContentLoaded', function(){
    logDebug('[reports] loaded');
    const btnApply = document.getElementById('btn-apply-filters');
    const btnReset = document.getElementById('btn-reset-filters');
    const btnExport = document.getElementById('btn-export-csv');
    logDebug('[reports] controls: btnApply=' + !!btnApply + ' btnReset=' + !!btnReset + ' btnExport=' + !!btnExport);

    if(btnApply) btnApply.addEventListener('click', applyFilters);
    if(btnReset) btnReset.addEventListener('click', resetFilters);
    if(btnExport) btnExport.addEventListener('click', exportCsv);

    // small-screen buttons (duplicate controls for mobile view)
    const btnApplySm = document.getElementById('btn-apply-filters_sm');
    const btnResetSm = document.getElementById('btn-reset-filters_sm');
    const btnExportSm = document.getElementById('btn-export-csv_sm');
    if(btnApplySm) btnApplySm.addEventListener('click', applyFilters);
    if(btnResetSm) btnResetSm.addEventListener('click', resetFilters);
    if(btnExportSm) btnExportSm.addEventListener('click', exportCsv);

    // set default expiring days label
    const expDaysEl = document.getElementById('expiring-days');
    if(expDaysEl) expDaysEl.textContent = '30';
        // show/hide fines paid filter depending on report kind
        const kind = document.getElementById('report-kind');
        const finesPaid = document.getElementById('fines-paid-filter');
        if(kind){
            kind.addEventListener('change', function(){
                if(this.value === 'fines') finesPaid.style.display = '';
                else finesPaid.style.display = 'none';
                setReportsHeader(this.value);
            });
        }
        // initialize header
        setReportsHeader(document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles');
});

function collectFilters(){
    const start = document.getElementById('filter-start').value;
    const end = document.getElementById('filter-end').value;
    const type = document.getElementById('filter-type').value;
    const status = document.getElementById('filter-status').value;
    const q = document.getElementById('filter-q').value;
    const params = new URLSearchParams();
    if(start) params.append('start_date', start);
    if(end) params.append('end_date', end);
    if(type) params.append('type', type);
    if(status) params.append('status', status);
    if(q) params.append('q', q);
    return params;
}

// Debug helpers: append messages to the visible debug panel if present
function logDebug(msg){
    try{
        console.log(msg);
        const logEl = document.getElementById('reports-debug-log');
        if(logEl){
            const time = new Date().toISOString().substr(11,8);
            logEl.textContent = (logEl.textContent ? logEl.textContent + '\n' : '') + '['+time+'] '+msg;
            logEl.scrollTop = logEl.scrollHeight;
        }
    }catch(e){ /* ignore */ }
}

function logError(msg){
    try{
        console.error(msg);
        const logEl = document.getElementById('reports-debug-log');
        if(logEl){
            const time = new Date().toISOString().substr(11,8);
            logEl.textContent = (logEl.textContent ? logEl.textContent + '\n' : '') + '['+time+'] ERROR: '+msg;
            logEl.scrollTop = logEl.scrollHeight;
        }
    }catch(e){ /* ignore */ }
}

function applyFilters(){
    try{
    const btnApply = document.getElementById('btn-apply-filters');
    const btnReset = document.getElementById('btn-reset-filters');
    const btnExport = document.getElementById('btn-export-csv');
    logDebug('[reports] applyFilters triggered - kind=' + (document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles'));
    
    // show debug panel so user can see messages
    const dbg = document.getElementById('reports-debug'); if(dbg) dbg.style.display = '';

    // disable buttons and show loading state
    if(btnApply) { btnApply.disabled = true; btnApply.dataset.orig = btnApply.innerHTML; btnApply.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Chargement'; }
    if(btnReset) btnReset.disabled = true;
    if(btnExport) btnExport.disabled = true;
    }catch(e){ logError('[reports] applyFilters startup error: ' + (e && e.message)); console.error('[reports] applyFilters startup error', e); }

        const kind = document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles';
        if(kind === 'fines'){
                // use fines endpoint
                const paid = document.getElementById('filter-paid') ? document.getElementById('filter-paid').value : '';
                const q = document.getElementById('filter-q').value || '';
                const paidParam = paid ? `&paid=${paid}` : '';
                fetchJson(`/api/vehicles/fines/all?q=${encodeURIComponent(q)}${paidParam}`)
                  .then(data=>{
                    renderFinesTable(data);
                    // summary: show counts of total/paid/unpaid
                    updateFinesSummary(data);
                  })
                    .catch(err => { console.error('Erreur chargement amandes:', err); alert('Erreur lors du chargement des amandes'); })
                        .finally(()=>{ try{ const btnApply = document.getElementById('btn-apply-filters'); const btnReset = document.getElementById('btn-reset-filters'); const btnExport = document.getElementById('btn-export-csv'); if(btnApply) { btnApply.disabled = false; btnApply.innerHTML = btnApply.dataset.orig || 'Appliquer'; } if(btnReset) btnReset.disabled = false; if(btnExport) btnExport.disabled = false; }catch(e){console.error('[reports] finally error', e);} });
                return;
        } else if(kind === 'expired'){
                // request vehicles with expired vignette
                const params = collectFilters();
                params.append('expired','true');
                fetchJson(`/api/vehicles/query?${params.toString()}`)
                  .then(data => {
                    renderReportsTable(data);
                    updateSummary(data);
                  })
                        .catch(err => { console.error('Erreur chargement rapports:', err); alert('Erreur lors du chargement des rapports'); })
                        .finally(()=>{ try{ const btnApply = document.getElementById('btn-apply-filters'); const btnReset = document.getElementById('btn-reset-filters'); const btnExport = document.getElementById('btn-export-csv'); if(btnApply) { btnApply.disabled = false; btnApply.innerHTML = btnApply.dataset.orig || 'Appliquer'; } if(btnReset) btnReset.disabled = false; if(btnExport) btnExport.disabled = false; }catch(e){console.error('[reports] finally error', e);} });
                return;
        } else {
                const params = collectFilters();
                fetchJson(`/api/vehicles/query?${params.toString()}`)
                .then(data => {
                  renderReportsTable(data);
                  updateSummary(data);
                })
        .catch(err => {
            console.error('Erreur chargement rapports:', err);
            alert('Erreur lors du chargement des rapports');
        })
        .finally(() => {
            try{ const btnApply = document.getElementById('btn-apply-filters'); const btnReset = document.getElementById('btn-reset-filters'); const btnExport = document.getElementById('btn-export-csv'); if(btnApply) { btnApply.disabled = false; btnApply.innerHTML = btnApply.dataset.orig || 'Appliquer'; } if(btnReset) btnReset.disabled = false; if(btnExport) btnExport.disabled = false; }catch(e){console.error('[reports] finally error', e);} });
}

function resetFilters(){
  const elems = ['filter-start','filter-end','filter-type','filter-status','filter-q','filter-paid'];
  elems.forEach(id => { const el = document.getElementById(id); if(el) el.value=''; });
  // reset report kind to default
  try{ const kindEl = document.getElementById('report-kind'); if(kindEl){ kindEl.value='vehicles'; kindEl.dispatchEvent(new Event('change')); } }catch(e){ console.error('[reports] reset kind failed', e); }
  // apply filters after reset so the table is populated
  try{ if (typeof applyFilters === 'function') applyFilters(); else { const btnApply = document.getElementById('btn-apply-filters'); if(btnApply) btnApply.click(); } }catch(e){ console.error('[reports] reset apply failed', e); }
}

function renderReportsTable(items){
    const tbody = document.getElementById('reports-tbody');
    if(!items || items.length===0){
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Aucun résultat</td></tr>';
        return;
    }
    tbody.innerHTML = items.map((v,i)=>`<tr>
        <td>${i+1}</td>
        <td><strong>${v.license_plate}</strong></td>
        <td>${v.owner_name}</td>
        <td>${capitalize(v.vehicle_type)}</td>
        <td>${capitalizeStatus(v.status)}</td>
        <td>${v.registration_expiry || ''}</td>
        <td>${v.created_at || ''}</td>
    </tr>`).join('');
}

function renderFinesTable(items){
    const tbody = document.getElementById('reports-tbody');
    if(!items || items.length===0){
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Aucun résultat</td></tr>';
        return;
    }
    // render columns: #, Immatriculation, Motif, Montant, Émis le, Statut, Reçu
    tbody.innerHTML = items.map((f,i)=>`<tr>
        <td>${i+1}</td>
        <td><strong>${f.license_plate||''}</strong></td>
        <td>${f.reason||''}</td>
        <td>${Math.round(f.amount||0)} KMF</td>
        <td>${f.issued_at_str || f.issued_at || ''}</td>
        <td>${f.paid ? '<span class="badge bg-success">Payée</span>' : '<span class="badge bg-danger">Impayée</span>'}</td>
        <td>${f.receipt_number ? f.receipt_number : ''}</td>
    </tr>`).join('');
}

function updateFinesSummary(items){
    const total = items.length;
    const paid = items.filter(i=>i.paid).length;
    const unpaid = total - paid;
    document.getElementById('rep-total').textContent = total;
    document.getElementById('rep-active').textContent = paid;
    document.getElementById('rep-suspended').textContent = unpaid;
    // rep-expiring not relevant for fines
    document.getElementById('rep-expiring').textContent = '—';
}

function setReportsHeader(kind){
    const thead = document.getElementById('reports-thead');
    if(!thead) return;
    if(kind === 'fines'){
        thead.innerHTML = `<tr>
            <th>#</th>
            <th>Immatriculation</th>
            <th>Motif</th>
            <th>Montant</th>
            <th>Émis le</th>
            <th>Statut</th>
            <th>Reçu</th>
        </tr>`;
    } else {
        thead.innerHTML = `<tr>
            <th>#</th>
            <th>Immatriculation</th>
            <th>Propriétaire</th>
            <th>Type</th>
            <th>Statut</th>
            <th>Expiration Vignette</th>
            <th>Enregistré</th>
        </tr>`;
    }
}

function updateSummary(items){
    const total = items.length;
    const active = items.filter(i=>i.status==='active').length;
    const suspended = items.filter(i=>i.status==='suspended').length;
    // expiring within 30 days
    const now = new Date();
    const future = new Date(); future.setDate(now.getDate()+30);
    const expiring = items.filter(i=>{
        if(!i.registration_expiry) return false;
        const d = new Date(i.registration_expiry);
        return d >= now && d <= future;
    }).length;

    document.getElementById('rep-total').textContent = total;
    document.getElementById('rep-active').textContent = active;
    document.getElementById('rep-suspended').textContent = suspended;
    document.getElementById('rep-expiring').textContent = expiring;
}

function exportCsv(){
    const kind = document.getElementById('report-kind') ? document.getElementById('report-kind').value : 'vehicles';
    if(kind === 'fines'){
        const paid = document.getElementById('filter-paid') ? document.getElementById('filter-paid').value : '';
        const paidParam = paid ? `&paid=${paid}` : '';
        window.location.href = `/api/vehicles/fines/all?export=csv${paidParam}`;
        return;
    }
    const params = collectFilters();
    if(kind === 'expired') params.append('expired','true');
    const url = `/api/vehicles/export?${params.toString()}`;
    // navigate to the CSV URL to trigger download (preserves auth cookie)
    window.location.href = url;
}

function capitalize(s){ if(!s) return ''; return s.charAt(0).toUpperCase()+s.slice(1); }
function capitalizeStatus(s){ if(s==='active') return 'Actif'; if(s==='inactive') return 'Inactif'; if(s==='suspended') return 'Suspendu'; return s; }
