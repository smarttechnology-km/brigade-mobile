let alertsLastEditorRange = null;

function initDescriptionQuillOnce() {
    if (window.alertsDescriptionQuill) return;

    // Quill's bundled Size style attributor ships with its OWN default whitelist
    // (10px/18px/32px) — any other value is silently rejected unless we clear it here.
    const SizeStyle = Quill.import('attributors/style/size');
    SizeStyle.whitelist = null;
    Quill.register(SizeStyle, true);

    window.alertsDescriptionQuill = new Quill('#alert-description-editor', {
        theme: 'snow',
        placeholder: "Détails de l'alerte...",
        modules: {
            toolbar: '#alert-description-toolbar',
        },
    });

    // Quill's own Selection module saves the range on blur and restores it when
    // focus() is called (which getSelection(true) does). We ALSO track it ourselves
    // as a fallback, since clicking into the px input blurs the editor.
    window.alertsDescriptionQuill.on('selection-change', function (range) {
        if (range && range.length > 0) alertsLastEditorRange = range;
    });

    const sizeInput = document.getElementById('alert-description-size-input');
    sizeInput.value = '12';

    // Case 1: text is actually selected -> restyle it live, on every keystroke.
    // formatText() works purely on the document model by index/length, so it never
    // touches browser focus and never interrupts typing in this input.
    function applySizeToSelection() {
        const val = parseInt(sizeInput.value, 10);
        if (!val || val < 1) return;
        const range = alertsLastEditorRange;
        if (!range || range.length === 0) return;
        window.alertsDescriptionQuill.formatText(range.index, range.length, 'size', val + 'px', 'user');
    }

    // Case 2: nothing selected -> the size should apply to the NEXT characters typed,
    // not to existing text. This needs Quill's selection focused on a collapsed cursor,
    // which steals browser focus — so only do this once the user leaves the input
    // (blur / Enter), never on every keystroke, otherwise typing a 2-digit value here
    // would be interrupted.
    function applySizeForFutureTyping() {
        const val = parseInt(sizeInput.value, 10);
        if (!val || val < 1) return;
        const range = alertsLastEditorRange;
        if (range && range.length > 0) return; // real selection: handled live instead
        const quill = window.alertsDescriptionQuill;
        const cursorIndex = range ? range.index : Math.max(0, quill.getLength() - 1);
        quill.setSelection(cursorIndex, 0, 'silent');
        quill.format('size', val + 'px', 'user');
    }

    sizeInput.addEventListener('input', applySizeToSelection);
    sizeInput.addEventListener('blur', applySizeForFutureTyping);
    sizeInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            applySizeToSelection();
            applySizeForFutureTyping();
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    window.alertsCurrentItems = [];
    window.alertsCurrentFilter = 'active';
    window.alertsSelectedPhotos = [];
    window.alertsPrimaryIndex = 0;
    window.alertsSelectedVehicles = [];
    window.alertsContactPhones = [];
    window.alertsEditingId = null;
    window.alertsExistingPhotos = [];
    window.alertsPrimaryExistingId = null;

    loadAlerts();

    document.querySelectorAll('#alerts-filter-group button').forEach(function (btn) {
        btn.addEventListener('click', function () {
            document.querySelectorAll('#alerts-filter-group button').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            window.alertsCurrentFilter = btn.dataset.filter;
            renderAlertsTable();
        });
    });

    document.getElementById('alert-type').addEventListener('change', updateConditionalFields);
    document.getElementById('alert-photos').addEventListener('change', handlePhotosSelected);
    document.getElementById('alert-create-submit').addEventListener('click', submitAlertForm);

    let vehicleSearchTimer = null;
    const vehicleSearchInput = document.getElementById('alert-vehicle-search');
    vehicleSearchInput.addEventListener('input', function () {
        clearTimeout(vehicleSearchTimer);
        const q = vehicleSearchInput.value.trim();
        if (!q) { hideVehicleResults(); return; }
        vehicleSearchTimer = setTimeout(function () { searchVehiclesForAlert(q); }, 300);
    });
    document.addEventListener('click', function (e) {
        const wrap = document.getElementById('alert-vehicles-wrap');
        if (wrap && !wrap.contains(e.target)) hideVehicleResults();
    });

    document.getElementById('alert-contact-phone-add').addEventListener('click', addContactPhoneToAlert);
    document.getElementById('alert-contact-phone-input').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            addContactPhoneToAlert();
        }
    });

    document.getElementById('alert-create-modal').addEventListener('show.bs.modal', function () {
        initDescriptionQuillOnce();
        prefillDates();
        updateConditionalFields();
    });
    document.getElementById('alert-create-modal').addEventListener('hidden.bs.modal', function () {
        resetAlertForm();
    });
});

