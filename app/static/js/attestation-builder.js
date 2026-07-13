/* attestation-builder.js — 5 layout builders for insurance attestation cards */

window.ATTESTATION_MODELS = [
  { id: 1, name: 'Classique',      desc: 'Fond ivoire, style officiel',       color: '#fffff0' },
  { id: 2, name: 'Moderne Bleu',   desc: 'En-tête coloré, design contemporain', color: '#ffffff' },
  { id: 3, name: 'Vert Forêt',     desc: 'Accents verts, sobre et élégant',   color: '#f5fbf5' },
  { id: 4, name: 'Bordeaux',       desc: 'Double filet rouge, classique chic', color: '#fdf8f2' },
  { id: 5, name: 'Minimaliste',    desc: 'Blanc épuré, lignes fines',          color: '#ffffff' },
];

function _initials(name) {
  return (name || 'X').split(/\s+/).map(w => w[0] || '').join('').toUpperCase().slice(0, 4);
}
function _police(tpl, vehicleId) {
  const ini = _initials(tpl.company_name || 'X');
  return ini + String(vehicleId).padStart(6, '0');
}
function _serial(vehicleId) { return String(vehicleId).padStart(5, '0'); }
function _arrete(v) {
  const id   = String(v.insurance_id || 1).padStart(3, '0');
  const year = v.insurance_year || new Date().getFullYear();
  return `N°${id}/${year}`;
}
function _logoTag(b64, initials) {
  return b64
    ? `<img src="${b64}" style="max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block;">`
    : `<span style="font-size:20px;font-weight:900;color:#1a5c2a;line-height:1;">${initials}</span>`;
}

/* ═══════════════════════════════════════════════════════════════
   MODEL 1 — CLASSIQUE (ivoire, Times New Roman, grid header)
═══════════════════════════════════════════════════════════════ */
function buildModel1(tpl, v) {
  const bg     = tpl.card_color || '#fffff0';
  const ini    = _initials(tpl.company_name);
  const police = _police(tpl, v.id);
  const logo   = _logoTag(tpl.logo_b64, ini);
  return `
<div style="background:${bg};border:2px solid #333;font-family:'Times New Roman',serif;font-size:11px;width:680px;color:#000;">
  <div style="display:grid;grid-template-columns:3fr 2fr;border-bottom:2px solid #333;">
    <div style="display:grid;grid-template-columns:110px 1fr;border-right:2px solid #333;">
      <div style="border-right:1px solid #333;display:flex;align-items:center;justify-content:center;padding:8px;min-height:90px;">${logo}</div>
      <div style="padding:6px 8px;font-size:9px;line-height:1.5;">
        <strong>${tpl.company_name||''}</strong><br>
        ${tpl.company_code?`${tpl.company_code}<br>`:''}
        ${tpl.capital?`S.A au Capital Social : ${tpl.capital} KMF<br>`:''}
        ${tpl.bic?`N°Compte BIC : ${tpl.bic} KMF<br>`:''}
        ${tpl.company_address?`Siège social, ${tpl.company_address}<br>`:''}
        ${tpl.company_phone?`Tél. : ${tpl.company_phone}<br>`:''}
        ${tpl.company_email?`E-mail : ${tpl.company_email}`:''}
      </div>
    </div>
    <div style="padding:10px 14px;display:flex;flex-direction:column;justify-content:center;">
      <div style="font-size:14px;font-weight:bold;text-align:center;text-transform:uppercase;border-bottom:1px solid #333;padding-bottom:6px;margin-bottom:6px;">Attestation d'Assurance</div>
      ${_arrete(v)?`<div style="font-size:10px;text-align:center;">Arrêté ${_arrete(v)}</div>`:''}
    </div>
  </div>
  <div style="padding:10px 14px;line-height:2.0;">
    <div style="display:flex;gap:6px;"><b>N° de Police :</b> ${police} <span style="margin-left:40px;font-weight:bold;">N° ${v.id}</span></div>
    <div style="display:flex;gap:6px;"><b>Souscripteur (Nom et Prénom) :</b> <span style="text-transform:uppercase;">${v.owner_name}</span></div>
    <div style="display:flex;gap:6px;"><b>Adresse</b> <span style="margin-left:6px;">: <span style="text-transform:uppercase;">${v.owner_address}</span></span></div>
    <div style="display:flex;gap:6px;"><b>Valable du :</b> ${v.today} à 00 HEURE 00 Min &nbsp;&nbsp; au &nbsp;&nbsp; ${v.insurance_expiry} à MINUIT</div>
  </div>
  <div style="border-top:2px solid #333;border-bottom:2px solid #333;margin-top:8px;">
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr>
        <th style="border:1px solid #333;padding:5px 8px;text-align:center;font-size:10px;background:#e8e8d0;text-transform:uppercase;">Genre</th>
        <th style="border:1px solid #333;padding:5px 8px;text-align:center;font-size:10px;background:#e8e8d0;text-transform:uppercase;">Marque<br><small style="font-weight:normal;font-size:8px;">(et type pour les remorques)</small></th>
        <th style="border:1px solid #333;padding:5px 8px;text-align:center;font-size:10px;background:#e8e8d0;text-transform:uppercase;">Numéro Immatriculation<br><small style="font-weight:normal;font-size:8px;">(ou à défaut N° du moteur)</small></th>
      </tr></thead>
      <tbody><tr>
        <td style="border:1px solid #333;padding:10px 8px;text-align:center;font-size:13px;font-weight:bold;text-transform:uppercase;">${v.vehicle_type}</td>
        <td style="border:1px solid #333;padding:10px 8px;text-align:center;font-size:13px;font-weight:bold;text-transform:uppercase;">${v.model}</td>
        <td style="border:1px solid #333;padding:10px 8px;text-align:center;font-size:13px;font-weight:bold;">${v.license_plate}</td>
      </tr></tbody>
    </table>
  </div>
  <div style="padding:8px 14px 6px;font-size:10px;">Délivrée le ${v.today}</div>
  <div style="color:#cc0000;font-size:18px;font-weight:bold;font-family:monospace;padding:4px 14px;border-top:1px solid #333;">${_serial(v.id)}</div>
  <div style="font-size:8px;color:#444;padding:4px 14px 8px;font-style:italic;line-height:1.4;">${tpl.legal_notice || "La présentation de ce document justificatif n'implique qu'une présomption de garantie à la charge de l'Assureur."}</div>
</div>`;
}

