// ── Amendes permis de conduire (onglet "Permis de conduire" de Gestion des Amendes) ──

document.addEventListener('DOMContentLoaded', function () {
    window.licenseFinesCurrentPage = 1;
    window.licenseFinesCurrentItems = [];
    window.LICENSE_FINES_PER_PAGE = 20;

    const permisTabBtn = document.getElementById('tab-fines-permis-btn');
    if (permisTabBtn) {
        let loadedOnce = false;
        permisTabBtn.addEventListener('shown.bs.tab', function () {
            if (!loadedOnce) {
                loadedOnce = true;
                loadLicenseFines();
            }
        });
    }

    // search (debounced)
    const searchEl = document.getElementById('license-fines-search');
    const clearBtn = document.getElementById('clear-license-fines-search');
    if (searchEl) {
        let debounceTimer;
        searchEl.addEventListener('input', function () {
            if (clearBtn) clearBtn.style.display = this.value ? 'inline-block' : 'none';
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                const filter = document.querySelector('#license-fines-filter-group .active');
                const fval = filter ? filter.dataset.filter : 'all';
                loadLicenseFinesWithParams(this.value.trim(), fval === 'paid' ? true : fval === 'unpaid' ? false : null);
            }, 250);
        });
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            if (searchEl) { searchEl.value = ''; searchEl.focus(); }
            this.style.display = 'none';
            const filter = document.querySelector('#license-fines-filter-group .active');
            const fval = filter ? filter.dataset.filter : 'all';
            loadLicenseFinesWithParams('', fval === 'paid' ? true : fval === 'unpaid' ? false : null);
        });
    }

    // filter buttons (Tous / Payées / Impayées)
    const filterGroup = document.getElementById('license-fines-filter-group');
    if (filterGroup) {
        filterGroup.addEventListener('click', function (e) {
            const btn = e.target.closest('button[data-filter]');
            if (!btn) return;
            filterGroup.querySelectorAll('button[data-filter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const q = (document.getElementById('license-fines-search') || { value: '' }).value.trim();
            const f = btn.dataset.filter;
            loadLicenseFinesWithParams(q, f === 'paid' ? true : f === 'unpaid' ? false : null);
        });
    }

    // ── Paramètres Amendes Permis modal ──
    const settingsModal = document.getElementById('license-fine-settings-modal');
    if (settingsModal) {
        settingsModal.addEventListener('show.bs.modal', function () {
            try {
                resetLfArticleForm();
                resetLfReasonForm();
                resetLfCategoryForm();
                loadLfArticles().then(() => Promise.all([loadLfCategories(), loadLfReasons()]));
            } catch (e) { console.error(e); }
        });
    }
    setupLfReasonIconPicker();

    const articleForm = document.getElementById('lf-article-form');
    if (articleForm) articleForm.addEventListener('submit', submitLfArticleForm);
    const articleCancel = document.getElementById('lf-article-cancel');
    if (articleCancel) articleCancel.addEventListener('click', resetLfArticleForm);

    const reasonForm = document.getElementById('lf-reason-form');
    if (reasonForm) reasonForm.addEventListener('submit', submitLfReasonForm);
    const reasonCancel = document.getElementById('lf-reason-cancel');
    if (reasonCancel) reasonCancel.addEventListener('click', resetLfReasonForm);

    const categoryForm = document.getElementById('lf-category-form');
    if (categoryForm) categoryForm.addEventListener('submit', submitLfCategoryForm);
    const categoryCancel = document.getElementById('lf-category-cancel');
    if (categoryCancel) categoryCancel.addEventListener('click', resetLfCategoryForm);
    const applyNowBtn = document.getElementById('btn-apply-lf-categories');
    if (applyNowBtn) applyNowBtn.addEventListener('click', applyLfCategoriesNow);

    // ── Réclamation ──
    document.getElementById('lf-reclamation-action-change')?.addEventListener('change', lfOnReclamationActionChange);
    document.getElementById('lf-reclamation-action-cancel')?.addEventListener('change', lfOnReclamationActionChange);
    document.getElementById('lf-reclamation-confirm-btn')?.addEventListener('click', lfSubmitReclamation);
});