const ALERT_TYPE_META = {
    accident:              { icon: 'fas fa-car-burst',       color: '#dc3545', label: 'Accident' },
    recherche_vehicule:    { icon: 'fas fa-magnifying-glass', color: '#6f42c1', label: 'Recherche de véhicule' },
    route_construction:    { icon: 'fas fa-road',             color: '#fd7e14', label: 'Route en construction' },
    evenement_circulation: { icon: 'fas fa-triangle-exclamation', color: '#ffc107', label: 'Évènement bloquant la circulation' },
    travaux_planifies:     { icon: 'fas fa-helmet-safety',    color: '#0d6efd', label: 'Travaux planifiés' },
};
const VEHICLE_LINK_TYPES = ['accident', 'recherche_vehicule'];
const ZONE_TYPES = ['route_construction', 'evenement_circulation', 'travaux_planifies'];

function pad2(n) { return String(n).padStart(2, '0'); }
function toLocalDatetimeInputValue(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function prefillDates() {
    const startsInput = document.getElementById('alert-starts-at');
    const expiresInput = document.getElementById('alert-expires-at');
    if (!startsInput.value) {
        const now = new Date();
        startsInput.value = toLocalDatetimeInputValue(now);
        const plus3h = new Date(now.getTime() + 3 * 60 * 60 * 1000);
        expiresInput.value = toLocalDatetimeInputValue(plus3h);
    }
}

function updateConditionalFields() {
    const type = document.getElementById('alert-type').value;
    document.getElementById('alert-vehicles-wrap').classList.toggle('d-none', !VEHICLE_LINK_TYPES.includes(type));
    document.getElementById('alert-contact-phones-wrap').classList.toggle('d-none', type !== 'recherche_vehicule');
    document.getElementById('alert-zone-wrap').classList.toggle('d-none', !ZONE_TYPES.includes(type));
    document.getElementById('alert-custom-type-wrap').classList.toggle('d-none', type !== 'autre');
}

function searchVehiclesForAlert(q) {
    fetch(`/api/vehicles/query?q=${encodeURIComponent(q)}`)
        .then(function (r) { return r.json(); })
        .then(function (list) {
            renderVehicleResults(Array.isArray(list) ? list : []);
        })
        .catch(function () { hideVehicleResults(); });
}

function renderVehicleResults(list) {
    const box = document.getElementById('alert-vehicle-results');
    const selectedIds = window.alertsSelectedVehicles.map(function (v) { return v.id; });
    window.alertsVehicleSearchResults = list.filter(function (v) { return !selectedIds.includes(v.id); });
    if (!window.alertsVehicleSearchResults.length) {
        box.innerHTML = '<div class="list-group-item text-muted small">Aucun véhicule trouvé</div>';
        box.classList.remove('d-none');
        return;
    }
    box.innerHTML = window.alertsVehicleSearchResults.map(function (v, idx) {
        return `<button type="button" class="list-group-item list-group-item-action" onclick="addVehicleToAlertByIndex(${idx})">
            <strong>${escapeHtml(v.license_plate)}</strong>${v.owner_name ? ' — ' + escapeHtml(v.owner_name) : ''}
        </button>`;
    }).join('');
    box.classList.remove('d-none');
}

function addVehicleToAlertByIndex(idx) {
    const vehicle = (window.alertsVehicleSearchResults || [])[idx];
    if (vehicle) addVehicleToAlert(vehicle);
}

function hideVehicleResults() {
    const box = document.getElementById('alert-vehicle-results');
    box.classList.add('d-none');
    box.innerHTML = '';
}

function addVehicleToAlert(vehicle) {
    if (!window.alertsSelectedVehicles.some(function (v) { return v.id === vehicle.id; })) {
        window.alertsSelectedVehicles.push(vehicle);
    }
    document.getElementById('alert-vehicle-search').value = '';
    hideVehicleResults();
    renderVehicleChips();
}

function removeVehicleFromAlert(id) {
    window.alertsSelectedVehicles = window.alertsSelectedVehicles.filter(function (v) { return v.id !== id; });
    renderVehicleChips();
}

function renderVehicleChips() {
    const container = document.getElementById('alert-vehicle-chips');
    container.innerHTML = window.alertsSelectedVehicles.map(function (v) {
        return `<span class="badge bg-secondary d-inline-flex align-items-center gap-1 py-2 px-2">
            <i class="fas fa-car"></i> ${escapeHtml(v.license_plate)}
            <button type="button" class="btn-close btn-close-white" style="font-size:.6rem;" onclick="removeVehicleFromAlert(${v.id})"></button>
        </span>`;
    }).join('');
}

function addContactPhoneToAlert() {
    const input = document.getElementById('alert-contact-phone-input');
    const value = input.value.trim();
    if (!value) return;
    if (!window.alertsContactPhones.includes(value)) {
        window.alertsContactPhones.push(value);
    }
    input.value = '';
    input.focus();
    renderContactPhoneChips();
}

function removeContactPhoneFromAlert(idx) {
    window.alertsContactPhones.splice(idx, 1);
    renderContactPhoneChips();
}

function renderContactPhoneChips() {
    const container = document.getElementById('alert-contact-phone-chips');
    container.innerHTML = window.alertsContactPhones.map(function (phone, idx) {
        return `<span class="badge bg-secondary d-inline-flex align-items-center gap-1 py-2 px-2">
            <i class="fas fa-phone"></i> ${escapeHtml(phone)}
            <button type="button" class="btn-close btn-close-white" style="font-size:.6rem;" onclick="removeContactPhoneFromAlert(${idx})"></button>
        </span>`;
    }).join('');
}

function handlePhotosSelected(e) {
    window.alertsSelectedPhotos = Array.from(e.target.files || []);
    window.alertsPrimaryIndex = 0;
    renderPhotosPreview();
}

function renderPhotosPreview() {
    const container = document.getElementById('alert-photos-preview');
    if (!window.alertsSelectedPhotos.length) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = window.alertsSelectedPhotos.map(function (file, idx) {
        const url = URL.createObjectURL(file);
        const checked = idx === window.alertsPrimaryIndex ? 'checked' : '';
        return `<div class="text-center" style="width:90px;">
            <img src="${url}" style="width:90px;height:90px;object-fit:cover;border-radius:8px;border:2px solid ${idx === window.alertsPrimaryIndex ? '#dc3545' : '#dee2e6'};">
            <div class="form-check form-check-inline mt-1" style="font-size:.75rem;">
                <input class="form-check-input" type="radio" name="alert-primary-photo" id="primary-photo-${idx}" ${checked} onchange="setPrimaryPhoto(${idx})">
                <label class="form-check-label" for="primary-photo-${idx}">Principale</label>
            </div>
        </div>`;
    }).join('');
}

function setPrimaryPhoto(idx) {
    window.alertsPrimaryIndex = idx;
    window.alertsPrimaryExistingId = null;
    renderPhotosPreview();
    renderExistingPhotos();
}

function loadAlerts() {
    fetch('/api/alerts')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            window.alertsCurrentItems = Array.isArray(data) ? data : [];
            renderAlertsTable();
        })
        .catch(function () {
            document.getElementById('alerts-tbody').innerHTML = '<tr><td colspan="8" class="text-center text-muted">Erreur de chargement</td></tr>';
        });
}

