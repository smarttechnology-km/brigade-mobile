document.addEventListener('DOMContentLoaded', function(){
    // wire fine modal openers if present
    bindFineButtons();

    const saveFineBtn = document.getElementById('save-fine-btn');
    if(saveFineBtn) saveFineBtn.addEventListener('click', submitFine);
});

let fineModalInstance = null;
function openFineModal(vehicleId){
    // reset
    const form = document.getElementById('fine-form');
    if(form) form.reset();
    document.getElementById('fine-vehicle-id').value = vehicleId || '';
    fineModalInstance = new bootstrap.Modal(document.getElementById('fineModal'));
    fineModalInstance.show();
}

function bindFineButtons(){
    document.querySelectorAll('[data-open-fine-modal]').forEach(btn=>{
        // remove previous listeners to avoid duplicates
        btn.replaceWith(btn.cloneNode(true));
    });
    document.querySelectorAll('[data-open-fine-modal]').forEach(btn=>{
        btn.addEventListener('click', function(e){
            const vid = this.dataset.vehicleId;
            openFineModal(vid);
        });
    });
}

function submitFine(){
    const vid = document.getElementById('fine-vehicle-id').value;
    const amount = document.getElementById('fine-amount').value;
    const reason = document.getElementById('fine-reason').value;
    const officer = document.getElementById('fine-officer').value;
    const notes = document.getElementById('fine-notes').value;
    if(!vid || !amount || !reason){ alert('Veuillez remplir le montant et le motif'); return; }
    const payload = { amount, reason, officer, notes };
    fetch(`/api/vehicles/${vid}/fines`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
    }).then(r=>{
        if(!r.ok) return r.json().then(x=>{ throw x; });
        return r.json();
    }).then(res=>{
        // close modal and refresh lists if on vehicle page
        fineModalInstance.hide();
        try{ if(typeof loadVehicles === 'function') loadVehicles(); }catch(e){}
        try{ if(typeof applyFilters === 'function') applyFilters(); }catch(e){}
        alert('Amande créée');
    }).catch(err=>{ alert(err.error || 'Erreur création amande'); });
}
