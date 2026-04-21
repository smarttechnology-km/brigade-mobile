// Photo Submissions Management

let allSubmissions = [];
let currentModal = {};

// Load submissions on page load
document.addEventListener('DOMContentLoaded', () => {
    loadSubmissions();
    
    // Setup event listeners
    document.getElementById('btn-filter').addEventListener('click', filterSubmissions);
    document.getElementById('btn-resolve').addEventListener('click', resolveSubmission);
    document.getElementById('btn-delete').addEventListener('click', deleteSubmission);
    
    // Country filter listener for admin
    const countryFilter = document.getElementById('filter-country');
    if (countryFilter) {
        countryFilter.addEventListener('change', loadSubmissions);
    }
    
    // Auto-load every 10s
    setInterval(loadSubmissions, 10000);
});

async function loadSubmissions() {
    try {
        const countryFilter = document.getElementById('filter-country');
        const country = countryFilter ? countryFilter.value : '';
        const url = country ? `/api/photo-submissions/list?country=${encodeURIComponent(country)}` : '/api/photo-submissions/list';
        
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            console.error('Failed to load submissions');
            return;
        }

        const data = await response.json();
        allSubmissions = data.submissions || [];
        renderSubmissions(allSubmissions);
    } catch (error) {
        console.error('Error loading submissions:', error);
    }
}

function renderSubmissions(submissions) {
    const tbody = document.getElementById('submissions-tbody');
    
    if (submissions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">Aucune soumission trouvée</td></tr>';
        return;
    }

    tbody.innerHTML = submissions.map((sub, idx) => {
        const submittedAt = sub.submitted_at ? new Date(sub.submitted_at).toLocaleString('fr-FR') : '-';
        const statusBadge = sub.status === 'pending' 
            ? '<span class="badge bg-warning">En attente</span>'
            : '<span class="badge bg-success">Résolue</span>';

        const actionBtn = sub.status === 'pending'
            ? `<button class="btn btn-sm btn-info" onclick="openPhotoModal(${idx})"><i class="fas fa-eye me-1"></i>Voir</button>`
            : '';

        return `
            <tr>
                <td>${sub.id}</td>
                <td><strong>${sub.license_plate || '-'}</strong></td>
                <td>${sub.user?.username || '-'}</td>
                <td>${sub.description || '-'}</td>
                <td>${submittedAt}</td>
                <td>${statusBadge}</td>
                <td>${actionBtn}</td>
            </tr>
        `;
    }).join('');
}

function filterSubmissions() {
    const status = document.getElementById('filter-status').value;
    const plate = document.getElementById('filter-plate').value.toUpperCase();
    const username = document.getElementById('filter-username').value.toLowerCase();
    const country = document.getElementById('filter-country') ? document.getElementById('filter-country').value : '';

    let filtered = allSubmissions.filter(sub => {
        const matchStatus = !status || sub.status === status;
        const matchPlate = !plate || (sub.license_plate && sub.license_plate.includes(plate));
        const matchUser = !username || (sub.user?.username?.toLowerCase().includes(username));
        const matchCountry = !country || (sub.vehicle?.owner_island === country);
        
        return matchStatus && matchPlate && matchUser && matchCountry;
    });

    renderSubmissions(filtered);
}

function openPhotoModal(index) {
    const submission = allSubmissions[index];
    if (!submission) return;

    currentModal = submission;

    // Déterminer l'URL de la photo
    let photoUrl = '';
    if (submission.photo_filename) {
        photoUrl = `/static/photo_submissions/${submission.photo_filename}`;
    }

    // Remplir les champs du modal
    document.getElementById('photo-preview').src = photoUrl;
    document.getElementById('modal-plate').textContent = submission.license_plate || '-';
    document.getElementById('modal-username').textContent = submission.user?.username || '-';
    document.getElementById('modal-description').textContent = submission.description || '-';
    
    const submittedAt = submission.submitted_at ? new Date(submission.submitted_at).toLocaleString('fr-FR') : '-';
    document.getElementById('modal-submitted-at').textContent = submittedAt;

    // Statut
    const statusEl = document.getElementById('modal-status');
    if (submission.status === 'pending') {
        statusEl.textContent = 'En attente';
        statusEl.className = 'badge bg-warning';
    } else {
        statusEl.textContent = 'Résolue';
        statusEl.className = 'badge bg-success';
    }

    // Afficher/masquer les sections
    const reviewSection = document.getElementById('review-section');
    const reviewedSection = document.getElementById('reviewed-section');

    if (submission.status === 'pending') {
        reviewSection.style.display = 'block';
        reviewedSection.style.display = 'none';
        document.getElementById('review-notes').value = '';
    } else {
        reviewSection.style.display = 'none';
        reviewedSection.style.display = 'block';
        
        const reviewerName = submission.reviewed_by_user?.username || '-';
        const reviewedAt = submission.reviewed_at ? new Date(submission.reviewed_at).toLocaleString('fr-FR') : '-';
        
        document.getElementById('modal-reviewer-name').textContent = reviewerName;
        document.getElementById('modal-reviewed-at').textContent = reviewedAt;
        document.getElementById('modal-review-notes').textContent = submission.review_notes || '(Aucun commentaire)';
    }

    // Afficher le modal
    const modal = new bootstrap.Modal(document.getElementById('photoModal'));
    modal.show();
}

async function resolveSubmission() {
    if (!currentModal.id) return;

    const reviewNotes = document.getElementById('review-notes').value.trim();

    try {
        const response = await fetch(`/api/photo-submissions/${currentModal.id}/review`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                status: 'resolved',
                review_notes: reviewNotes
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert('Erreur: ' + (errorData.error || 'Impossible de valider'));
            return;
        }

        alert('✓ Soumission marquée comme résolue');
        
        // Fermer le modal et recharger
        bootstrap.Modal.getInstance(document.getElementById('photoModal')).hide();
        loadSubmissions();
    } catch (error) {
        console.error('Error resolving submission:', error);
        alert('Erreur lors de la validation');
    }
}

async function deleteSubmission() {
    if (!currentModal.id) return;

    if (!confirm('Êtes-vous sûr de vouloir supprimer cette soumission ?')) {
        return;
    }

    try {
        const response = await fetch(`/api/photo-submissions/${currentModal.id}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert('Erreur: ' + (errorData.error || 'Impossible de supprimer'));
            return;
        }

        alert('✓ Soumission supprimée');
        
        // Fermer le modal et recharger
        bootstrap.Modal.getInstance(document.getElementById('photoModal')).hide();
        loadSubmissions();
    } catch (error) {
        console.error('Error deleting submission:', error);
        alert('Erreur lors de la suppression');
    }
}

function expandPhoto() {
    if (!currentModal.photo_filename) return;
    const photoUrl = `/static/photo_submissions/${currentModal.photo_filename}`;
    window.open(photoUrl, '_blank');
}