function renderAlertsTable() {
    const tbody = document.getElementById('alerts-tbody');
    let items = window.alertsCurrentItems || [];

    if (window.alertsCurrentFilter === 'active') items = items.filter(function (a) { return !a.is_expired; });
    else if (window.alertsCurrentFilter === 'expired') items = items.filter(function (a) { return a.is_expired; });

    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Aucune alerte</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(function (a, i) {
        const meta = ALERT_TYPE_META[a.alert_type] || { icon: 'fas fa-bell', color: '#6c757d', label: a.alert_type_label };
        const statusBadge = a.is_expired
            ? '<span class="badge bg-secondary">Expirée</span>'
            : '<span class="badge bg-success">Active</span>';
        const vehiclesLine = (a.vehicles && a.vehicles.length)
            ? `<div class="text-muted small mt-1"><i class="fas fa-car me-1"></i>${a.vehicles.map(function (v) { return escapeHtml(v.license_plate); }).join(', ')}</div>`
            : '';
        const zoneLine = a.zone
            ? `<div class="text-muted small mt-1"><i class="fas fa-map-marker-alt me-1"></i>${escapeHtml(a.zone)}</div>`
            : '';
        const extraPhotosBadge = a.photos && a.photos.length > 1
            ? `<span class="badge bg-light text-dark border ms-1">+${a.photos.length - 1}</span>`
            : '';
        const photoMenuItem = a.primary_photo_url
            ? `<li><a class="dropdown-item" href="#" onclick='event.preventDefault(); showAlertPhotos(${JSON.stringify(a.photos)});'><i class="fas fa-camera me-2"></i>Voir les photos${a.photos.length > 1 ? ` <span class="badge bg-light text-dark border ms-1">+${a.photos.length - 1}</span>` : ''}</a></li>`
            : '';
        const descPlain = stripHtml(a.description);
        const descLine = descPlain
            ? `<div class="text-muted small mt-1">${escapeHtml(descPlain.length > 120 ? descPlain.slice(0, 120) + '…' : descPlain)}</div>`
            : '';
        const expireMenuItem = (!a.expires_at_str && !a.is_expired)
            ? `<li><a class="dropdown-item" href="#" onclick="event.preventDefault(); markAlertExpired(${a.id});"><i class="fas fa-flag-checkered me-2"></i>Marquer comme expirée</a></li>`
            : '';
        return `<tr>
            <td>${i + 1}</td>
            <td><strong>${escapeHtml(a.title)}</strong>${descLine}${vehiclesLine}${zoneLine}</td>
            <td><i class="${meta.icon} me-2" style="color:${meta.color};"></i>${escapeHtml(a.alert_type_label)}</td>
            <td>${escapeHtml(a.island)}</td>
            <td>${a.starts_at_str || ''}</td>
            <td>${a.expires_at_str || '<span class="text-muted">—</span>'}</td>
            <td>${statusBadge}</td>
            <td>
                <div class="d-flex align-items-center gap-1">
                    <button type="button" class="btn btn-sm btn-outline-primary" title="Voir le détail" onclick="viewAlert(${a.id})"><i class="fas fa-eye"></i></button>
                    <div class="dropdown">
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown" data-bs-boundary="viewport" aria-expanded="false" title="Plus d'actions">
                            <i class="fas fa-ellipsis-h"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            <li><a class="dropdown-item" href="#" onclick="event.preventDefault(); editAlert(${a.id});"><i class="fas fa-pencil-alt me-2"></i>Modifier</a></li>
                            ${photoMenuItem}
                            ${expireMenuItem}
                        </ul>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-danger" title="Supprimer" onclick="deleteAlert(${a.id})"><i class="fas fa-trash"></i></button>
                </div>
            </td>
        </tr>`;
    }).join('');

    // Force the "..." actions dropdown to use fixed (viewport-relative) positioning.
    // This escapes ANY ancestor's overflow/clipping entirely (unlike boundary tuning),
    // since position:fixed is not constrained by scrolling/overflow containers.
    tbody.querySelectorAll('[data-bs-toggle="dropdown"]').forEach(function (el) {
        new bootstrap.Dropdown(el, { popperConfig: { strategy: 'fixed' } });
    });
}