/* ═══════════════════════════════════════════════════════════════
   MODEL 2 — MODERNE BLEU (en-tête pleine largeur coloré)
═══════════════════════════════════════════════════════════════ */
function buildModel2(tpl, v) {
  const accent = tpl.card_color && tpl.card_color !== '#ffffff' ? tpl.card_color : '#1a4b8c';
  const ini    = _initials(tpl.company_name);
  const police = _police(tpl, v.id);
  const logo   = _logoTag(tpl.logo_b64, ini);
  return `
<div style="background:#fff;border:1.5px solid ${accent};font-family:Arial,sans-serif;font-size:11px;width:680px;color:#000;border-radius:4px;overflow:hidden;">
  <!-- Header bar -->
  <div style="background:${accent};color:#fff;display:flex;align-items:center;justify-content:space-between;padding:10px 16px;min-height:80px;">
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="background:#fff;border-radius:4px;width:90px;height:72px;display:flex;align-items:center;justify-content:center;padding:5px;flex-shrink:0;">${logo}</div>
      <div>
        <div style="font-size:14px;font-weight:bold;letter-spacing:0.5px;">${tpl.company_name||''}</div>
        ${tpl.company_code?`<div style="font-size:8px;opacity:0.8;margin-top:1px;">${tpl.company_code}</div>`:''}
        <div style="font-size:9px;opacity:0.85;margin-top:2px;">
          ${tpl.company_address||''} ${tpl.company_phone?'• Tél. '+tpl.company_phone:''}
        </div>
        <div style="font-size:8px;opacity:0.75;">
          ${tpl.capital?'Capital : '+tpl.capital+' KMF':''} ${tpl.bic?'• BIC : '+tpl.bic:''}
        </div>
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:16px;font-weight:bold;text-transform:uppercase;letter-spacing:1px;">Attestation<br>d'Assurance</div>
      ${_arrete(v)?`<div style="font-size:9px;opacity:0.85;margin-top:4px;">Arrêté ${_arrete(v)}</div>`:''}
    </div>
  </div>
  <!-- Body -->
  <div style="padding:12px 16px;line-height:1.9;border-bottom:1px solid #ddd;">
    <div><b>N° de Police :</b> ${police} &nbsp;&nbsp;&nbsp; <b>N° :</b> ${v.id}</div>
    <div><b>Souscripteur :</b> <span style="text-transform:uppercase;">${v.owner_name}</span></div>
    <div><b>Adresse :</b> <span style="text-transform:uppercase;">${v.owner_address}</span></div>
    <div><b>Valable du :</b> ${v.today} à 00 H 00 Min &nbsp; <b>au</b> &nbsp; ${v.insurance_expiry} à MINUIT</div>
  </div>
  <!-- Table -->
  <table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th style="background:${accent}22;border:1px solid #ccc;padding:6px;text-align:center;font-size:10px;color:${accent};text-transform:uppercase;">Genre</th>
      <th style="background:${accent}22;border:1px solid #ccc;padding:6px;text-align:center;font-size:10px;color:${accent};text-transform:uppercase;">Marque</th>
      <th style="background:${accent}22;border:1px solid #ccc;padding:6px;text-align:center;font-size:10px;color:${accent};text-transform:uppercase;">N° Immatriculation</th>
    </tr></thead>
    <tbody><tr>
      <td style="border:1px solid #ccc;padding:10px;text-align:center;font-size:14px;font-weight:bold;text-transform:uppercase;">${v.vehicle_type}</td>
      <td style="border:1px solid #ccc;padding:10px;text-align:center;font-size:14px;font-weight:bold;text-transform:uppercase;">${v.model}</td>
      <td style="border:1px solid #ccc;padding:10px;text-align:center;font-size:14px;font-weight:bold;">${v.license_plate}</td>
    </tr></tbody>
  </table>
  <!-- Footer -->
  <div style="padding:8px 16px;display:flex;justify-content:space-between;align-items:center;border-top:1px solid #eee;">
    <div style="font-size:10px;">Délivrée le ${v.today}</div>
    <div style="color:${accent};font-size:16px;font-weight:bold;font-family:monospace;">${_serial(v.id)}</div>
  </div>
  <div style="font-size:8px;color:#666;padding:0 16px 8px;font-style:italic;">${tpl.legal_notice || "La présentation de ce document justificatif n'implique qu'une présomption de garantie à la charge de l'Assureur."}</div>
</div>`;
}

