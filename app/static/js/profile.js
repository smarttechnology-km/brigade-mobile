document.addEventListener('DOMContentLoaded', function(){
  loadProfile();
  const save = document.getElementById('p-save'); if(save) save.addEventListener('click', saveProfile);
  const change = document.getElementById('p-change-password'); if(change) change.addEventListener('click', changePassword);
});

function showMsg(m, ok){
  const el = document.getElementById('profile-msg'); if(!el) return;
  el.innerHTML = `<div class="alert ${ok ? 'alert-success' : 'alert-danger'} alert-dismissible fade show" role="alert">${m}<button type=\"button\" class=\"btn-close\" data-bs-dismiss=\"alert\" aria-label=\"Close\"></button></div>`;
  if(ok){ setTimeout(()=>{ if(el) el.innerHTML=''; }, 4000); }
}

function loadProfile(){
  fetch('/api/users/me').then(r=>r.json()).then(data=>{
    document.getElementById('p-username').value = data.username || '';
    document.getElementById('p-fullname').value = data.full_name || '';
    document.getElementById('p-email').value = data.email || '';
    document.getElementById('p-phone').value = data.phone || '';
    document.getElementById('p-active').checked = data.is_active === true;
  }).catch(err=>{ console.error('load profile failed', err); });
}

function saveProfile(){
  const full_name = document.getElementById('p-fullname').value.trim();
  const email = document.getElementById('p-email').value.trim();
  const phone = document.getElementById('p-phone').value.trim();
  const is_active = !!document.getElementById('p-active').checked;
  fetch('/api/users/profile', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({full_name, email, phone, is_active}) })
    .then(resp=>resp.json().then(j=>({ok:resp.ok, body:j})))
    .then(r=>{ if(!r.ok) throw r.body; showMsg('Profil mis à jour.', true); setTimeout(()=>showMsg('',true),3000); })
    .catch(e=>{ console.error(e); showMsg(e.error || 'Erreur mise à jour', false); });
}

function changePassword(){
  const oldp = document.getElementById('p-old-password').value;
  const newp = document.getElementById('p-new-password').value;
  const newpc = document.getElementById('p-new-password-confirm').value;
  if(!oldp || !newp){ showMsg('Complétez les champs de mot de passe', false); return; }
  if(newp !== newpc){ showMsg('Les mots de passe ne correspondent pas', false); return; }
  fetch('/api/users/profile/password', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({current_password: oldp, new_password: newp}) })
    .then(resp=>resp.json().then(j=>({ok:resp.ok, body:j})))
    .then(r=>{ if(!r.ok) throw r.body; showMsg('Mot de passe changé.', true); document.getElementById('p-old-password').value=''; document.getElementById('p-new-password').value=''; document.getElementById('p-new-password-confirm').value=''; })
    .catch(e=>{ console.error(e); showMsg(e.error || 'Erreur changement mot de passe', false); });
}