function viewAlert(id) {
    const a = (window.alertsCurrentItems || []).find(function (x) { return x.id === id; });
    if (!a) return;

    const meta = ALERT_TYPE_META[a.alert_type] || { icon: 'fas fa-bell', color: '#6c757d' };
    const statusBadge = a.is_expired
        ? '<span class="badge bg-secondary">Expirée</span>'
        : '<span class="badge bg-success">Active</span>';

    const vehiclesBlock = (a.vehicles && a.vehicles.length)
        ? `<div class="col-12">
             <div class="small fw-bold text-muted">Véhicule(s) concerné(s)</div>
             <div>${a.vehicles.map(function (v) {
                 return `<span class="badge bg-secondary me-1"><i class="fas fa-car me-1"></i>${escapeHtml(v.license_plate)}${v.owner_name ? ' — ' + escapeHtml(v.owner_name) : ''}</span>`;
             }).join('')}</div>
           </div>`
        : '';

    const contactPhonesBlock = (a.contact_phones && a.contact_phones.length)
        ? `<div class="col-12">
             <div class="small fw-bold text-muted">Numéro(s) à contacter</div>
             <div>${a.contact_phones.map(function (phone) {
                 return `<span class="badge bg-secondary me-1"><i class="fas fa-phone me-1"></i>${escapeHtml(phone)}</span>`;
             }).join('')}</div>
           </div>`
        : '';

    const zoneBlock = a.zone
        ? `<div class="col-12"><div class="small fw-bold text-muted">Zone concernée</div><div>${escapeHtml(a.zone)}</div></div>`
        : '';

    const descBlock = a.description
        ? `<div class="col-12"><div class="small fw-bold text-muted">Description</div><div>${a.description}</div></div>`
        : '';

    const photosBlock = (a.photos && a.photos.length)
        ? `<div class="col-12">
             <div class="small fw-bold text-muted mb-1">Photos</div>
             <div class="d-flex flex-wrap gap-2">
                 ${a.photos.map(function (p) {
                     return `<div style="position:relative;">
                         <img src="${p.photo_url}" style="width:100px;height:100px;object-fit:cover;border-radius:8px;border:2px solid ${p.is_primary ? '#dc3545' : '#dee2e6'};">
                         ${p.is_primary ? '<span class="badge bg-danger" style="position:absolute;bottom:4px;left:4px;font-size:.6rem;">Principale</span>' : ''}
                     </div>`;
                 }).join('')}
             </div>
           </div>`
        : '';

    document.getElementById('alert-view-modal-body').innerHTML = `
        <div class="row g-3">
            <div class="col-12 d-flex align-items-center justify-content-between">
                <h5 class="mb-0"><i class="${meta.icon} me-2" style="color:${meta.color};"></i>${escapeHtml(a.title)}</h5>
                ${statusBadge}
            </div>
            <div class="col-md-6"><div class="small fw-bold text-muted">Type</div><div>${escapeHtml(a.alert_type_label)}</div></div>
            <div class="col-md-6"><div class="small fw-bold text-muted">Île</div><div>${escapeHtml(a.island)}</div></div>
            <div class="col-md-6"><div class="small fw-bold text-muted">Date de début</div><div>${a.starts_at_str || ''}</div></div>
            <div class="col-md-6"><div class="small fw-bold text-muted">Date de fin</div><div>${a.expires_at_str || '<span class="text-muted">Non définie</span>'}</div></div>
            ${zoneBlock}
            ${vehiclesBlock}
            ${contactPhonesBlock}
            ${descBlock}
            ${photosBlock}
            <div class="col-12 border-top pt-2 d-flex justify-content-between text-muted small">
                <span>Créée par ${escapeHtml(a.created_by || '—')}</span>
                <span>${a.created_at || ''}</span>
            </div>
        </div>
    `;

    const modalEl = document.getElementById('alertViewModal');
    if (modalEl) new bootstrap.Modal(modalEl).show();
}