function loadLicenseFines() {
    loadLicenseFinesWithParams('', null);
}

function loadLicenseFinesWithParams(q, paid) {
    let url = '/api/licenses/fines';
    const parts = [];
    if (q) parts.push('q=' + encodeURIComponent(q));
    if (paid !== null && paid !== undefined) parts.push('paid=' + (paid ? 'true' : 'false'));
    if (parts.length) url += '?' + parts.join('&');

    fetch(url)
        .then(r => r.json())
        .then(data => renderLicenseFinesTable(data))
        .catch(err => {
            console.error('Erreur chargement amendes permis', err);
            document.getElementById('license-fines-tbody').innerHTML = '<tr><td colspan="9" class="text-center text-muted">Erreur chargement</td></tr>';
        });
}

function renderLicenseFinesTable(items) {
    window.licenseFinesCurrentItems = items || [];
    window.licenseFinesCurrentPage = 1;
    displayLicenseFinesPage();
}

function _lfFormatDateTime(dt) {
    if (!dt) return '';
    try {
        const d = new Date(dt);
        if (isNaN(d)) return dt;
        const pad = (n) => String(n).padStart(2, '0');
        return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch (e) { return dt; }
}

function displayLicenseFinesPage() {
    const items = window.licenseFinesCurrentItems || [];
    const tbody = document.getElementById('license-fines-tbody');
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center">Aucune amende</td></tr>';
        _lfUpdatePaginationInfo(0, 0, 0);
        return;
    }

    const totalPages = Math.ceil(items.length / window.LICENSE_FINES_PER_PAGE);
    const startIdx = (window.licenseFinesCurrentPage - 1) * window.LICENSE_FINES_PER_PAGE;
    const endIdx = Math.min(startIdx + window.LICENSE_FINES_PER_PAGE, items.length);
    const itemsOnPage = items.slice(startIdx, endIdx);

    tbody.innerHTML = itemsOnPage.map((f, i) => {
        const holder = [f.holder_firstname, f.holder_name].filter(Boolean).join(' ');
        const amountCell = (f.base_amount && Math.round(f.base_amount) !== Math.round(f.amount))
            ? `<span class="text-decoration-line-through text-muted me-1 small">${Math.round(f.base_amount)} KMF</span><strong class="text-danger">${Math.round(f.amount)} KMF</strong>`
            : `${Math.round(f.amount)} KMF`;
        const canReclaim = window.IS_LICENSE_ADMIN === true && f.reclaimable;
        const reclaimBtn = canReclaim
            ? `<button class="btn btn-sm btn-outline-warning" title="Réclamation" onclick="lfOpenReclamationModal(${f.history_id}, ${f.id}, '${(f.reason_label || '').replace(/'/g, "\\'")}')"><i class="fas fa-gavel"></i></button>`
            : '';
        return `<tr>
            <td>${startIdx + i + 1}</td>
            <td><strong>${f.license_number || f.license_id}</strong></td>
            <td>${holder}</td>
            <td>${amountCell}</td>
            <td>${f.reason_label}</td>
            <td>${f.officer || ''}</td>
            <td>${_lfFormatDateTime(f.issued_at)}</td>
            <td>${f.paid ? '<span class="status-badge-paid">Payée</span>' : '<span class="status-badge-unpaid">Impayée</span>'}</td>
            <td>${reclaimBtn}</td>
        </tr>`;
    }).join('');

    _lfUpdatePaginationInfo(startIdx + 1, endIdx, items.length, window.licenseFinesCurrentPage, totalPages);
    _lfUpdatePaginationButtons(window.licenseFinesCurrentPage, totalPages);
}

