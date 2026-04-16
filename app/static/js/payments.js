document.addEventListener('DOMContentLoaded', function(){
    // Restore previous view if returning from receipt
    const savedView = sessionStorage.getItem('payments-current-view');
    const initialView = savedView || 'pending';
    
    bindViewControls();
    
    // Set active button based on saved view
    if(savedView){
        const group = document.getElementById('payments-view-group');
        if(group){
            group.querySelectorAll('button[data-view]').forEach(b=>{
                b.classList.remove('active');
                if(b.dataset.view === savedView){
                    b.classList.add('active');
                }
            });
        }
    }
    
    loadPayments(initialView);
});

function bindViewControls(){
    const group = document.getElementById('payments-view-group');
    if(!group) return;
    group.addEventListener('click', function(e){
        const btn = e.target.closest('button[data-view]');
        if(!btn) return;
        group.querySelectorAll('button[data-view]').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        const view = btn.dataset.view;
        // Save current view to sessionStorage
        sessionStorage.setItem('payments-current-view', view);
        loadPayments(view);
    });

    const exportBtn = document.getElementById('export-archive');
    if(exportBtn){
      exportBtn.addEventListener('click', function(){
                // Show modal for date range selection
                const modal = new bootstrap.Modal(document.getElementById('exportModal'));
                modal.show();
      });
    }
    
    // Handle export confirmation
    const confirmExportBtn = document.getElementById('confirm-export-btn');
    if(confirmExportBtn){
        confirmExportBtn.addEventListener('click', function(){
            const startDate = document.getElementById('export-date-start').value;
            const endDate = document.getElementById('export-date-end').value;
            
            // Check if both dates are provided or both are empty
            if((startDate && !endDate) || (!startDate && endDate)){
                alert('Veuillez sélectionner les deux dates ou laisser les deux vides pour tout exporter');
                return;
            }
            
            if(startDate && endDate && startDate > endDate){
                alert('La date de début doit être antérieure à la date de fin');
                return;
            }
            
            // Build URL with or without date range
            let url = '/api/vehicles/fines/all?paid=true&export=pdf';
            if(startDate && endDate){
                url += `&start_date=${startDate}&end_date=${endDate}`;
                console.log('Exporting with date range:', startDate, 'to', endDate);
                console.log('Export URL:', url);
            } else {
                console.log('Exporting all archives (no date filter)');
            }
            
            // Remove focus from button to avoid aria-hidden warning
            this.blur();
            
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('exportModal'));
            if(modal) modal.hide();
            
            // Download PDF
            window.location = url;
        });
    }
}

let archiveData = [];
let pendingData = [];

function loadPayments(view){
    // view: 'pending' or 'archive'
    if(view === 'archive'){
        fetch('/api/vehicles/fines/all?paid=true')
            .then(r=>r.json())
            .then(data=>{
                // Store archive data for searching
                archiveData = data || [];
                // Sort by paid_at descending (most recent first)
                archiveData.sort((a, b) => {
                    const dateA = a.paid_at ? new Date(a.paid_at) : new Date(0);
                    const dateB = b.paid_at ? new Date(b.paid_at) : new Date(0);
                    return dateB - dateA;
                });
                renderPaymentsTable(archiveData, true);
                // show export button
                const exp = document.getElementById('export-archive'); if(exp) exp.style.display='inline-block';
                // show search bar
                const searchBar = document.getElementById('payments-search-bar'); if(searchBar) searchBar.style.display='';
                // clear search input
                const searchInput = document.getElementById('payments-search-input'); if(searchInput) searchInput.value = '';
            }).catch(err=>{
                console.error('Erreur chargement archive', err);
                document.getElementById('payments-tbody').innerHTML = '<tr><td colspan="8" class="text-center text-muted">Erreur</td></tr>';
            });
    } else {
        fetch('/api/vehicles/fines/all?paid=false')
            .then(r=>r.json())
            .then(data=>{
                // Store pending data for searching
                pendingData = data || [];
                // Sort by issued_at descending (newest first)
                pendingData.sort((a, b) => {
                    const dateA = a.issued_at ? new Date(a.issued_at) : new Date(0);
                    const dateB = b.issued_at ? new Date(b.issued_at) : new Date(0);
                    return dateB - dateA;
                });
                renderPaymentsTable(pendingData, false);
                const exp = document.getElementById('export-archive'); if(exp) exp.style.display='none';
                // show search bar
                const searchBar = document.getElementById('payments-search-bar'); if(searchBar) searchBar.style.display='';
                // clear search input
                const searchInput = document.getElementById('payments-search-input'); if(searchInput) searchInput.value = '';
            }).catch(err=>{
                console.error('Erreur chargement paiements', err);
                document.getElementById('payments-tbody').innerHTML = '<tr><td colspan="7" class="text-center text-muted">Erreur</td></tr>';
            });
    }
}