function editAlert(id) {
    const a = (window.alertsCurrentItems || []).find(function (x) { return x.id === id; });
    if (!a) return;

    window.alertsEditingId = id;
    window.alertsExistingPhotos = (a.photos || []).slice();
    window.alertsPrimaryExistingId = (a.photos || []).find(function (p) { return p.is_primary; })?.id || null;

    document.getElementById('alert-editing-id').value = id;
    document.getElementById('alert-title').value = a.title || '';
    document.getElementById('alert-type').value = a.alert_type;
    document.getElementById('alert-island').value = a.island;
    document.getElementById('alert-starts-at').value = (a.starts_at || '').slice(0, 16);
    document.getElementById('alert-expires-at').value = a.expires_at ? a.expires_at.slice(0, 16) : '';
    document.getElementById('alert-zone').value = a.zone || '';
    document.getElementById('alert-custom-type-label').value = a.custom_type_label || '';
    document.getElementById('alert-send-notification').checked = !!a.send_notification;

    window.alertsSelectedVehicles = (a.vehicles || []).map(function (v) {
        return { id: v.id, license_plate: v.license_plate, owner_name: v.owner_name };
    });
    renderVehicleChips();

    window.alertsContactPhones = (a.contact_phones || []).slice();
    renderContactPhoneChips();

    renderExistingPhotos();

    updateConditionalFields();

    document.getElementById('alertCreateLabel').innerHTML = '<i class="fas fa-pencil-alt me-1"></i>Modifier l\'alerte';
    document.getElementById('alert-create-submit').innerHTML = '<i class="fas fa-check me-1"></i>Enregistrer';

    const modalEl = document.getElementById('alert-create-modal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();

    // Quill needs the editor visible before content can be set reliably
    setTimeout(function () {
        if (window.alertsDescriptionQuill) {
            window.alertsDescriptionQuill.root.innerHTML = a.description || '';
        }
    }, 50);
}

function renderExistingPhotos() {
    const wrap = document.getElementById('alert-existing-photos-wrap');
    const container = document.getElementById('alert-existing-photos');
    const photos = window.alertsExistingPhotos || [];

    if (!photos.length) {
        wrap.classList.add('d-none');
        container.innerHTML = '';
        return;
    }

    wrap.classList.remove('d-none');
    container.innerHTML = photos.map(function (p) {
        const isPrimary = p.id === window.alertsPrimaryExistingId;
        return `<div class="text-center" style="width:90px;">
            <div style="position:relative;">
                <img src="${p.photo_url}" style="width:90px;height:90px;object-fit:cover;border-radius:8px;border:2px solid ${isPrimary ? '#dc3545' : '#dee2e6'};">
                <button type="button" class="btn-close btn-close-white bg-danger rounded-circle p-1" style="position:absolute;top:-6px;right:-6px;font-size:.55rem;" title="Retirer" onclick="removeExistingPhoto(${p.id})"></button>
            </div>
            <div class="form-check form-check-inline mt-1" style="font-size:.75rem;">
                <input class="form-check-input" type="radio" name="alert-primary-existing-photo" id="primary-existing-${p.id}" ${isPrimary ? 'checked' : ''} onchange="setExistingPhotoPrimary(${p.id})">
                <label class="form-check-label" for="primary-existing-${p.id}">Principale</label>
            </div>
        </div>`;
    }).join('');
}

function setExistingPhotoPrimary(photoId) {
    window.alertsPrimaryExistingId = photoId;
    window.alertsPrimaryIndex = null;
    renderExistingPhotos();
    renderPhotosPreview();
}

function removeExistingPhoto(photoId) {
    if (!window.alertsEditingId) return;
    if (!confirm('Retirer cette photo de l\'alerte ?')) return;
    fetch(`/api/alerts/${window.alertsEditingId}/photos/${photoId}`, { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.error) { alert(d.error); return; }
            window.alertsExistingPhotos = d.photos || [];
            window.alertsPrimaryExistingId = (d.photos || []).find(function (p) { return p.is_primary; })?.id || null;
            renderExistingPhotos();
            // keep the table in sync in case the modal is closed without re-saving
            const idx = (window.alertsCurrentItems || []).findIndex(function (x) { return x.id === window.alertsEditingId; });
            if (idx !== -1) window.alertsCurrentItems[idx] = d;
        })
        .catch(function () { alert('Erreur réseau.'); });
}