function _lfUpdatePaginationInfo(start, end, total, currentPage, totalPages) {
    const startEl = document.getElementById('license-fines-pagination-start');
    const endEl = document.getElementById('license-fines-pagination-end');
    const totalEl = document.getElementById('license-fines-pagination-total');
    const pageInfoEl = document.getElementById('license-fines-page-info');
    if (startEl && endEl && totalEl) {
        startEl.textContent = total === 0 ? 0 : start;
        endEl.textContent = end;
        totalEl.textContent = total;
    }
    if (pageInfoEl && currentPage && totalPages) {
        pageInfoEl.textContent = 'Page ' + currentPage + ' sur ' + totalPages;
    }
}

function _lfUpdatePaginationButtons(currentPage, totalPages) {
    const prevBtn = document.querySelector('#license-fines-pagination-controls li:first-child a');
    const nextBtn = document.querySelector('#license-fines-pagination-controls li:last-child a');
    if (prevBtn) prevBtn.parentElement.classList.toggle('disabled', currentPage <= 1);
    if (nextBtn) nextBtn.parentElement.classList.toggle('disabled', currentPage >= totalPages);
}

function licenseFinesGoToPreviousPage() {
    if (window.licenseFinesCurrentPage > 1) {
        window.licenseFinesCurrentPage--;
        displayLicenseFinesPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function licenseFinesGoToNextPage() {
    const totalPages = Math.ceil((window.licenseFinesCurrentItems || []).length / window.LICENSE_FINES_PER_PAGE);
    if (window.licenseFinesCurrentPage < totalPages) {
        window.licenseFinesCurrentPage++;
        displayLicenseFinesPage();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

// ── Réclamation (annuler/changer le motif d'un retrait de points) ──
function lfOpenReclamationModal(historyId, fineId, reasonLabel) {
    document.getElementById('lf-reclamation-history-id').value = historyId;
    document.getElementById('lf-reclamation-license-id').value = fineId; // kept for symmetry, unused by the API call
    document.getElementById('lf-reclamation-info').textContent = `Infraction « ${reasonLabel} ».`;
    document.getElementById('lf-reclamation-action-change').checked = true;
    fetch('/api/licenses/point-reasons')
        .then(r => r.json())
        .then(reasons => {
            const sel = document.getElementById('lf-reclamation-reason-select');
            sel.innerHTML = reasons.map(r => `<option value="${r.id}">${r.label} (−${r.points_to_deduct} pts)</option>`).join('');
        });
    lfOnReclamationActionChange();
    new bootstrap.Modal(document.getElementById('lf-reclamation-modal')).show();
}

function lfOnReclamationActionChange() {
    const isCancel = document.getElementById('lf-reclamation-action-cancel').checked;
    document.getElementById('lf-reclamation-reason-wrap').style.display = isCancel ? 'none' : '';
    document.getElementById('lf-reclamation-cancel-note').style.display = isCancel ? '' : 'none';
}

function lfSubmitReclamation() {
    const historyId = document.getElementById('lf-reclamation-history-id').value;
    const action = document.querySelector('input[name="lf-reclamation-action"]:checked').value;
    const body = { action };
    if (action === 'change_reason') {
        const reasonId = document.getElementById('lf-reclamation-reason-select').value;
        if (!reasonId) { alert('Sélectionnez un motif.'); return; }
        body.reason_id = reasonId;
    } else if (!confirm("Confirmer l'annulation de ce retrait de points ? Cette action est irréversible.")) {
        return;
    }
    const btn = document.getElementById('lf-reclamation-confirm-btn');
    btn.disabled = true;
    fetch(`/api/licenses/point-history/${historyId}/reclamation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
        .then(r => { if (!r.ok) return r.json().then(x => { throw x; }); return r.json(); })
        .then(() => {
            bootstrap.Modal.getInstance(document.getElementById('lf-reclamation-modal'))?.hide();
            loadLicenseFines();
        })
        .catch(err => alert(err.error || 'Erreur'))
        .finally(() => { btn.disabled = false; });
}

// ── Articles ──
function loadLfArticles() {
    return fetch('/api/licenses/point-articles')
        .then(r => r.json())
        .then(data => {
            window.lfArticlesCache = data;
            const sel = document.getElementById('lf-reason-article');
            if (sel) {
                sel.innerHTML = '<option value="">— aucun —</option>' + data.map(a => `<option value="${a.id}">${a.code}</option>`).join('');
            }
            renderLfArticlesTable(data);
            return data;
        });
}

function renderLfArticlesTable(items) {
    const tbody = document.getElementById('lf-articles-tbody');
    if (!tbody) return;
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center">Aucun article</td></tr>';
        return;
    }
    tbody.innerHTML = items.map(a => `<tr>
        <td><span class="badge bg-secondary">${a.code}</span></td>
        <td>${a.description || '<span class="text-muted">—</span>'}</td>
        <td>
          <button class="btn btn-sm btn-outline-secondary me-1" onclick="editLfArticle(${a.id})">Éditer</button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteLfArticle(${a.id})">Supprimer</button>
        </td>
    </tr>`).join('');
}

function editLfArticle(id) {
    const a = (window.lfArticlesCache || []).find(x => x.id === id);
    if (!a) return;
    document.getElementById('lf-article-id').value = a.id;
    document.getElementById('lf-article-code').value = a.code;
    document.getElementById('lf-article-description').value = a.description || '';
    document.getElementById('lf-article-cancel').classList.remove('d-none');
}

function resetLfArticleForm() {
    const form = document.getElementById('lf-article-form');
    if (form) form.reset();
    document.getElementById('lf-article-id').value = '';
    const cancel = document.getElementById('lf-article-cancel');
    if (cancel) cancel.classList.add('d-none');
}

function submitLfArticleForm(e) {
    e.preventDefault();
    const id = document.getElementById('lf-article-id').value;
    const code = document.getElementById('lf-article-code').value.trim();
    const description = document.getElementById('lf-article-description').value.trim();
    if (!code) return;
    const url = id ? `/api/licenses/point-articles/${id}` : '/api/licenses/point-articles';
    fetch(url, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, description }) })
        .then(r => { if (!r.ok) return r.json().then(x => { throw x; }); return r.json(); })
        .then(() => { resetLfArticleForm(); loadLfArticles(); })
        .catch(err => alert(err.error || 'Erreur'));
}

function deleteLfArticle(id) {
    if (!confirm('Supprimer cet article ?')) return;
    fetch(`/api/licenses/point-articles/${id}`, { method: 'DELETE' })
        .then(r => { if (!r.ok) throw new Error(); return r.json(); })
        .then(() => loadLfArticles())
        .catch(() => alert('Impossible de supprimer'));
}

// ── Motifs de réduction (icônes réutilisées depuis fines_list.js) ──
function setupLfReasonIconPicker() {
    const grid = document.getElementById('lf-reason-icon-grid');
    if (!grid || typeof FINE_TYPE_ICON_GROUPS === 'undefined') return;
    grid.innerHTML = FINE_TYPE_ICON_GROUPS.map(g => `
        <div class="w-100 text-muted" style="font-size:.68rem;text-transform:uppercase;letter-spacing:.04em;margin:${g === FINE_TYPE_ICON_GROUPS[0] ? '0' : '.35rem'} 0 .15rem;">${g.label}</div>
        ${g.icons.map(icon => `<button type="button" class="btn btn-outline-secondary" style="width:2.4rem;height:2.4rem;font-size:1.1rem;padding:0;" data-lf-icon-choice="${icon}">${icon}</button>`).join('')}
    `).join('');
    grid.querySelectorAll('[data-lf-icon-choice]').forEach(btn => {
        btn.addEventListener('click', function () { setLfReasonIcon(this.dataset.lfIconChoice); });
    });
    const noneBtn = document.querySelector('#tab-lf-reasons [data-icon-choice=""]');
    if (noneBtn) noneBtn.addEventListener('click', () => setLfReasonIcon(''));
}

function setLfReasonIcon(icon) {
    const hidden = document.getElementById('lf-reason-icon');
    const preview = document.getElementById('lf-reason-icon-preview');
    if (hidden) hidden.value = icon || '';
    if (preview) preview.textContent = icon || '🏷️';
}

function loadLfReasons() {
    return fetch('/api/licenses/point-reasons')
        .then(r => r.json())
        .then(data => {
            window.lfReasonsCache = data;
            renderLfReasonsTable(data);
            return data;
        });
}

function renderLfReasonsTable(items) {
    const tbody = document.getElementById('lf-reasons-tbody');
    if (!tbody) return;
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center">Aucun motif</td></tr>';
        return;
    }
    tbody.innerHTML = items.map(r => `<tr>
        <td class="text-center" style="font-size:1.1rem;">${r.icon || '<span class="text-muted small">—</span>'}</td>
        <td>${r.label}</td>
        <td>${r.points_to_deduct} pt${r.points_to_deduct > 1 ? 's' : ''}</td>
        <td>${r.article_code ? `<span class="badge bg-secondary">${r.article_code}</span>` : '<span class="text-muted">—</span>'}</td>
        <td>${r.category_name ? `${r.category_name} <span class="text-muted small">(${Math.round(r.category_min_price)}–${Math.round(r.category_max_price)} KMF)</span>` : '<span class="text-muted">—</span>'}</td>
        <td>
          <button class="btn btn-sm btn-outline-secondary me-1" onclick="editLfReason(${r.id})">Éditer</button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteLfReason(${r.id})">Supprimer</button>
        </td>
    </tr>`).join('');
}

function editLfReason(id) {
    const r = (window.lfReasonsCache || []).find(x => x.id === id);
    if (!r) return;
    document.getElementById('lf-reason-id').value = r.id;
    document.getElementById('lf-reason-label').value = r.label;
    document.getElementById('lf-reason-pts').value = r.points_to_deduct;
    document.getElementById('lf-reason-article').value = r.article_id || '';
    document.getElementById('lf-reason-category').value = r.category_id || '';
    setLfReasonIcon(r.icon || '');
    document.getElementById('lf-reason-cancel').classList.remove('d-none');
}

function resetLfReasonForm() {
    const form = document.getElementById('lf-reason-form');
    if (form) form.reset();
    document.getElementById('lf-reason-id').value = '';
    setLfReasonIcon('');
    const cancel = document.getElementById('lf-reason-cancel');
    if (cancel) cancel.classList.add('d-none');
}

function submitLfReasonForm(e) {
    e.preventDefault();
    const id = document.getElementById('lf-reason-id').value;
    const label = document.getElementById('lf-reason-label').value.trim();
    const points_to_deduct = document.getElementById('lf-reason-pts').value;
    const article_id = document.getElementById('lf-reason-article').value || null;
    const category_id = document.getElementById('lf-reason-category').value || null;
    const icon = document.getElementById('lf-reason-icon').value || null;
    if (!label) return;
    const payload = { label, points_to_deduct, article_id, category_id, icon };
    const url = id ? `/api/licenses/point-reasons/${id}` : '/api/licenses/point-reasons';
    fetch(url, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(r => { if (!r.ok) return r.json().then(x => { throw x; }); return r.json(); })
        .then(() => { resetLfReasonForm(); loadLfReasons(); })
        .catch(err => alert(err.error || 'Erreur'));
}

function deleteLfReason(id) {
    if (!confirm('Supprimer ce motif ?')) return;
    fetch(`/api/licenses/point-reasons/${id}`, { method: 'DELETE' })
        .then(r => { if (!r.ok) throw new Error(); return r.json(); })
        .then(() => loadLfReasons())
        .catch(() => alert('Impossible de supprimer'));
}

// ── Classe de contravention ──
function loadLfCategories() {
    return fetch('/api/licenses/point-categories')
        .then(r => r.json())
        .then(data => {
            window.lfCategoriesCache = data;
            const sel = document.getElementById('lf-reason-category');
            if (sel) {
                const current = sel.value;
                sel.innerHTML = '<option value="">— aucune —</option>' + data.map(c => `<option value="${c.id}">${c.name} (${Math.round(c.min_price)}–${Math.round(c.max_price)} KMF)</option>`).join('');
                sel.value = current;
            }
            renderLfCategoriesTable(data);
            return data;
        });
}

function renderLfCategoriesTable(items) {
    const tbody = document.getElementById('lf-categories-tbody');
    if (!tbody) return;
    if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">Aucune classe</td></tr>';
        return;
    }
    tbody.innerHTML = items.map(c => `<tr>
        <td>${c.name}</td>
        <td>${Math.round(c.min_price)} KMF</td>
        <td>${Math.round(c.max_price)} KMF</td>
        <td>${Math.round(c.weekly_increment)} KMF</td>
        <td>
          <button class="btn btn-sm btn-outline-secondary me-1" onclick="editLfCategory(${c.id})">Éditer</button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteLfCategory(${c.id})">Supprimer</button>
        </td>
    </tr>`).join('');
}

function editLfCategory(id) {
    const c = (window.lfCategoriesCache || []).find(x => x.id === id);
    if (!c) return;
    document.getElementById('lf-category-name').dataset.editingId = c.id;
    document.getElementById('lf-category-name').value = c.name;
    document.getElementById('lf-category-min').value = c.min_price;
    document.getElementById('lf-category-max').value = c.max_price;
    document.getElementById('lf-category-increment').value = c.weekly_increment;
    document.getElementById('lf-category-submit-btn').innerHTML = '<i class="fas fa-save me-1"></i>Enregistrer';
    document.getElementById('lf-category-cancel').classList.remove('d-none');
}

function resetLfCategoryForm() {
    const form = document.getElementById('lf-category-form');
    if (form) form.reset();
    delete document.getElementById('lf-category-name').dataset.editingId;
    document.getElementById('lf-category-submit-btn').innerHTML = '<i class="fas fa-plus me-1"></i>Ajouter';
    const cancel = document.getElementById('lf-category-cancel');
    if (cancel) cancel.classList.add('d-none');
}

function submitLfCategoryForm(e) {
    e.preventDefault();
    const id = document.getElementById('lf-category-name').dataset.editingId;
    const payload = {
        name: document.getElementById('lf-category-name').value.trim(),
        min_price: document.getElementById('lf-category-min').value,
        max_price: document.getElementById('lf-category-max').value,
        weekly_increment: document.getElementById('lf-category-increment').value,
    };
    const url = id ? `/api/licenses/point-categories/${id}` : '/api/licenses/point-categories';
    fetch(url, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(r => { if (!r.ok) return r.json().then(x => { throw x; }); return r.json(); })
        .then(() => { resetLfCategoryForm(); loadLfCategories(); })
        .catch(err => alert(err.error || 'Erreur'));
}

function deleteLfCategory(id) {
    if (!confirm('Supprimer cette classe ?')) return;
    fetch(`/api/licenses/point-categories/${id}`, { method: 'DELETE' })
        .then(r => { if (!r.ok) return r.json().then(x => { throw x; }); return r.json(); })
        .then(() => loadLfCategories())
        .catch(err => alert(err.error || 'Impossible de supprimer'));
}

function applyLfCategoriesNow() {
    if (!confirm('Recalculer toutes les amendes de permis impayées maintenant ?')) return;
    fetch('/api/licenses/point-categories/apply-now', { method: 'POST' })
        .then(r => { if (!r.ok) return r.json().then(x => { throw x; }); return r.json(); })
        .then(() => { alert('Majorations appliquées'); loadLicenseFines(); })
        .catch(err => alert(err.error || 'Erreur'));
}