/* ═══════════════════════════════════════════════════════════════
   MODEL 3 — VERT FORÊT (bandeau vert, logo centré, aéré)
═══════════════════════════════════════════════════════════════ */
function buildModel3(tpl, v) {
  const green  = tpl.card_color && tpl.card_color !== '#f5fbf5' ? tpl.card_color : '#2d6a4f';
  const bg     = '#f5fbf5';
  const ini    = _initials(tpl.company_name);
  const police = _police(tpl, v.id);
  const logo   = _logoTag(tpl.logo_b64, ini);
  return `
<div style="background:${bg};border:2px solid ${green};font-family:Georgia,serif;font-size:11px;width:680px;color:#000;">
  <!-- Top green bar -->
  <div style="background:${green};color:#fff;padding:10px 16px;display:flex;align-items:center;gap:14px;">
    <div style="background:#fff;border-radius:8px;width:90px;height:72px;display:flex;align-items:center;justify-content:center;padding:5px;flex-shrink:0;">${logo}</div>
    <div style="flex:1;text-align:center;">
      <div style="font-size:16px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;">${tpl.company_name||''}</div>
      ${tpl.company_code?`<div style="font-size:8px;opacity:0.8;margin-top:1px;">${tpl.company_code}</div>`:''}
      ${tpl.company_address?`<div style="font-size:9px;opacity:0.85;margin-top:2px;">${tpl.company_address}</div>`:''}
      ${tpl.company_phone?`<div style="font-size:9px;opacity:0.8;">Tél. ${tpl.company_phone}</div>`:''}
    </div>
    <div style="text-align:right;flex-shrink:0;">
      <div style="font-size:10px;font-weight:bold;text-transform:uppercase;opacity:0.9;">ATTESTATION D'ASSURANCE</div>
      ${_arrete(v)?`<div style="font-size:8px;opacity:0.8;">Arrêté ${_arrete(v)}</div>`:''}
    </div>
  </div>
  <!-- Sub-info bar -->
  <div style="background:${green}22;padding:4px 16px;font-size:8.5px;color:${green};border-bottom:1px solid ${green}44;">
    ${tpl.capital?`Capital : ${tpl.capital} KMF &nbsp;|&nbsp; `:''} ${tpl.bic?`BIC : ${tpl.bic} &nbsp;|&nbsp; `:''} ${tpl.company_email||''}
  </div>
  <!-- Body -->
  <div style="padding:12px 16px 8px;line-height:2.0;border-bottom:1px solid ${green}55;">
    <div><b>N° de Police :</b> <span style="font-family:monospace;">${police}</span> &nbsp;&nbsp;&nbsp; <b>N° :</b> ${v.id}</div>
    <div><b>Souscripteur (Nom et Prénom) :</b> <span style="text-transform:uppercase;font-weight:bold;">${v.owner_name}</span></div>
    <div><b>Adresse :</b> <span style="text-transform:uppercase;">${v.owner_address}</span></div>
    <div><b>Valable du :</b> ${v.today} à 00 HEURE 00 Min &nbsp;&nbsp; <b>au</b> &nbsp;&nbsp; ${v.insurance_expiry} à MINUIT</div>
  </div>
  <!-- Table -->
  <table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th style="background:${green};color:#fff;border:1px solid ${green};padding:6px;text-align:center;font-size:10px;text-transform:uppercase;">Genre</th>
      <th style="background:${green};color:#fff;border:1px solid ${green};padding:6px;text-align:center;font-size:10px;text-transform:uppercase;">Marque</th>
      <th style="background:${green};color:#fff;border:1px solid ${green};padding:6px;text-align:center;font-size:10px;text-transform:uppercase;">N° Immatriculation</th>
    </tr></thead>
    <tbody><tr>
      <td style="border:1px solid ${green}55;padding:10px;text-align:center;font-size:13px;font-weight:bold;text-transform:uppercase;">${v.vehicle_type}</td>
      <td style="border:1px solid ${green}55;padding:10px;text-align:center;font-size:13px;font-weight:bold;text-transform:uppercase;">${v.model}</td>
      <td style="border:1px solid ${green}55;padding:10px;text-align:center;font-size:13px;font-weight:bold;">${v.license_plate}</td>
    </tr></tbody>
  </table>
  <!-- Footer -->
  <div style="padding:8px 16px;display:flex;justify-content:space-between;align-items:center;">
    <div style="font-size:10px;">Délivrée le ${v.today}</div>
    <div style="color:${green};font-size:16px;font-weight:bold;font-family:monospace;">${_serial(v.id)}</div>
  </div>
  <div style="font-size:8px;color:#555;padding:0 16px 8px;font-style:italic;border-top:1px solid ${green}33;">${tpl.legal_notice || "La présentation de ce document justificatif n'implique qu'une présomption de garantie à la charge de l'Assureur."}</div>
</div>`;
}