function showAlertPhotos(photos) {
    const wrap = document.getElementById('alert-photo-modal-body');
    if (!photos || !photos.length) return;
    const sorted = photos.slice().sort(function (a, b) { return (b.is_primary ? 1 : 0) - (a.is_primary ? 1 : 0); });
    wrap.innerHTML = sorted.map(function (p) {
        return `<div class="mb-3">
            ${p.is_primary ? '<span class="badge bg-danger mb-1">Photo principale</span>' : ''}
            <img src="${p.photo_url}" style="max-width:100%; border-radius:8px;">
        </div>`;
    }).join('');
    const modalEl = document.getElementById('alertPhotoModal');
    if (modalEl) new bootstrap.Modal(modalEl).show();
}

function deleteAlert(id) {
    if (!confirm('Supprimer cette alerte ?')) return;
    fetch(`/api/alerts/${id}`, { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.error) { alert(d.error); return; }
            loadAlerts();
        })
        .catch(function () { alert('Erreur réseau.'); });
}

function markAlertExpired(id) {
    if (!confirm("Marquer cette alerte comme expirée ?")) return;
    fetch(`/api/alerts/${id}/expire`, { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.error) { alert(d.error); return; }
            loadAlerts();
        })
        .catch(function () { alert('Erreur réseau.'); });
}

