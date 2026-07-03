(function () {
    'use strict';

    let currentPage = 1;
    let searchTimer;
    let _lastKey = null;
    let _settings  = { initial_points: 12, temp_validity_months: 12 };

    const searchInput  = document.getElementById('search-input');
    const statusFilter = document.getElementById('status-filter');
    const typeFilter   = document.getElementById('type-filter');
    const tbody        = document.getElementById('licenses-tbody');

    /* ── Helpers ── */
    function esc(s) {
        return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function fmtDate(iso) {
        if (!iso) return '—';
        const [y, m, d] = iso.split('-');
        return `${d}/${m}/${y}`;
    }

    function statusBadge(status, isExpired) {
        if (isExpired && status === 'actif') status = 'expire';
        const map = {
            actif:    ['bg-success',             'Actif'],
            suspendu: ['bg-warning text-dark',   'Suspendu'],
            revoque:  ['bg-danger',              'Révoqué'],
            expire:   ['bg-secondary',           'Expiré'],
        };
        const [cls, label] = map[status] || ['bg-secondary', status];
        return `<span class="badge ${cls}">${label}</span>`;
    }

    function pointsBadge(pts) {
        const max = _settings.initial_points || 12;
        const n   = pts ?? max;
        const cls = n >= max * 0.75 ? 'bg-success' : n >= max * 0.4 ? 'bg-warning text-dark' : 'bg-danger';
        return `<span class="badge ${cls}">${n}/${max}</span>`;
    }

    function catBadges(cats) {
        if (!cats) return '<span class="text-muted">—</span>';
        return cats.split(',').map(c => c.trim()).filter(Boolean)
            .map(c => `<span class="badge bg-info text-dark me-1">${esc(c)}</span>`).join('');
    }

    /* ── Load table ── */
    function buildUrl() {
        const q      = encodeURIComponent(searchInput.value.trim());
        const status = encodeURIComponent(statusFilter.value);
        const type   = encodeURIComponent(typeFilter.value);
        return `/api/licenses?page=${currentPage}&q=${q}&status=${status}&type=${type}`;
    }

    function loadLicenses(resetPage) {
        if (resetPage) currentPage = 1;
        fetch(buildUrl(), { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (!data) return;
                renderTable(data);
                renderPagination(data);
            })
            .catch(() => {});
    }

    function renderTable(data) {
        if (!data.items.length) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Aucun permis trouvé.</td></tr>';
            return;
        }
        const offset = (data.page - 1) * data.per_page;
        tbody.innerHTML = data.items.map((l, i) => `
            <tr class="${l.print_status === 'pending' ? 'table-warning' : l.print_status === 'printed' ? 'table-success' : ''}">
                <td class="text-muted">${offset + i + 1}</td>
                <td><strong>${esc(l.license_number)}</strong></td>
                <td>
                    <div class="d-flex align-items-center gap-2">
                        ${l.photo_filename
                            ? `<img src="/uploads/license_photos/${esc(l.photo_filename)}" style="width:32px;height:38px;object-fit:cover;border-radius:4px;border:1px solid #dee2e6;" alt="">`
                            : `<span style="width:32px;height:38px;display:inline-flex;align-items:center;justify-content:center;background:#f0f0f0;border-radius:4px;color:#aaa;font-size:1rem;"><i class="fas fa-user"></i></span>`
                        }
                        <div>
                            <div class="fw-semibold">${esc(l.holder_firstname ? l.holder_firstname + ' ' + l.holder_name : l.holder_name)}</div>
                            <div class="text-muted small">${esc(l.holder_phone || '—')}</div>
                        </div>
                    </div>
                </td>
                <td>${esc(l.holder_island || '—')}</td>
                <td>${catBadges(l.categories)}</td>
                <td>${l.type_permis === 'temporaire'
                    ? '<span class="badge bg-warning text-dark">T</span>'
                    : '<span class="badge bg-success">P</span>'}</td>
                <td class="text-muted">${fmtDate(l.expiry_date)}</td>
                <td>${pointsBadge(l.points)}</td>
                <td>${statusBadge(l.status, l.is_expired)}</td>
                <td style="white-space:nowrap;">
                    <button class="btn btn-sm btn-outline-primary" title="Détails" onclick="viewLicense(${l.id})"><i class="fas fa-eye"></i></button>
                    <button class="btn btn-sm btn-outline-warning" title="Modifier" onclick="editLicense(${l.id})"><i class="fas fa-edit"></i></button>
                    ${l.status === 'revoque'
                        ? (window.CURRENT_USER_ROLE === 'administrateur'
                            ? `<button class="btn btn-sm btn-outline-success" title="Réinitialiser les points" onclick="resetPoints(${l.id}, '${esc(l.license_number)}')"><i class="fas fa-redo"></i></button>`
                            : `<button class="btn btn-sm btn-outline-secondary" title="Réservé à l'administrateur" disabled><i class="fas fa-lock"></i></button>`)
                        : `<button class="btn btn-sm btn-outline-danger" title="Réduire les points" onclick="openReductionModal(${l.id}, '${esc(l.license_number)}', ${l.points ?? 0})"><i class="fas fa-minus-circle"></i></button>`
                    }
                    <button class="btn btn-sm btn-outline-danger" title="Supprimer" onclick="deleteLicense(${l.id}, '${esc(l.license_number)}')"><i class="fas fa-trash"></i></button>
                </td>
            </tr>
        `).join('');
    }

    function renderPagination(data) {
        const wrap = document.getElementById('pagination-wrap');
        const info = document.getElementById('pagination-info');
        const btns = document.getElementById('pagination-btns');

        if (data.pages <= 1) { wrap.style.display = 'none'; return; }
        wrap.style.removeProperty('display');

        const s = (data.page - 1) * data.per_page + 1;
        const e = Math.min(data.page * data.per_page, data.total);
        info.textContent = `${s}–${e} sur ${data.total}`;

        let h = `<button class="btn btn-sm btn-outline-secondary" ${data.page <= 1 ? 'disabled' : ''} onclick="goPage(${data.page - 1})">‹</button>`;
        const from = Math.max(1, data.page - 2);
        const to   = Math.min(data.pages, data.page + 2);
        for (let p = from; p <= to; p++) {
            h += `<button class="btn btn-sm ${p === data.page ? 'btn-primary' : 'btn-outline-secondary'}" onclick="goPage(${p})">${p}</button>`;
        }
        h += `<button class="btn btn-sm btn-outline-secondary" ${data.page >= data.pages ? 'disabled' : ''} onclick="goPage(${data.page + 1})">›</button>`;
        btns.innerHTML = h;
    }

    window.goPage = function (p) { currentPage = p; loadLicenses(false); };

    /* ── Real-time polling ── */
    function checkUpdates() {
        if (document.hidden) return;
        fetch('/api/licenses/last-update', { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : null)
            .then(d => {
                if (!d) return;
                if (_lastKey === null) { _lastKey = d.key; return; }
                if (d.key !== _lastKey) { _lastKey = d.key; loadLicenses(false); loadStats(); }
            }).catch(() => {});
    }
    setInterval(checkUpdates, 5000);
    setInterval(loadStats, 30000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) checkUpdates(); });

    /* ── Filters ── */
    searchInput?.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => loadLicenses(true), 400);
    });
    statusFilter?.addEventListener('change', () => loadLicenses(true));
    typeFilter?.addEventListener('change',   () => loadLicenses(true));

    /* ── Photo preview ── */
    window.previewPhoto = function (input) {
        const file = input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            document.getElementById('photo-preview-img').src = e.target.result;
            document.getElementById('photo-preview-img').style.display = '';
            document.getElementById('photo-preview-icon').style.display = 'none';
        };
        reader.readAsDataURL(file);
    };

    /* ── Form helpers ── */
    function clearForm() {
        ['f-id','f-license_number','f-holder_name','f-holder_firstname','f-holder_phone','f-holder_address',
         'f-nationalite','f-lieu_naissance','f-centre_immatriculation',
         'f-date_of_birth','f-issue_date','f-expiry_date','f-notes'].forEach(id => {
            document.getElementById(id).value = '';
        });
        document.getElementById('f-holder_island').value = '';
        document.getElementById('f-sexe').value = '';
        document.getElementById('f-status').value = 'actif';
        document.getElementById('f-points').value = '12';
        document.getElementById('f-type_permis').value = 'permanent';
        onTypePermisChange();
        document.getElementById('f-photo').value = '';
        document.getElementById('photo-preview-img').src = '';
        document.getElementById('photo-preview-img').style.display = 'none';
        document.getElementById('photo-preview-icon').style.display = '';
        document.querySelectorAll('.cat-checkbox').forEach(cb => cb.checked = false);
        document.querySelectorAll('.cat-details').forEach(d => d.style.display = 'none');
        document.querySelectorAll('.cat-identifiant, .cat-date, .cat-expiration').forEach(i => i.value = '');
    }

    function populateForm(l) {
        document.getElementById('f-id').value              = l.id;
        document.getElementById('f-license_number').value  = l.license_number;
        document.getElementById('f-holder_name').value     = l.holder_name;
        document.getElementById('f-holder_firstname').value= l.holder_firstname || '';
        document.getElementById('f-holder_phone').value   = l.holder_phone || '';
        document.getElementById('f-holder_island').value  = l.holder_island || '';
        document.getElementById('f-holder_address').value = l.holder_address || '';
        document.getElementById('f-nationalite').value          = l.nationalite || '';
        document.getElementById('f-sexe').value                 = l.sexe || '';
        document.getElementById('f-points').value               = l.points ?? 12;
        document.getElementById('f-lieu_naissance').value        = l.lieu_naissance || '';
        document.getElementById('f-centre_immatriculation').value= l.centre_immatriculation || '';
        document.getElementById('f-type_permis').value           = l.type_permis || 'permanent';
        onTypePermisChange();
        document.getElementById('f-date_of_birth').value = l.date_of_birth || '';
        document.getElementById('f-issue_date').value   = l.issue_date || '';
        document.getElementById('f-expiry_date').value  = l.expiry_date || '';
        document.getElementById('f-status').value       = l.status || 'actif';
        document.getElementById('f-notes').value        = l.notes || '';
        const cats = (l.categories || '').split(',').map(c => c.trim()).filter(Boolean);
        const catDetails = l.category_details || {};
        document.querySelectorAll('.cat-checkbox').forEach(cb => {
            const cat = cb.value;
            cb.checked = cats.includes(cat);
            const detailsDiv = document.getElementById(`cat-details-${cat}`);
            if (detailsDiv) detailsDiv.style.display = cb.checked ? '' : 'none';
            const d = catDetails[cat] || {};
            const idInput   = document.getElementById(`cat-identifiant-${cat}`);
            const dateInput = document.getElementById(`cat-date-${cat}`);
            const expInput  = document.getElementById(`cat-expiration-${cat}`);
            if (idInput)   idInput.value = d.identifiant || (cb.checked ? (l.license_number || '') : '');
            if (dateInput) dateInput.value = d.date || '';
            if (expInput)  expInput.value = d.expiration || '';
        });
        if (l.photo_filename) {
            const img = document.getElementById('photo-preview-img');
            img.src = `/uploads/license_photos/${l.photo_filename}`;
            img.style.display = '';
            document.getElementById('photo-preview-icon').style.display = 'none';
        }
    }

    function getCategories() {
        return Array.from(document.querySelectorAll('.cat-checkbox:checked')).map(cb => cb.value).join(',');
    }

    function getCategoryDetails() {
        const details = {};
        document.querySelectorAll('.cat-checkbox:checked').forEach(cb => {
            const cat = cb.value;
            const identifiant = document.getElementById(`cat-identifiant-${cat}`)?.value.trim() || '';
            const date = document.getElementById(`cat-date-${cat}`)?.value || '';
            const expiration = document.getElementById(`cat-expiration-${cat}`)?.value || '';
            if (identifiant || date || expiration) {
                details[cat] = { identifiant, date, expiration };
            }
        });
        return details;
    }

    window.onCategoryToggle = function (cat) {
        const cb = document.getElementById(`cat-${cat}`);
        const detailsDiv = document.getElementById(`cat-details-${cat}`);
        if (!detailsDiv) return;
        detailsDiv.style.display = cb && cb.checked ? '' : 'none';
        if (cb && cb.checked) {
            const idInput = document.getElementById(`cat-identifiant-${cat}`);
            if (idInput && !idInput.value.trim()) {
                idInput.value = document.getElementById('f-license_number')?.value || '';
            }
            window.autoFillCategoryExpiration(cat);
        }
        if (!cb || !cb.checked) {
            const idInput   = document.getElementById(`cat-identifiant-${cat}`);
            const dateInput = document.getElementById(`cat-date-${cat}`);
            const expInput  = document.getElementById(`cat-expiration-${cat}`);
            if (idInput)   idInput.value = '';
            if (dateInput) dateInput.value = '';
            if (expInput)  expInput.value = '';
        }
    };

    /* ── Settings ── */
    let _reasons = [];

    function loadSettings() {
        fetch('/api/licenses/settings', { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) { _settings = d; loadLicenses(false); } })
            .catch(() => {});
    }

    // ── Articles de retrait de point ─────────────────────────────────────
    let _pointArticles = [];

    window.loadPointArticles = async function loadPointArticles() {
        try {
            const r = await fetch('/api/licenses/point-articles', { credentials: 'same-origin' });
            const data = r.ok ? await r.json() : [];
            _pointArticles = data;
            renderPointArticlesList();
            const sel = document.getElementById('s-reason-article');
            if (sel) {
                const cur = sel.value;
                sel.innerHTML = '<option value="">— aucun —</option>' +
                    data.map(a => `<option value="${a.id}">${esc(a.code)}${a.description ? ' — ' + esc(a.description) : ''}</option>`).join('');
                sel.value = cur;
            }
        } catch {}
    };

    function renderPointArticlesList() {
        const el = document.getElementById('point-articles-list');
        if (!el) return;
        if (!_pointArticles.length) {
            el.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Aucun article défini.</td></tr>';
            return;
        }
        el.innerHTML = _pointArticles.map(a => `
            <tr>
                <td><strong>${esc(a.code)}</strong></td>
                <td class="text-muted small">${esc(a.description || '—')}</td>
                <td>
                    <button class="btn btn-sm btn-outline-warning me-1" onclick="editPointArticle(${a.id})" title="Modifier"><i class="fas fa-edit"></i></button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deletePointArticle(${a.id})" title="Supprimer"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`).join('');
    }

    window.savePointArticle = async function () {
        const editingId  = document.getElementById('s-article-editing-id').value;
        const code       = document.getElementById('s-article-code').value.trim();
        const description = document.getElementById('s-article-description').value.trim();
        if (!code) { alert('N° article obligatoire.'); return; }
        const url    = editingId ? `/api/licenses/point-articles/${editingId}` : '/api/licenses/point-articles';
        const method = editingId ? 'PUT' : 'POST';
        const r = await fetch(url, { method, headers: {'Content-Type':'application/json'}, credentials: 'same-origin', body: JSON.stringify({ code, description }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.error || 'Erreur'); return; }
        resetPointArticleForm();
        loadPointArticles();
    };

    window.editPointArticle = function (id) {
        const a = _pointArticles.find(x => x.id === id);
        if (!a) return;
        document.getElementById('s-article-editing-id').value = a.id;
        document.getElementById('s-article-code').value        = a.code;
        document.getElementById('s-article-description').value = a.description || '';
        const btn = document.getElementById('s-article-submit-btn');
        if (btn) { btn.innerHTML = '<i class="fas fa-save me-1"></i>Modifier'; btn.className = 'btn btn-warning'; }
        document.getElementById('s-article-cancel-btn')?.classList.remove('d-none');
    };

    window.cancelEditPointArticle = function () { resetPointArticleForm(); };

    window.deletePointArticle = async function (id) {
        if (!confirm('Supprimer cet article ?')) return;
        await fetch(`/api/licenses/point-articles/${id}`, { method: 'DELETE', credentials: 'same-origin' });
        resetPointArticleForm();
        loadPointArticles();
    };

    function resetPointArticleForm() {
        document.getElementById('s-article-editing-id').value = '';
        document.getElementById('s-article-code').value = '';
        document.getElementById('s-article-description').value = '';
        const btn = document.getElementById('s-article-submit-btn');
        if (btn) { btn.innerHTML = '<i class="fas fa-plus me-1"></i>Ajouter'; btn.className = 'btn btn-outline-primary'; }
        document.getElementById('s-article-cancel-btn')?.classList.add('d-none');
    }

    // ── Motifs de réduction ───────────────────────────────────────────────
    window.loadReasons = function loadReasons() {
        loadPointArticles().then(() => {
            fetch('/api/licenses/point-reasons', { credentials: 'same-origin' })
                .then(r => r.ok ? r.json() : [])
                .then(data => {
                    _reasons = data;
                    renderReasonsList();
                }).catch(() => {});
        });
    }

    function renderReasonsList() {
        const el = document.getElementById('reasons-list');
        if (!el) return;
        if (!_reasons.length) {
            el.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Aucun motif défini.</td></tr>';
            return;
        }
        el.innerHTML = _reasons.map((r, i) => `
            <tr>
                <td>${i + 1}</td>
                <td>${esc(r.label)}</td>
                <td><span class="badge bg-danger">−${r.points_to_deduct} pt${r.points_to_deduct > 1 ? 's' : ''}</span></td>
                <td>${r.article_code ? `<span class="badge bg-secondary">${esc(r.article_code)}</span>` : '<span class="text-muted">—</span>'}</td>
                <td>
                    <button class="btn btn-sm btn-outline-warning me-1" onclick="editReason(this)" data-id="${r.id}" data-label="${esc(r.label)}" data-pts="${r.points_to_deduct}" data-article="${r.article_id || ''}" title="Modifier">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteReason(${r.id})" title="Supprimer">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>`).join('');
    }

    function loadStatusRules() {
        fetch('/api/licenses/status-rules', { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : [])
            .then(rules => renderStatusRules(rules))
            .catch(() => {});
    }

    function renderStatusRules(rules) {
        const tbody = document.getElementById('status-rules-list');
        if (!tbody) return;
        const opLabel = { lt: '<', lte: '≤', eq: '=' };
        const statusLabel = { suspendu: '<span class="badge bg-warning text-dark">Suspendu</span>', revoque: '<span class="badge bg-danger">Révoqué</span>' };
        if (!rules.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Aucune règle définie.</td></tr>';
            return;
        }
        tbody.innerHTML = rules.map(r => `
            <tr>
                <td>Points <strong>${opLabel[r.operator] || r.operator} ${r.threshold}</strong></td>
                <td>${statusLabel[r.status] || r.status}</td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteStatusRule(${r.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>`).join('');
    }

    window.addStatusRule = async function () {
        const status    = document.getElementById('s-rule-status').value;
        const operator  = document.getElementById('s-rule-operator').value;
        const threshold = parseInt(document.getElementById('s-rule-threshold').value);
        const r = await fetch('/api/licenses/status-rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ status, operator, threshold }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.error || 'Erreur'); return; }
        loadStatusRules();
    };

    window.deleteStatusRule = async function (id) {
        if (!confirm('Supprimer cette règle ?')) return;
        await fetch(`/api/licenses/status-rules/${id}`, { method: 'DELETE', credentials: 'same-origin' });
        loadStatusRules();
    };

    window.applyStatusRules = async function () {
        if (!confirm('Appliquer les règles de statut à tous les permis existants ?')) return;
        const r = await fetch('/api/licenses/status-rules/apply', { method: 'POST', credentials: 'same-origin' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.error || 'Erreur'); return; }
        alert(`${d.updated} permis mis à jour.`);
        loadLicenses(false);
        loadStats();
    };

    function renderSignaturePreview() {
        const img    = document.getElementById('signature-preview-img');
        const empty  = document.getElementById('signature-preview-empty');
        const delBtn = document.getElementById('signature-remove-btn');
        if (_settings.directeur_signature_filename) {
            img.src = `/uploads/signatures/${_settings.directeur_signature_filename}`;
            img.style.display = '';
            empty.style.display = 'none';
            delBtn.style.display = '';
        } else {
            img.style.display = 'none';
            empty.style.display = '';
            delBtn.style.display = 'none';
        }
    }

    async function uploadSignatureBlob(blob, filename) {
        const fd = new FormData();
        fd.append('signature', blob, filename);
        const r = await fetch('/api/licenses/settings/signature', {
            method: 'POST',
            credentials: 'same-origin',
            body: fd,
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || 'Erreur lors de l\'envoi.');
        _settings = d;
        renderSignaturePreview();
    }

    window.uploadDirecteurSignature = async function (input) {
        const file = input.files[0];
        if (!file) return;
        try {
            await uploadSignatureBlob(file, file.name);
        } catch (e) {
            alert(e.message);
        } finally {
            input.value = '';
        }
    };

    /* ── Signature pad (draw on screen) ── */
    let sigPadCtx = null;
    let sigPadDrawing = false;
    let sigPadHasStrokes = false;

    function sigPadPos(e, canvas) {
        const rect = canvas.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function setupSignaturePad() {
        const canvas = document.getElementById('signature-pad-canvas');
        if (!canvas || canvas._sigPadBound) return;
        canvas._sigPadBound = true;
        canvas.addEventListener('pointerdown', (e) => {
            sigPadDrawing = true;
            sigPadHasStrokes = true;
            const { x, y } = sigPadPos(e, canvas);
            sigPadCtx.beginPath();
            sigPadCtx.moveTo(x, y);
        });
        canvas.addEventListener('pointermove', (e) => {
            if (!sigPadDrawing) return;
            const { x, y } = sigPadPos(e, canvas);
            sigPadCtx.lineTo(x, y);
            sigPadCtx.stroke();
        });
        const stop = () => { sigPadDrawing = false; };
        canvas.addEventListener('pointerup', stop);
        canvas.addEventListener('pointerleave', stop);
        canvas.addEventListener('pointercancel', stop);
    }

    window.openSignaturePad = function () {
        const canvas = document.getElementById('signature-pad-canvas');
        setupSignaturePad();
        const modalEl = document.getElementById('signaturePadModal');
        modalEl.addEventListener('shown.bs.modal', function onShown() {
            modalEl.removeEventListener('shown.bs.modal', onShown);
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width;
            canvas.height = rect.height;
            sigPadCtx = canvas.getContext('2d');
            sigPadCtx.strokeStyle = '#14306e';
            sigPadCtx.lineWidth = 4;
            sigPadCtx.lineCap = 'round';
            sigPadCtx.lineJoin = 'round';
            sigPadHasStrokes = false;
        });
        new bootstrap.Modal(modalEl).show();
    };

    window.clearSignaturePad = function () {
        const canvas = document.getElementById('signature-pad-canvas');
        if (sigPadCtx) sigPadCtx.clearRect(0, 0, canvas.width, canvas.height);
        sigPadHasStrokes = false;
    };

    window.saveSignaturePad = function () {
        if (!sigPadHasStrokes) {
            alert('Veuillez dessiner une signature avant d\'enregistrer.');
            return;
        }
        const canvas = document.getElementById('signature-pad-canvas');
        const btn = document.getElementById('signature-pad-save-btn');
        btn.disabled = true;
        canvas.toBlob(async (blob) => {
            try {
                await uploadSignatureBlob(blob, 'signature.png');
                bootstrap.Modal.getInstance(document.getElementById('signaturePadModal'))?.hide();
            } catch (e) {
                alert(e.message);
            } finally {
                btn.disabled = false;
            }
        }, 'image/png');
    };

    window.removeDirecteurSignature = async function () {
        if (!confirm('Retirer la signature actuelle ?')) return;
        try {
            const r = await fetch('/api/licenses/settings/signature', { method: 'DELETE', credentials: 'same-origin' });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.error || 'Erreur');
            _settings = d;
            renderSignaturePreview();
        } catch (e) {
            alert(e.message);
        }
    };

    const ALL_CATS = ['A', 'A1', 'A2', 'B', 'C', 'D', 'E', 'F', 'P'];

    function populateCategoryValidityForm() {
        const cfg = _settings.category_validity || {};
        ALL_CATS.forEach(cat => {
            const entry = cfg[cat] || { mode: 'card' };
            const modeSel = document.getElementById(`catval-mode-${cat}`);
            const yearsInput = document.getElementById(`catval-years-${cat}`);
            if (modeSel) modeSel.value = entry.mode === 'custom' ? 'custom' : 'card';
            if (yearsInput) yearsInput.value = entry.years || 5;
            onCatValidityModeChange(cat);
        });
    }

    window.onCatValidityModeChange = function (cat) {
        const modeSel = document.getElementById(`catval-mode-${cat}`);
        const wrap    = document.getElementById(`catval-years-wrap-${cat}`);
        if (wrap) wrap.style.display = (modeSel && modeSel.value === 'custom') ? '' : 'none';
    };

    function getCategoryValidityConfig() {
        const cfg = {};
        ALL_CATS.forEach(cat => {
            const mode = document.getElementById(`catval-mode-${cat}`)?.value || 'card';
            if (mode === 'custom') {
                cfg[cat] = { mode: 'custom', years: parseInt(document.getElementById(`catval-years-${cat}`)?.value) || 5 };
            } else {
                cfg[cat] = { mode: 'card' };
            }
        });
        return cfg;
    }

    /* Auto-compute a category's expiration date from the validity settings. */
    window.autoFillCategoryExpiration = function (cat) {
        const expInput = document.getElementById(`cat-expiration-${cat}`);
        if (!expInput) return;
        const cfg = (_settings.category_validity || {})[cat] || { mode: 'card' };
        if (cfg.mode === 'custom' && cfg.years) {
            const baseStr = document.getElementById(`cat-date-${cat}`)?.value || document.getElementById('f-issue_date')?.value;
            if (baseStr) {
                const d = new Date(baseStr);
                d.setFullYear(d.getFullYear() + Number(cfg.years));
                expInput.value = d.toISOString().slice(0, 10);
            }
        } else {
            expInput.value = document.getElementById('f-expiry_date')?.value || '';
        }
    };

    window.openSettingsModal = function () {
        document.getElementById('s-initial_points').value = _settings.initial_points;
        document.getElementById('s-temp_months').value    = _settings.temp_validity_months;
        document.getElementById('s-permanent_years').value = _settings.permanent_validity_years;
        document.getElementById('s-directeur_general_name').value = _settings.directeur_general_name || '';
        renderSignaturePreview();
        populateCategoryValidityForm();

        // Reset to "Général" tab and show save button
        const generalTab = document.getElementById('tab-general-btn');
        if (generalTab) bootstrap.Tab.getOrCreateInstance(generalTab).show();
        document.getElementById('settings-save-btn')?.classList.remove('d-none');

        // Toggle save button visibility based on active tab (it doesn't apply to
        // "Motifs de réduction", which has its own inline add/edit controls)
        const tabBtns = document.querySelectorAll('#settings-tabs .nav-link');
        tabBtns.forEach(btn => {
            btn.addEventListener('shown.bs.tab', () => {
                document.getElementById('settings-save-btn')?.classList.toggle('d-none', btn.id === 'tab-reasons-btn');
            });
        });

        loadStatusRules();
        new bootstrap.Modal(document.getElementById('settingsModal')).show();
    };

    function resetReasonForm() {
        document.getElementById('s-reason-label').value      = '';
        document.getElementById('s-reason-pts').value        = '1';
        document.getElementById('s-reason-editing-id').value = '';
        const artSel = document.getElementById('s-reason-article');
        if (artSel) artSel.value = '';
        const submitBtn = document.getElementById('s-reason-submit-btn');
        if (submitBtn) { submitBtn.innerHTML = '<i class="fas fa-plus me-1"></i>Ajouter'; submitBtn.className = 'btn btn-outline-primary'; }
        document.getElementById('s-reason-cancel-btn')?.classList.add('d-none');
    }

    window.addReason = async function () {
        const label      = document.getElementById('s-reason-label').value.trim();
        const pts        = parseInt(document.getElementById('s-reason-pts').value) || 1;
        const article_id = document.getElementById('s-reason-article')?.value || null;
        const editingId  = document.getElementById('s-reason-editing-id').value;
        if (!label) { alert('Libellé obligatoire.'); return; }

        const isEdit = !!editingId;
        const url    = isEdit ? `/api/licenses/point-reasons/${editingId}` : '/api/licenses/point-reasons';
        const method = isEdit ? 'PUT' : 'POST';

        const r = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ label, points_to_deduct: pts, article_id: article_id || null }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.error || 'Erreur'); return; }
        resetReasonForm();
        loadReasons();
    };

    window.editReason = function (el) {
        const id         = el.dataset.id;
        const label      = el.dataset.label;
        const pts        = el.dataset.pts;
        const article_id = el.dataset.article || '';
        document.getElementById('s-reason-label').value      = label;
        document.getElementById('s-reason-pts').value        = pts;
        document.getElementById('s-reason-editing-id').value = id;
        const artSel = document.getElementById('s-reason-article');
        if (artSel) artSel.value = article_id;
        const submitBtn = document.getElementById('s-reason-submit-btn');
        if (submitBtn) { submitBtn.innerHTML = '<i class="fas fa-save me-1"></i>Modifier'; submitBtn.className = 'btn btn-warning'; }
        document.getElementById('s-reason-cancel-btn')?.classList.remove('d-none');
        document.getElementById('s-reason-label').focus();
    };

    window.cancelEditReason = function () { resetReasonForm(); };

    window.deleteReason = async function (id) {
        if (!confirm('Supprimer ce motif ?')) return;
        await fetch(`/api/licenses/point-reasons/${id}`, { method: 'DELETE', credentials: 'same-origin' });
        resetReasonForm();
        loadReasons();
    };

    window.saveSettings = async function () {
        const btn = document.getElementById('settings-save-btn');
        btn.disabled = true;
        try {
            const r = await fetch('/api/licenses/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    initial_points:       parseInt(document.getElementById('s-initial_points').value) || 12,
                    temp_validity_months: parseInt(document.getElementById('s-temp_months').value)    || 12,
                    permanent_validity_years: parseInt(document.getElementById('s-permanent_years').value) || 10,
                    directeur_general_name: document.getElementById('s-directeur_general_name').value.trim(),
                    category_validity: getCategoryValidityConfig(),
                }),
            });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.error || 'Erreur');
            _settings = d;
            loadLicenses(false);
            loadStats();
            bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
        } catch (e) {
            alert(e.message);
        } finally {
            btn.disabled = false;
        }
    };

    /* ── Reset points ── */
    window.resetPoints = async function (licId, licNum) {
        if (!confirm(`Réinitialiser les points du permis « ${licNum} » et passer le statut en Actif ?`)) return;
        const r = await fetch(`/api/licenses/${licId}/reset-points`, { method: 'POST', credentials: 'same-origin' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.error || 'Erreur'); return; }
        loadLicenses(false);
        loadStats();
    };

    window.renewLicensePoints = async function (licId) {
        if (!confirm('Renouveler les points de ce permis et repasser le statut en Actif ?')) return;
        const r = await fetch(`/api/licenses/${licId}/reset-points`, { method: 'POST', credentials: 'same-origin' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.error || 'Erreur'); return; }
        loadLicenses(false);
        loadStats();
        viewLicense(licId);
    };

    /* ── Réduction points ── */
    window.openReductionModal = function (licId, licNum, currentPoints) {
        if (!_reasons.length) {
            alert('Aucun motif de réduction défini. Ajoutez-en dans les Paramètres.');
            return;
        }
        document.getElementById('reduction-license-id').value = licId;
        document.getElementById('reduction-info').textContent =
            `Permis ${licNum} — Points actuels : ${currentPoints}/${_settings.initial_points || 12}`;
        const sel = document.getElementById('reduction-reason-select');
        sel.innerHTML = _reasons.map(r =>
            `<option value="${r.id}" data-pts="${r.points_to_deduct}">${esc(r.label)} (−${r.points_to_deduct} pt${r.points_to_deduct > 1 ? 's' : ''})</option>`
        ).join('');
        updateReductionPreview(currentPoints);
        new bootstrap.Modal(document.getElementById('reductionModal')).show();
    };

    window.updateReductionPreview = function (currentPts) {
        const sel = document.getElementById('reduction-reason-select');
        const opt = sel.selectedOptions[0];
        if (!opt) return;
        const pts     = parseInt(opt.dataset.pts) || 0;
        const licId   = document.getElementById('reduction-license-id').value;
        const infoTxt = document.getElementById('reduction-info').textContent;
        const match   = infoTxt.match(/Points actuels\s*:\s*(\d+)/);
        const cur     = currentPts !== undefined ? currentPts : (match ? parseInt(match[1]) : 0);
        const after   = Math.max(0, cur - pts);
        const max     = _settings.initial_points || 12;
        document.getElementById('reduction-preview').innerHTML =
            `Après réduction : <strong>${after}/${max}</strong>`;
    };

    window.applyReduction = async function () {
        const licId    = document.getElementById('reduction-license-id').value;
        const sel      = document.getElementById('reduction-reason-select');
        const reasonId = sel.value;
        if (!reasonId) return;
        const btn = document.getElementById('reduction-confirm-btn');
        btn.disabled = true;
        try {
            const r = await fetch(`/api/licenses/${licId}/reduce-points`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ reason_id: parseInt(reasonId) }),
            });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.error || 'Erreur');
            bootstrap.Modal.getInstance(document.getElementById('reductionModal'))?.hide();
            loadLicenses(false);
            loadStats();
        } catch (e) {
            alert(e.message);
        } finally {
            btn.disabled = false;
        }
    };

    /* ── Type permis toggle ── */
    function autoFillExpiry() {
        const isTemp  = document.getElementById('f-type_permis').value === 'temporaire';
        const issueEl = document.getElementById('f-issue_date');
        const expEl   = document.getElementById('f-expiry_date');
        if (!issueEl.value || !expEl) return;
        const d = new Date(issueEl.value);
        if (isTemp) {
            d.setMonth(d.getMonth() + (_settings.temp_validity_months || 12));
        } else {
            d.setFullYear(d.getFullYear() + (_settings.permanent_validity_years || 10));
        }
        expEl.value = d.toISOString().slice(0, 10);
    }

    window.onTypePermisChange = function () {
        const isTemp = document.getElementById('f-type_permis').value === 'temporaire';
        const wrap   = document.getElementById('expiry-date-wrap');
        const lbl    = document.getElementById('issue-date-label');
        const expLbl = document.getElementById('expiry-date-label');
        if (wrap) wrap.style.display = '';
        if (lbl)  lbl.textContent    = isTemp ? 'Depuis le' : 'Date de début';
        if (expLbl) expLbl.textContent = isTemp ? 'Jusqu\'au' : 'Date de validité';
        autoFillExpiry();
    };

    document.getElementById('f-issue_date')?.addEventListener('change', autoFillExpiry);

    /* ── Open Add ── */
    window.openAddModal = function () {
        clearForm();
        document.getElementById('modal-title').innerHTML = '<i class="fas fa-plus me-2"></i>Ajouter un permis';
        document.getElementById('save-btn').innerHTML    = '<i class="fas fa-save me-1"></i>Enregistrer';
        document.getElementById('points-wrap').style.display = 'none';
        new bootstrap.Modal(document.getElementById('licenseModal')).show();
    };

    /* ── Open Edit ── */
    window.editLicense = function (id) {
        fetch(`/api/licenses/${id}`, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(l => {
                clearForm();
                populateForm(l);
                document.getElementById('modal-title').innerHTML = '<i class="fas fa-edit me-2"></i>Modifier le permis';
                document.getElementById('save-btn').innerHTML    = '<i class="fas fa-save me-1"></i>Enregistrer les modifications';
                new bootstrap.Modal(document.getElementById('licenseModal')).show();
            })
            .catch(() => alert('Impossible de charger le permis.'));
    };

    /* ── Save (Create / Update) ── */
    window.saveLicense = async function () {
        const id     = document.getElementById('f-id').value;
        const isEdit = !!id;
        const payload = {
            license_number: document.getElementById('f-license_number').value.trim().toUpperCase(),
            holder_name:       document.getElementById('f-holder_name').value.trim(),
            holder_firstname:  document.getElementById('f-holder_firstname').value.trim(),
            holder_phone:   document.getElementById('f-holder_phone').value.trim(),
            holder_island:  document.getElementById('f-holder_island').value,
            holder_address: document.getElementById('f-holder_address').value.trim(),
            nationalite:           document.getElementById('f-nationalite').value.trim(),
            sexe:                  document.getElementById('f-sexe').value,
            lieu_naissance:        document.getElementById('f-lieu_naissance').value.trim(),
            centre_immatriculation:document.getElementById('f-centre_immatriculation').value.trim(),
            type_permis:           document.getElementById('f-type_permis').value,
            date_of_birth:         document.getElementById('f-date_of_birth').value,
            issue_date:     document.getElementById('f-issue_date').value,
            expiry_date:    document.getElementById('f-expiry_date').value,
            categories:     getCategories(),
            category_details: getCategoryDetails(),
            status:         document.getElementById('f-status').value,
            notes:          document.getElementById('f-notes').value.trim(),
        };

        if (!payload.license_number || !payload.holder_name) {
            alert('Numéro de permis et nom de famille obligatoires.');
            return;
        }

        const btn = document.getElementById('save-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Enregistrement…';

        try {
            const url    = isEdit ? `/api/licenses/${id}` : '/api/licenses';
            const method = isEdit ? 'PUT' : 'POST';
            const r      = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(data.error || 'Erreur');

            const licId = data.id || id;
            const photoFile = document.getElementById('f-photo').files[0];
            if (photoFile && licId) {
                const fd = new FormData();
                fd.append('photo', photoFile);
                await fetch(`/api/licenses/${licId}/photo`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    body: fd,
                });
            }

            bootstrap.Modal.getInstance(document.getElementById('licenseModal'))?.hide();
            loadLicenses(false);
            loadStats();
        } catch (err) {
            alert(err.message || 'Erreur lors de l\'enregistrement.');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-save me-1"></i>Enregistrer';
        }
    };

    /* ── View ── */
    let _currentLicense = null;

    window.printLicenseDetails = function () {
        if (!_currentLicense) return;
        const onHistory = document.getElementById('view-tab-history')?.classList.contains('active');
        if (onHistory) {
            window.open(`/licenses/${_currentLicense.id}/print-history?temporaire=1`, '_blank');
        } else {
            window.open(`/licenses/${_currentLicense.id}/print-folded`, '_blank');
        }
    };

    window.printLicenseCard = function () {
        if (!_currentLicense) return;
        window.open(`/licenses/${_currentLicense.id}/print-card`, '_blank');
    };

    window.renewLicense = function () {
        if (!_currentLicense) return;
        const months = _settings.temp_validity_months || 12;
        const today = new Date();
        const toISO = d => d.toISOString().slice(0, 10);
        const expiry = new Date(today);
        expiry.setMonth(expiry.getMonth() + months);
        const issueStr  = toISO(today);
        const expiryStr = toISO(expiry);
        const fmtFR = s => { const [y,m,d] = s.split('-'); return `${d}/${m}/${y}`; };
        if (!confirm(`Renouveler ce permis temporaire ?\n\nDepuis le : ${fmtFR(issueStr)}\nJusqu'au   : ${fmtFR(expiryStr)}`)) return;
        const btn = document.getElementById('btn-renouveler');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>En cours…'; }
        fetch(`/api/licenses/${_currentLicense.id}`, {
            method: 'PUT',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ issue_date: issueStr, expiry_date: expiryStr, status: 'actif' })
        })
        .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.error || 'Erreur')))
        .then(() => {
            bootstrap.Modal.getInstance(document.getElementById('viewModal'))?.hide();
            loadLicenses();
        })
        .catch(err => {
            alert('Erreur : ' + err);
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-sync-alt me-1"></i>Renouveler'; }
        });
    };

    function syncPrintButton(licId, isPermanent) {
        const btn   = document.getElementById('btn-demander-impression');
        const badge = document.getElementById('badge-carte-imprimee');
        if (!btn) return;
        if (!isPermanent) {
            btn.style.display = 'none';
            if (badge) badge.style.display = 'none';
            return;
        }
        btn.style.display = '';
        fetch(`/api/licenses/${licId}/print-requests`, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : [])
            .then(requests => {
                const hasPending     = requests.some(r => r.status === 'pending');
                const latestPrinted  = !hasPending && requests.length > 0 && requests[0].status === 'printed';
                if (badge) badge.style.display = latestPrinted ? '' : 'none';
                if (hasPending) {
                    btn.disabled  = true;
                    btn.className = 'btn btn-outline-success';
                    btn.innerHTML = '<i class="fas fa-check me-1"></i>Demande envoyée';
                } else {
                    btn.disabled  = false;
                    btn.className = 'btn btn-outline-warning';
                    btn.innerHTML = '<i class="fas fa-paper-plane me-1"></i>Demander impression';
                }
            })
            .catch(() => {
                if (badge) badge.style.display = 'none';
                btn.disabled  = false;
                btn.className = 'btn btn-outline-warning';
                btn.innerHTML = '<i class="fas fa-paper-plane me-1"></i>Demander impression';
            });
    }

    window.demanderImpression = function () {
        if (!_currentLicense) return;
        const btn = document.getElementById('btn-demander-impression');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Envoi…';
        fetch(`/api/licenses/${_currentLicense.id}/print-request`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({}),
        })
        .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
        .then(({ ok, data }) => {
            if (ok) {
                syncPrintButton(_currentLicense.id, _currentLicense.type_permis === 'permanent');
                loadLicenses(false);
            } else {
                alert(data.error || 'Erreur lors de la demande.');
                syncPrintButton(_currentLicense.id, _currentLicense.type_permis === 'permanent');
            }
        })
        .catch(() => {
            alert('Erreur réseau.');
            syncPrintButton(_currentLicense.id, _currentLicense.type_permis === 'permanent');
        });
    };

    window.viewLicense = function (id) {
        // Reset to details tab and wire up history tab
        const detailsTab = document.querySelector('[data-bs-target="#view-tab-details"]');
        if (detailsTab) bootstrap.Tab.getOrCreateInstance(detailsTab).show();

        document.getElementById('view-tab-history-btn')?.addEventListener('shown.bs.tab', function onHistoryShown() {
            loadPointHistory(id);
            this.removeEventListener('shown.bs.tab', onHistoryShown);
        });

        fetch(`/api/licenses/${id}`, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(l => {
                _currentLicense = l;
                const btnCarte = document.getElementById('btn-carte-digitale');
                if (btnCarte) btnCarte.style.display = 'none';
                syncPrintButton(l.id, l.type_permis === 'permanent' && !l.is_expired);
                const btnImprimer = document.getElementById('btn-imprimer');
                if (btnImprimer) btnImprimer.style.display = l.is_expired ? 'none' : '';
                const btnRenouveler = document.getElementById('btn-renouveler');
                if (btnRenouveler) btnRenouveler.style.display = l.is_expired ? '' : 'none';
                const catList = l.categories ? l.categories.split(',').map(c => c.trim()).filter(Boolean) : [];
                const catDetailsMap = l.category_details || {};
                const cats = catList.length
                    ? catList.map(c => `<span class="badge bg-info text-dark me-1">${esc(c)}</span>`).join('')
                    : '—';
                const catDetailRows = catList
                    .filter(c => catDetailsMap[c] && (catDetailsMap[c].identifiant || catDetailsMap[c].date || catDetailsMap[c].expiration))
                    .map(c => `
                        <tr>
                            <td><span class="badge bg-info text-dark">${esc(c)}</span></td>
                            <td>${esc(catDetailsMap[c].identifiant || '—')}</td>
                            <td>${fmtDate(catDetailsMap[c].date)}</td>
                            <td>${fmtDate(catDetailsMap[c].expiration)}</td>
                        </tr>`).join('');
                const statusCls   = { actif: 'success', suspendu: 'warning', revoque: 'danger', expire: 'secondary' }[l.status] || 'secondary';
                const statusLabel = { actif: 'Actif', suspendu: 'Suspendu', revoque: 'Révoqué', expire: 'Expiré' }[l.is_expired ? 'expire' : l.status] || l.status;
                document.getElementById('view-body').innerHTML = `
                    <div class="row g-3 align-items-center">
                        <div class="col-auto">
                            ${l.photo_filename
                                ? `<img src="/uploads/license_photos/${esc(l.photo_filename)}" style="width:100px;height:120px;object-fit:cover;border-radius:8px;border:1px solid #dee2e6;" alt="">`
                                : `<div style="width:100px;height:120px;background:#f0f0f0;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:3rem;"><i class="fas fa-user-circle"></i></div>`
                            }
                        </div>
                        <div class="col">
                            <h5 class="mb-1">${esc(l.holder_firstname ? l.holder_firstname + ' ' + l.holder_name : l.holder_name)}</h5>
                            <div class="mb-2"><code class="fs-6">${esc(l.license_number)}</code> &nbsp; <span class="badge bg-${statusCls}">${statusLabel}</span></div>
                            <div class="text-muted small">${esc(l.holder_island || '—')} ${l.holder_phone ? '· ' + esc(l.holder_phone) : ''}</div>
                        </div>
                        <div class="col-auto">
                            <img src="/licenses/${l.id}/qrcode" alt="QR Code" style="width:120px;height:120px;border:1px solid #dee2e6;border-radius:6px;padding:4px;">
                        </div>
                    </div>
                    <hr>
                    <div class="row g-3 small">
                        <div class="col-md-4"><div class="text-muted mb-1">Date de naissance</div><strong>${fmtDate(l.date_of_birth)}</strong></div>
                        <div class="col-md-4"><div class="text-muted mb-1">Lieu de naissance</div><strong>${esc(l.lieu_naissance || '—')}</strong></div>
                        <div class="col-md-4"><div class="text-muted mb-1">Sexe</div><strong>${l.sexe === 'masculin' ? 'Masculin' : l.sexe === 'feminin' ? 'Féminin' : '—'}</strong></div>
                        <div class="col-md-4"><div class="text-muted mb-1">Nationalité</div><strong>${esc(l.nationalite || '—')}</strong></div>
                        <div class="col-md-4">
                            <div class="text-muted mb-1">Points</div>
                            <div class="d-flex align-items-center gap-2 flex-wrap">
                                ${pointsBadge(l.points)}
                                ${l.status === 'suspendu' && window.CURRENT_USER_ROLE === 'administrateur'
                                    ? `<button class="btn btn-sm btn-outline-success" onclick="renewLicensePoints(${l.id})"><i class="fas fa-redo me-1"></i>Renouveler les points</button>`
                                    : ''}
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="text-muted mb-1">Type de permis</div>
                            ${l.type_permis === 'temporaire'
                                ? '<span class="badge bg-warning text-dark"><i class="fas fa-clock me-1"></i>Temporaire</span>'
                                : '<span class="badge bg-success"><i class="fas fa-infinity me-1"></i>Permanent</span>'}
                        </div>
                        <div class="col-md-4"><div class="text-muted mb-1">${l.type_permis === 'temporaire' ? 'Depuis le' : 'Date de début'}</div><strong>${fmtDate(l.issue_date)}</strong></div>
                        ${l.type_permis === 'temporaire' ? `<div class="col-md-4"><div class="text-muted mb-1">Jusqu'au</div><strong>${fmtDate(l.expiry_date)}</strong></div>` : ''}
                        <div class="col-md-4"><div class="text-muted mb-1">Centre d'immatriculation</div><strong>${esc(l.centre_immatriculation || '—')}</strong></div>
                        <div class="col-md-4"><div class="text-muted mb-1">Adresse</div><span>${esc(l.holder_address || '—')}</span></div>
                        <div class="col-md-6"><div class="text-muted mb-1">Catégories</div><div class="mt-1">${cats || '—'}</div></div>
                        ${catDetailRows ? `
                        <div class="col-12">
                            <div class="text-muted mb-1">Détails par catégorie</div>
                            <table class="table table-sm mb-0">
                                <thead><tr><th>Catégorie</th><th>N° d'identifiant</th><th>Date d'obtention</th><th>Date d'expiration</th></tr></thead>
                                <tbody>${catDetailRows}</tbody>
                            </table>
                        </div>` : ''}
                        ${l.notes ? `<div class="col-12"><div class="text-muted mb-1">Notes</div><span>${esc(l.notes)}</span></div>` : ''}
                    </div>
                    <hr>
                    <div class="text-muted small">Créé par <strong>${esc(l.created_by || '—')}</strong> · ${l.created_at}</div>
                `;
                new bootstrap.Modal(document.getElementById('viewModal')).show();
            })
            .catch(() => alert('Impossible de charger le permis.'));
    };

    /* ── Point history ── */
    function loadPointHistory(licId) {
        const tbody = document.getElementById('view-history-tbody');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Chargement…</td></tr>';
        fetch(`/api/licenses/${licId}/point-history`, { credentials: 'same-origin' })
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(rows => {
                if (!rows.length) {
                    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Aucun retrait de points enregistré.</td></tr>';
                    return;
                }
                const max = _settings.initial_points || 12;
                const ptsCls = n => n >= max * 0.75 ? 'bg-success' : n >= max * 0.4 ? 'bg-warning text-dark' : 'bg-danger';
                tbody.innerHTML = rows.map(r => {
                    const isReset = r.points_after > r.points_before;
                    const deductCell = isReset
                        ? `<span class="badge bg-success">↺ Réinitialisation</span>`
                        : `<span class="badge bg-danger">−${r.points_deducted}</span>`;
                    const canReclaim = r.reclaimable && window.CURRENT_USER_ROLE === 'administrateur';
                    const actionCell = canReclaim
                        ? `<button class="btn btn-sm btn-outline-warning" title="Réclamation" onclick="openReclamationModal(${r.id}, ${licId}, '${esc(r.reason_label)}', ${r.points_deducted}, '${esc(r.created_at)}')"><i class="fas fa-gavel"></i></button>`
                        : '<span class="text-muted">—</span>';
                    return `
                    <tr>
                        <td class="text-muted small">${r.created_at}</td>
                        <td>${esc(r.reason_label)}</td>
                        <td><span class="badge ${ptsCls(r.points_before)}">${r.points_before}/${max}</span></td>
                        <td>${deductCell}</td>
                        <td><span class="badge ${ptsCls(r.points_after)}">${r.points_after}/${max}</span></td>
                        <td class="text-muted small">${esc(r.created_by || '—')}</td>
                        <td>${actionCell}</td>
                    </tr>`;
                }).join('');
            })
            .catch(() => {
                if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">Erreur de chargement.</td></tr>';
            });
    }

    /* ── Réclamation ── */
    window.openReclamationModal = function (historyId, licId, reasonLabel, pointsDeducted, createdAt) {
        document.getElementById('reclamation-history-id').value = historyId;
        document.getElementById('reclamation-license-id').value = licId;
        document.getElementById('reclamation-info').textContent =
            `Infraction « ${reasonLabel} » (−${pointsDeducted} pts) du ${createdAt}.`;
        document.getElementById('reclamation-action-change').checked = true;
        const sel = document.getElementById('reclamation-reason-select');
        sel.innerHTML = _reasons.map(r => `<option value="${r.id}">${esc(r.label)} (−${r.points_to_deduct} pts)</option>`).join('');
        onReclamationActionChange();
        new bootstrap.Modal(document.getElementById('reclamationModal')).show();
    };

    window.onReclamationActionChange = function () {
        const isCancel = document.getElementById('reclamation-action-cancel').checked;
        document.getElementById('reclamation-reason-wrap').style.display = isCancel ? 'none' : '';
        document.getElementById('reclamation-cancel-note').style.display = isCancel ? '' : 'none';
    };

    window.submitReclamation = async function () {
        const historyId = document.getElementById('reclamation-history-id').value;
        const licId     = document.getElementById('reclamation-license-id').value;
        const action    = document.querySelector('input[name="reclamation-action"]:checked').value;
        const body = { action };
        if (action === 'change_reason') {
            const reasonId = document.getElementById('reclamation-reason-select').value;
            if (!reasonId) { alert('Sélectionnez un motif.'); return; }
            body.reason_id = reasonId;
        } else if (!confirm('Confirmer l\'annulation de ce retrait de points ? Cette action est irréversible.')) {
            return;
        }
        const btn = document.getElementById('reclamation-confirm-btn');
        btn.disabled = true;
        try {
            const r = await fetch(`/api/licenses/point-history/${historyId}/reclamation`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) { alert(d.error || 'Erreur'); return; }
            bootstrap.Modal.getInstance(document.getElementById('reclamationModal'))?.hide();
            loadPointHistory(licId);
            loadLicenses(false);
            loadStats();
        } catch (e) {
            alert('Erreur réseau.');
        } finally {
            btn.disabled = false;
        }
    };

    /* ── Delete ── */
    window.deleteLicense = function (id, num) {
        if (!confirm(`Supprimer le permis « ${num} » ? Cette action est irréversible.`)) return;
        fetch(`/api/licenses/${id}`, { method: 'DELETE', credentials: 'same-origin' })
            .then(r => r.ok ? (loadLicenses(false), loadStats()) : r.json().then(d => alert(d.error || 'Erreur')))
            .catch(() => alert('Erreur réseau.'));
    };

    /* ── Stats ── */
    function loadStats() {
        fetch('/api/licenses/stats', { credentials: 'same-origin' })
            .then(r => {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(d => {
                const set = (id, val) => {
                    const el = document.getElementById(id);
                    if (el) el.textContent = val ?? '—';
                };
                set('stat-total',      d.total);
                set('stat-actif',      d.actif);
                set('stat-suspendu',   d.suspendu);
                set('stat-revoque',    d.revoque);
                set('stat-temporaire', d.temporaire);
                set('stat-permanent',  d.permanent);
            })
            .catch(e => console.error('[licenses] stats error:', e));
    }

    /* ── Init ── */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => { loadSettings(); loadReasons(); loadLicenses(true); loadStats(); });
    } else {
        loadSettings(); loadReasons(); loadLicenses(true); loadStats();
    }
})();