/* ═══════════════════════════════════════════════════════════════
   MODEL 4 — BORDEAUX ÉLÉGANT (double filet, typographie soignée)
═══════════════════════════════════════════════════════════════ */
function buildModel4(tpl, v) {
  const red    = tpl.card_color && tpl.card_color !== '#fdf8f2' ? tpl.card_color : '#8b1a2e';
  const bg     = '#fdf8f2';
  const ini    = _initials(tpl.company_name);
  const police = _police(tpl, v.id);
  const logo   = _logoTag(tpl.logo_b64, ini);
  return `
<div style="background:${bg};border:3px double ${red};font-family:'Times New Roman',serif;font-size:11px;width:680px;color:#000;padding:6px;">
  <div style="border:1px solid ${red};padding:0;">
    <!-- Header -->
    <div style="border-bottom:2px solid ${red};display:flex;align-items:stretch;">
      <div style="border-right:1px solid ${red};padding:8px 10px;display:flex;flex-direction:column;align-items:center;justify-content:center;width:100px;flex-shrink:0;">
        <div style="width:80px;height:64px;display:flex;align-items:center;justify-content:center;padding:4px;">${logo}</div>
      </div>
      <div style="flex:1;padding:8px 12px;font-size:9px;line-height:1.6;">
        <strong style="font-size:11px;">${tpl.company_name||''}</strong><br>
        ${tpl.company_code?`${tpl.company_code}<br>`:''}
        ${tpl.capital?`S.A au Capital Social : ${tpl.capital} KMF<br>`:''}
        ${tpl.bic?`N°Compte BIC : ${tpl.bic} KMF<br>`:''}
        ${tpl.company_address?`${tpl.company_address}<br>`:''}
        ${tpl.company_phone?`Tél. : ${tpl.company_phone} &nbsp; `:''}${tpl.company_email?`— ${tpl.company_email}`:''}
      </div>
      <div style="border-left:1px solid ${red};padding:10px 14px;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:160px;text-align:center;">
        <div style="color:${red};font-size:13px;font-weight:bold;text-transform:uppercase;letter-spacing:1px;">Attestation<br>d'Assurance</div>
        ${_arrete(v)?`<div style="font-size:9px;color:#555;margin-top:4px;border-top:1px solid ${red}44;padding-top:4px;">Arrêté ${_arrete(v)}</div>`:''}
      </div>
    </div>
    <!-- Body -->
    <div style="padding:10px 14px;line-height:2.0;border-bottom:1px solid ${red}55;">
      <div style="display:flex;gap:6px;"><b>N° de Police :</b> <span style="font-family:monospace;">${police}</span><span style="margin-left:40px;"><b>N° ${v.id}</b></span></div>
      <div style="display:flex;gap:6px;"><b>Souscripteur (Nom et Prénom) :</b> <span style="text-transform:uppercase;">${v.owner_name}</span></div>
      <div style="display:flex;gap:6px;"><b>Adresse :</b> <span style="text-transform:uppercase;">${v.owner_address}</span></div>
      <div style="display:flex;gap:6px;"><b>Valable du :</b> ${v.today} à 00 HEURE 00 Min &nbsp;&nbsp; au &nbsp;&nbsp; ${v.insurance_expiry} à MINUIT</div>
    </div>
    <!-- Table -->
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr>
        <th style="background:${red};color:#fff;border:1px solid ${red};padding:5px 8px;text-align:center;font-size:10px;text-transform:uppercase;">Genre</th>
        <th style="background:${red};color:#fff;border:1px solid ${red};padding:5px 8px;text-align:center;font-size:10px;text-transform:uppercase;">Marque</th>
        <th style="background:${red};color:#fff;border:1px solid ${red};padding:5px 8px;text-align:center;font-size:10px;text-transform:uppercase;">N° Immatriculation</th>
      </tr></thead>
      <tbody><tr>
        <td style="border:1px solid ${red}44;padding:10px;text-align:center;font-size:13px;font-weight:bold;text-transform:uppercase;">${v.vehicle_type}</td>
        <td style="border:1px solid ${red}44;padding:10px;text-align:center;font-size:13px;font-weight:bold;text-transform:uppercase;">${v.model}</td>
        <td style="border:1px solid ${red}44;padding:10px;text-align:center;font-size:13px;font-weight:bold;">${v.license_plate}</td>
      </tr></tbody>
    </table>
    <!-- Footer -->
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 14px;border-top:1px solid ${red}44;">
      <div style="font-size:10px;">Délivrée le ${v.today}</div>
      <div style="color:${red};font-size:17px;font-weight:bold;font-family:monospace;">${_serial(v.id)}</div>
    </div>
    <div style="font-size:8px;color:#555;padding:0 14px 6px;font-style:italic;">${tpl.legal_notice || "La présentation de ce document justificatif n'implique qu'une présomption de garantie à la charge de l'Assureur."}</div>
  </div>
</div>`;
}

