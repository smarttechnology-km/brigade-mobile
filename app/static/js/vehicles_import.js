const IMPORT_TEMPLATE_HEADERS = [
  'license_plate', 'owner_name', 'owner_phone', 'owner_island', 'vehicle_type',
  'fuel_type', 'make', 'model', 'year', 'vin', 'color', 'owner_address',
  'status', 'notes', 'registration_date',
  'places_assises', 'poids_total_autorise', 'poids_a_vide', 'charge_utile_ptc',
  'profession_proprietaire',
];

document.addEventListener('DOMContentLoaded', function () {
  const templateBtn = document.getElementById('btn-import-template');
  if (templateBtn) templateBtn.addEventListener('click', downloadImportTemplate);

  const submitBtn = document.getElementById('btn-import-submit');
  if (submitBtn) submitBtn.addEventListener('click', submitVehicleImport);
});

function downloadImportTemplate() {
  const csv = IMPORT_TEMPLATE_HEADERS.join(',') + '\n';
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'modele_import_vehicules.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function submitVehicleImport() {
  const fileInput = document.getElementById('import-vehicles-file');
  const resultEl = document.getElementById('import-vehicles-result');
  const submitBtn = document.getElementById('btn-import-submit');
  if (!fileInput || !fileInput.files || !fileInput.files.length) {
    if (resultEl) resultEl.innerHTML = '<div class="alert alert-warning small">Sélectionnez un fichier CSV.</div>';
    return;
  }

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  if (submitBtn) { submitBtn.disabled = true; submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Import en cours...'; }
  if (resultEl) resultEl.innerHTML = '';

  fetch('/api/vehicles/import', {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  })
    .then(resp => resp.json().then(body => ({ ok: resp.ok, body })))
    .then(({ ok, body }) => {
      if (!ok) throw body;
      renderImportResult(body);
      fileInput.value = '';
      if (typeof loadVehicles === 'function') loadVehicles();
    })
    .catch(err => {
      if (resultEl) {
        resultEl.innerHTML = `<div class="alert alert-danger small"><i class="fas fa-exclamation-triangle me-1"></i>${(err && err.error) || "Échec de l'import."}</div>`;
      }
    })
    .finally(() => {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = '<i class="fas fa-file-import me-1"></i>Importer'; }
    });
}

function renderImportResult(res) {
  const resultEl = document.getElementById('import-vehicles-result');
  if (!resultEl) return;

  let html = `<div class="alert alert-success small">
    <i class="fas fa-check-circle me-1"></i><strong>${res.imported}</strong> véhicule(s) importé(s) sur ${res.total_rows} ligne(s) lue(s).
  </div>`;

  if (res.skipped_duplicates > 0) {
    html += `<div class="alert alert-warning small">
      <i class="fas fa-clone me-1"></i><strong>${res.skipped_duplicates}</strong> ligne(s) ignorée(s) — immatriculation déjà existante`;
    if (res.duplicate_samples && res.duplicate_samples.length) {
      html += ` (ex: ${res.duplicate_samples.slice(0, 10).join(', ')}${res.skipped_duplicates > 10 ? '…' : ''})`;
    }
    html += `</div>`;
  }

  if (res.skipped_invalid > 0) {
    html += `<div class="alert alert-secondary small">
      <i class="fas fa-ban me-1"></i><strong>${res.skipped_invalid}</strong> ligne(s) ignorée(s) — immatriculation ou propriétaire manquant
    </div>`;
  }

  resultEl.innerHTML = html;
}