function resetAlertForm() {
    document.getElementById('alert-create-form').reset();
    document.getElementById('alert-create-error').classList.add('d-none');
    document.getElementById('alert-vehicles-wrap').classList.add('d-none');
    document.getElementById('alert-contact-phones-wrap').classList.add('d-none');
    document.getElementById('alert-zone-wrap').classList.add('d-none');
    document.getElementById('alert-custom-type-wrap').classList.add('d-none');
    document.getElementById('alert-existing-photos-wrap').classList.add('d-none');
    window.alertsSelectedPhotos = [];
    window.alertsPrimaryIndex = 0;
    window.alertsSelectedVehicles = [];
    window.alertsContactPhones = [];
    window.alertsEditingId = null;
    window.alertsExistingPhotos = [];
    window.alertsPrimaryExistingId = null;
    document.getElementById('alert-editing-id').value = '';
    document.getElementById('alert-photos-preview').innerHTML = '';
    document.getElementById('alert-vehicle-chips').innerHTML = '';
    document.getElementById('alert-contact-phone-chips').innerHTML = '';
    document.getElementById('alert-existing-photos').innerHTML = '';
    hideVehicleResults();
    if (window.alertsDescriptionQuill) window.alertsDescriptionQuill.setText('');
    document.getElementById('alertCreateLabel').innerHTML = '<i class="fas fa-exclamation-triangle me-1"></i>Ajouter une alerte';
    document.getElementById('alert-create-submit').innerHTML = '<i class="fas fa-check me-1"></i>Créer l\'alerte';
}