/* ═══════════════════════════════════════════════════════════════
   MODEL 5 — MINIMALISTE (blanc pur, lignes fines, aéré)
═══════════════════════════════════════════════════════════════ */
function buildModel5(tpl, v) {
  const accent = tpl.card_color && tpl.card_color !== '#ffffff' ? tpl.card_color : '#333333';
  const ini    = _initials(tpl.company_name);
  const police = _police(tpl, v.id);
  const logo   = _logoTag(tpl.logo_b64, ini);
  return `
<div style="background:#fff;border:1px solid #ccc;font-family:Arial,Helvetica,sans-serif;font-size:11px;width:680px;color:#111;">
  <!-- Top strip -->
  <div style="height:4px;background:${accent};"></div>
  <!-- Header -->
  <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid #ddd;">
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="width:90px;height:72px;display:flex;align-items:center;justify-content:center;padding:4px;flex-shrink:0;">${logo}</div>
      <div>
        <div style="font-size:13px;font-weight:bold;color:${accent};">${tpl.company_name||''}</div>
        ${tpl.company_code?`<div style="font-size:8px;color:#888;margin-top:1px;">${tpl.company_code}</div>`:''}
        <div style="font-size:9px;color:#666;margin-top:2px;">
          ${[tpl.company_address, tpl.company_phone?`Tél. ${tpl.company_phone}`:'', tpl.company_email].filter(Boolean).join(' · ')}
        </div>
        ${(tpl.capital||tpl.bic)?`<div style="font-size:8px;color:#888;margin-top:1px;">${tpl.capital?'Capital '+tpl.capital+' KMF':''} ${tpl.bic?'· BIC '+tpl.bic:''}</div>`:''}
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:13px;font-weight:bold;color:${accent};text-transform:uppercase;letter-spacing:0.5px;">Attestation d'Assurance</div>
      ${_arrete(v)?`<div style="font-size:9px;color:#888;margin-top:2px;">Arrêté ${_arrete(v)}</div>`:''}
    </div>
  </div>
  <!-- Data rows -->
  <div style="padding:10px 18px;line-height:2.1;">
    <div style="display:grid;grid-template-columns:160px 1fr;gap:2px;">
      <span style="color:#888;font-size:10px;">N° de Police</span>
      <span style="font-weight:600;font-family:monospace;">${police} &nbsp;–&nbsp; N° ${v.id}</span>
      <span style="color:#888;font-size:10px;">Souscripteur</span>
      <span style="font-weight:600;text-transform:uppercase;">${v.owner_name}</span>
      <span style="color:#888;font-size:10px;">Adresse</span>
      <span style="text-transform:uppercase;">${v.owner_address}</span>
      <span style="color:#888;font-size:10px;">Valable du</span>
      <span>${v.today} &nbsp;→&nbsp; ${v.insurance_expiry}</span>
    </div>
  </div>
  <!-- Table -->
  <div style="border-top:1px solid #ddd;border-bottom:1px solid #ddd;">
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr>
        <th style="background:#f5f5f5;border-right:1px solid #ddd;padding:6px 10px;text-align:center;font-size:10px;color:#555;text-transform:uppercase;font-weight:600;">Genre</th>
        <th style="background:#f5f5f5;border-right:1px solid #ddd;padding:6px 10px;text-align:center;font-size:10px;color:#555;text-transform:uppercase;font-weight:600;">Marque</th>
        <th style="background:#f5f5f5;padding:6px 10px;text-align:center;font-size:10px;color:#555;text-transform:uppercase;font-weight:600;">N° Immatriculation</th>
      </tr></thead>
      <tbody><tr>
        <td style="border-right:1px solid #eee;padding:11px 10px;text-align:center;font-size:14px;font-weight:700;text-transform:uppercase;">${v.vehicle_type}</td>
        <td style="border-right:1px solid #eee;padding:11px 10px;text-align:center;font-size:14px;font-weight:700;text-transform:uppercase;">${v.model}</td>
        <td style="padding:11px 10px;text-align:center;font-size:14px;font-weight:700;letter-spacing:1px;">${v.license_plate}</td>
      </tr></tbody>
    </table>
  </div>
  <!-- Footer -->
  <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 18px;">
    <div style="font-size:10px;color:#555;">Délivrée le <strong>${v.today}</strong></div>
    <div style="font-family:monospace;font-size:15px;font-weight:bold;color:${accent};">${_serial(v.id)}</div>
  </div>
  <div style="height:3px;background:${accent};opacity:0.4;"></div>
  <div style="font-size:8px;color:#999;padding:4px 18px 6px;font-style:italic;">${tpl.legal_notice || "La présentation de ce document justificatif n'implique qu'une présomption de garantie à la charge de l'Assureur."}</div>
</div>`;
}

/* ─── Dispatcher ─── */
window.buildAttestationHTML = function(tpl, vehicle) {
  const layout = parseInt(tpl.layout || 1);
  const builders = { 1: buildModel1, 2: buildModel2, 3: buildModel3, 4: buildModel4, 5: buildModel5 };
  return (builders[layout] || buildModel1)(tpl, vehicle);
};
