function escHtmlReceipt(s) {
    return (s || '').toString().replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function fmtReceipt(n) { return Math.round(n).toLocaleString('fr'); }

function printReceipt(sale) {
    const w = window.open('', '_blank', 'width=850,height=1100');
    const esc = escHtmlReceipt;
    const fmt = fmtReceipt;
    const receiptNo = 'REC-' + String(sale.id).padStart(6, '0');

    w.document.write('<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">' +
        '<title>Reçu ' + receiptNo + '</title><style>' +
        '@page { size: A4 portrait; margin: 20mm; }' +
        '* { box-sizing: border-box; margin: 0; padding: 0; }' +
        'html, body { background: #e9edf1; }' +
        'body { font-family: "Segoe UI", Arial, sans-serif; color: #1a1a2e; font-size: 14px; display: flex; justify-content: center; padding: 24px 0; }' +
        '.page { background: #fff; width: 210mm; min-height: 297mm; padding: 20mm; box-shadow: 0 0 12px rgba(0,0,0,0.15); }' +
        '.receipt-header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #0f3460; padding-bottom: 18px; }' +
        '.receipt-header .org { font-size: 26px; font-weight: 800; color: #0f3460; letter-spacing: .5px; }' +
        '.receipt-header .sub { font-size: 12px; color: #667; margin-top: 4px; }' +
        '.receipt-header .doc-label { text-align: right; font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #8892a0; }' +
        '.receipt-header .doc-no { text-align: right; font-size: 20px; font-weight: 800; color: #0f3460; margin-top: 4px; }' +
        '.meta-strip { display: flex; justify-content: space-between; margin-top: 22px; padding: 12px 18px; background: #f4f6f9; border-radius: 8px; font-size: 12.5px; color: #556; }' +
        '.meta-strip strong { color: #1a1a2e; }' +
        '.section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #8892a0; margin: 32px 0 10px; font-weight: 700; }' +
        '.items-table { width: 100%; border-collapse: collapse; }' +
        '.items-table thead th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .4px; color: #fff; background: #0f3460; padding: 10px 14px; }' +
        '.items-table thead th.num, .items-table tbody td.num { text-align: right; }' +
        '.items-table tbody td { padding: 14px; border-bottom: 1px solid #eef0f3; font-size: 14px; }' +
        '.items-table tbody td.item-name { font-weight: 600; }' +
        '.items-table tbody tr:nth-child(even) { background: #fafbfc; }' +
        '.total-row { display: flex; justify-content: flex-end; align-items: baseline; gap: 14px; padding: 20px 14px 6px; border-top: 2px solid #1a1a2e; margin-top: 4px; }' +
        '.total-row .label { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px; color: #444; }' +
        '.total-row .value { font-size: 28px; font-weight: 800; color: #1a7f37; }' +
        '.info-grid { display: flex; gap: 32px; margin-top: 28px; }' +
        '.info-col { flex: 1; }' +
        '.info-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #eef0f3; font-size: 13px; }' +
        '.info-row .label { color: #8892a0; } .info-row .value { font-weight: 600; }' +
        '.sig-row { display: flex; gap: 40px; margin-top: 64px; }' +
        '.sig-box { flex: 1; text-align: center; }' +
        '.sig-line { border-bottom: 1px solid #aab2bd; height: 48px; }' +
        '.sig-label { font-size: 11px; color: #8892a0; margin-top: 6px; text-transform: uppercase; letter-spacing: .5px; }' +
        '.receipt-footer { text-align: center; margin-top: 40px; padding-top: 16px; border-top: 1px solid #eef0f3; font-size: 11px; color: #8892a0; }' +
        '.receipt-footer .thanks { font-weight: 700; color: #0f3460; font-size: 13px; margin-bottom: 4px; }' +
        '.no-print { text-align: center; padding: 18px; }' +
        '.btn-print { background: #0f3460; color: #fff; border: none; padding: 10px 30px; border-radius: 8px; font-size: 14px; cursor: pointer; font-weight: 600; }' +
        '@media print { html, body { background: #fff; padding: 0; } .page { box-shadow: none; width: auto; min-height: 0; padding: 0; } .no-print { display: none; } }' +
        '</style></head><body>' +
        '<div>' +
        '<div class="page">' +
          '<div class="receipt-header">' +
            '<div><div class="org">SMART DEVELOPMENT</div><div class="sub">MORONI — COMORES</div></div>' +
            '<div><div class="doc-label">Reçu de vente</div><div class="doc-no">' + receiptNo + '</div></div>' +
          '</div>' +
          '<div class="meta-strip"><span>Date : <strong>' + esc(sale.sold_at) + '</strong></span><span>Vendu par : <strong>' + esc(sale.sold_by || '—') + '</strong></span></div>' +

          '<div class="section-title">Détail de la vente</div>' +
          '<table class="items-table">' +
            '<thead><tr><th>Article</th><th class="num">Qté</th><th class="num">Prix unit.</th><th class="num">Montant</th></tr></thead>' +
            '<tbody><tr>' +
              '<td class="item-name">' + esc(sale.item_name) + '</td>' +
              '<td class="num">' + sale.quantity + '</td>' +
              '<td class="num">' + fmt(sale.unit_price) + ' KMF</td>' +
              '<td class="num">' + fmt(sale.total_amount) + ' KMF</td>' +
            '</tr></tbody>' +
          '</table>' +
          '<div class="total-row"><span class="label">Total payé</span><span class="value">' + fmt(sale.total_amount) + ' KMF</span></div>' +

          '<div class="info-grid">' +
            '<div class="info-col"><div class="info-row"><span class="label">Client</span><span class="value">' + (sale.customer_name ? esc(sale.customer_name) : '—') + '</span></div></div>' +
            '<div class="info-col"><div class="info-row"><span class="label">Mode de règlement</span><span class="value">Espèces</span></div></div>' +
          '</div>' +

          '<div class="sig-row">' +
            '<div class="sig-box"><div class="sig-line"></div><div class="sig-label">Signature client</div></div>' +
            '<div class="sig-box"><div class="sig-line"></div><div class="sig-label">Signature agent</div></div>' +
          '</div>' +

          '<div class="receipt-footer">' +
            '<div class="thanks">Merci pour votre achat</div>' +
            'Ce reçu fait foi de paiement et doit être conservé.' +
          '</div>' +
        '</div>' +
        '<div class="no-print"><button class="btn-print" onclick="window.print()">🖨️ Imprimer</button></div>' +
        '</div>' +
        '</body></html>');
    w.document.close();
}