function submitAlertForm() {
    const title = document.getElementById('alert-title').value;
    const alertType = document.getElementById('alert-type').value;
    const island = document.getElementById('alert-island').value;
    const startsAt = document.getElementById('alert-starts-at').value;
    const expiresAt = document.getElementById('alert-expires-at').value;
    const zone = document.getElementById('alert-zone').value;
    const customTypeLabel = document.getElementById('alert-custom-type-label').value;
    const descriptionHtml = window.alertsDescriptionQuill.getText().trim()
        ? window.alertsDescriptionQuill.root.innerHTML
        : '';
    const sendNotification = document.getElementById('alert-send-notification').checked;
    const errorBox = document.getElementById('alert-create-error');
    const submitBtn = document.getElementById('alert-create-submit');

    errorBox.classList.add('d-none');

    if (!title.trim() || !alertType || !island || !startsAt) {
        errorBox.textContent = 'Veuillez remplir tous les champs obligatoires (*).';
        errorBox.classList.remove('d-none');
        return;
    }
    if (expiresAt && new Date(expiresAt) <= new Date(startsAt)) {
        errorBox.textContent = 'La date de fin doit être après la date de début.';
        errorBox.classList.remove('d-none');
        return;
    }
    if (alertType === 'autre' && !customTypeLabel.trim()) {
        errorBox.textContent = "Veuillez préciser le type d'alerte.";
        errorBox.classList.remove('d-none');
        return;
    }
    if (ZONE_TYPES.includes(alertType) && !zone.trim()) {
        errorBox.textContent = 'Veuillez préciser la zone concernée.';
        errorBox.classList.remove('d-none');
        return;
    }
    if (VEHICLE_LINK_TYPES.includes(alertType) && !window.alertsSelectedVehicles.length) {
        errorBox.textContent = 'Veuillez sélectionner au moins un véhicule.';
        errorBox.classList.remove('d-none');
        return;
    }
    if (alertType === 'recherche_vehicule' && !window.alertsContactPhones.length) {
        errorBox.textContent = 'Veuillez indiquer au moins un numéro à contacter.';
        errorBox.classList.remove('d-none');
        return;
    }

    const formData = new FormData();
    formData.append('title', title.trim());
    formData.append('alert_type', alertType);
    formData.append('island', island);
    formData.append('starts_at', startsAt);
    if (expiresAt) formData.append('expires_at', expiresAt);
    formData.append('description', descriptionHtml);
    formData.append('send_notification', sendNotification ? '1' : '0');
    if (VEHICLE_LINK_TYPES.includes(alertType)) {
        window.alertsSelectedVehicles.forEach(function (v) {
            formData.append('vehicle_ids', v.id);
        });
    }
    if (ZONE_TYPES.includes(alertType) && zone.trim()) {
        formData.append('zone', zone.trim());
    }
    if (alertType === 'recherche_vehicule') {
        window.alertsContactPhones.forEach(function (phone) {
            formData.append('contact_phones', phone);
        });
    }
    if (alertType === 'autre' && customTypeLabel.trim()) {
        formData.append('custom_type_label', customTypeLabel.trim());
    }
    (window.alertsSelectedPhotos || []).forEach(function (file) {
        formData.append('photos', file);
    });
    if (window.alertsPrimaryExistingId) {
        formData.append('primary_photo_id', window.alertsPrimaryExistingId);
    } else {
        formData.append('primary_index', window.alertsPrimaryIndex || 0);
    }

    const isEditing = !!window.alertsEditingId;
    const url = isEditing ? `/api/alerts/${window.alertsEditingId}` : '/api/alerts';
    const method = isEditing ? 'PUT' : 'POST';
    const loadingText = isEditing ? 'Enregistrement...' : 'Création...';
    const idleText = isEditing ? 'Enregistrer' : "Créer l'alerte";

    submitBtn.disabled = true;
    submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-1"></i>${loadingText}`;

    fetch(url, { method: method, body: formData })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
            if (!res.ok) {
                errorBox.textContent = res.data.error || "Erreur lors de l'enregistrement.";
                errorBox.classList.remove('d-none');
                return;
            }
            bootstrap.Modal.getInstance(document.getElementById('alert-create-modal')).hide();
            loadAlerts();
        })
        .catch(function () {
            errorBox.textContent = 'Erreur réseau.';
            errorBox.classList.remove('d-none');
        })
        .finally(function () {
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<i class="fas fa-check me-1"></i>${idleText}`;
        });
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function stripHtml(html) {
    if (!html) return '';
    const div = document.createElement('div');
    div.innerHTML = html;
    return (div.textContent || div.innerText || '').trim();
}