function searchPayments(query){
    const activeBtn = document.querySelector('#payments-view-group button.active');
    const currentView = activeBtn ? activeBtn.dataset.view : 'pending';
    
    if(!query.trim()){
        if(currentView === 'archive'){
            renderPaymentsTable(archiveData, true);
        } else {
            renderPaymentsTable(pendingData, false);
        }
        return;
    }
    
    const dataSource = currentView === 'archive' ? archiveData : pendingData;
    const filtered = dataSource.filter(f => 
        (f.license_plate || '').toLowerCase().includes(query.toLowerCase()) ||
        (f.reason || '').toLowerCase().includes(query.toLowerCase()) ||
        (f.receipt_number || '').toLowerCase().includes(query.toLowerCase())
    );
    const isArchive = currentView === 'archive';
    renderPaymentsTable(filtered, isArchive);
}

function renderPaymentsTable(items, isArchive){
    const tbody = document.getElementById('payments-tbody');
    
    // Update column headers based on view
    const dateHeader = document.getElementById('date-column-header');
    const paidDateHeader = document.getElementById('paid-date-column-header');
    
    if(isArchive){
        // Show both date columns in archive view
        if(dateHeader) dateHeader.style.display = '';
        if(paidDateHeader) paidDateHeader.style.display = '';
    } else {
        // Show only issued date in pending view
        if(dateHeader) dateHeader.style.display = '';
        if(paidDateHeader) paidDateHeader.style.display = 'none';
    }
    
    if(!items || items.length===0){
        const colspan = isArchive ? '8' : '7';
        tbody.innerHTML = `<tr><td colspan="${colspan}" class="text-center">${isArchive ? 'Aucune facture archivée' : 'Aucune amande impayée'}</td></tr>`;
        return;
    }
    tbody.innerHTML = items.map((f,i)=>{
        // Format issued date
        let issuedDate = f.issued_at_str || f.issued_at;
        try {
            const dt = new Date(f.issued_at);
            issuedDate = dt.toLocaleDateString('fr-FR');
        } catch(e) {}
        
        // Format paid date
        let paidDate = '';
        if(f.paid_at){
            try {
                const dt = new Date(f.paid_at);
                paidDate = dt.toLocaleDateString('fr-FR');
            } catch(e) {
                paidDate = f.paid_at;
            }
        }
        
        return `<tr>
        <td>${i+1}</td>
        <td>${f.license_plate||''}</td>
        <td>${f.reason}</td>
        <td>${Math.round(f.amount)} KMF</td>
        <td>${issuedDate}</td>
        ${isArchive ? `<td>${paidDate}</td>` : ''}
        <td>${f.paid ? (f.receipt_number ? 'Payée' : 'Payée') : 'Impayée'}</td>
        <td>
            ${isArchive ? `<a class="btn btn-sm btn-outline-secondary" href="/fines/receipt/${f.id}" onclick="sessionStorage.setItem('payments-current-view', 'archive');"><i class="fas fa-print me-1"></i>Reçu</a>` : `<button class="btn btn-sm btn-success" data-pay-id="${f.id}"><i class="fas fa-check me-1"></i>Payer</button>`}
        </td>
    </tr>`;
    }).join('');

    if(!isArchive){
      document.querySelectorAll('[data-pay-id]').forEach(btn=>{
          btn.addEventListener('click', function(){
              const id = this.dataset.payId;
              openPayModal(id);
          });
      });
    }
}

let selectedPayId = null;
function openPayModal(id){
    selectedPayId = id;
    const modal = new bootstrap.Modal(document.getElementById('payModal'));
    modal.show();
    const confirmBtn = document.getElementById('confirm-pay-btn');
    if(confirmBtn){
        confirmBtn.onclick = submitPayment;
    }
}

function submitPayment(){
    if(!selectedPayId) return alert('Aucune amande sélectionnée');
    const method = document.getElementById('pay-method').value;
    fetch(`/api/vehicles/fines/${selectedPayId}/pay`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({payment_method: method})
    }).then(r=>{
        if(!r.ok) return r.json().then(x=>{ throw x; }); return r.json();
    }).then(res=>{
        // close modal
        const modEl = document.getElementById('payModal');
        const bs = bootstrap.Modal.getInstance(modEl);
        if(bs) bs.hide();
        
        // Save current view before redirecting
        const activeBtn = document.querySelector('#payments-view-group button.active');
        const currentView = activeBtn ? activeBtn.dataset.view : 'pending';
        sessionStorage.setItem('payments-current-view', currentView);
        
        // open receipt
        const fid = res.fine.id;
        window.location.href = `/fines/receipt/${fid}`;
    }).catch(err=>{ alert(err.error || 'Erreur lors du paiement'); });
}
