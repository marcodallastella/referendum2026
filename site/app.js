// ---------------------------------------------------------------------------
// Referendum 2026 — Main Application
// ---------------------------------------------------------------------------

let map, geojsonLayer;
let nationalData = null;
let regionsData = null;
let currentMode = 'risultati'; // 'affluenza' or 'risultati'
let sortCol = null;
let sortAsc = true;

// ---------------------------------------------------------------------------
// Color scales
// ---------------------------------------------------------------------------

// Affluenza: white → dark blue
const AFFLUENZA_BREAKS = [0, 10, 20, 30, 40, 50, 60, 70, 80];
const AFFLUENZA_COLORS = [
    '#f7fbff', '#deebf7', '#c6dbef', '#9ecae1',
    '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b'
];

// Risultati: red (No) → white (50%) → green (Sì)
const RISULTATI_BREAKS = [0, 20, 35, 45, 50, 55, 65, 80, 100];
const RISULTATI_COLORS = [
    '#c62828', '#e57373', '#ffcdd2', '#fff9c4',
    '#f5f5f5',
    '#c8e6c9', '#66bb6a', '#2e7d32', '#1b5e20'
];

function getColor(value, breaks, colors) {
    if (value == null || isNaN(value)) return '#ccc';
    for (let i = breaks.length - 1; i >= 0; i--) {
        if (value >= breaks[i]) return colors[i];
    }
    return colors[0];
}

function getAffluenzaColor(perc) {
    return getColor(perc, AFFLUENZA_BREAKS, AFFLUENZA_COLORS);
}

function getRisultatiColor(percSi) {
    if (percSi == null) return '#d0d0d0';
    return getColor(percSi, RISULTATI_BREAKS, RISULTATI_COLORS);
}

// ---------------------------------------------------------------------------
// Number formatting
// ---------------------------------------------------------------------------

function fmtNum(n) {
    if (n == null || isNaN(n)) return '—';
    return n.toLocaleString('it-IT');
}

function fmtPerc(n) {
    if (n == null || isNaN(n)) return '—';
    return n.toFixed(1).replace('.', ',') + '%';
}

function fmtPerc2(n) {
    if (n == null || isNaN(n)) return '—';
    return n.toFixed(2).replace('.', ',') + '%';
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
    try {
        const [natResp, regResp] = await Promise.all([
            fetch('data/national.json'),
            fetch('data/regions.json'),
        ]);
        nationalData = await natResp.json();
        regionsData = await regResp.json();

        updateSummaryPanel();
        buildRegionsTable();
        loadMap();
    } catch (e) {
        console.error('Failed to load data:', e);
        document.getElementById('summary').innerHTML =
            '<p style="text-align:center;padding:2rem;color:#c62828;">Errore nel caricamento dei dati. Eseguire prima prepare_site.py.</p>';
    }
}

// ---------------------------------------------------------------------------
// Summary panel
// ---------------------------------------------------------------------------

function updateSummaryPanel() {
    if (!nationalData) return;
    const d = nationalData;

    // Affluenza
    document.getElementById('nat-elettori').textContent = fmtNum(d.elettori);
    document.getElementById('nat-affluenza').textContent = fmtPerc(d.affluenza.best_perc);
    document.getElementById('nat-votanti').textContent = fmtNum(d.affluenza.best_votanti);

    // Progression
    const progEl = document.getElementById('progression');
    const maxPerc = Math.max(...d.affluenza.snapshots.map(s => s.perc), 1);
    progEl.innerHTML = d.affluenza.snapshots.map(s => {
        const h = Math.max(2, (s.perc / maxPerc) * 60);
        const filled = s.votanti > 0 ? 'filled' : '';
        return `<div class="prog-step">
            <div class="prog-bar ${filled}" style="height:${h}px"></div>
            <div class="prog-perc">${s.votanti > 0 ? fmtPerc(s.perc) : '—'}</div>
            <div class="prog-label">${s.label}</div>
        </div>`;
    }).join('');

    // Results
    if (d.has_results) {
        document.getElementById('risultati-available').style.display = '';
        document.getElementById('risultati-unavailable').style.display = 'none';
        const r = d.results;
        document.getElementById('nat-si-perc').textContent = fmtPerc(r.perc_si);
        document.getElementById('nat-no-perc').textContent = fmtPerc(r.perc_no);
        document.getElementById('nat-si-count').textContent = fmtNum(r.si) + ' voti';
        document.getElementById('nat-no-count').textContent = fmtNum(r.no) + ' voti';
        document.getElementById('nat-validi').textContent = fmtNum(r.validi);
        document.getElementById('bar-si').style.width = r.perc_si + '%';
        document.getElementById('bar-no').style.width = r.perc_no + '%';
    } else {
        document.getElementById('risultati-available').style.display = 'none';
        document.getElementById('risultati-unavailable').style.display = '';
    }
}

// ---------------------------------------------------------------------------
// Mode toggle
// ---------------------------------------------------------------------------

function setMode(mode) {
    currentMode = mode;

    // Update buttons
    document.getElementById('btn-affluenza').classList.toggle('active', mode === 'affluenza');
    document.getElementById('btn-risultati').classList.toggle('active', mode === 'risultati');

    // Toggle summary content
    document.getElementById('summary-affluenza').style.display = mode === 'affluenza' ? '' : 'none';
    document.getElementById('summary-risultati').style.display = mode === 'risultati' ? '' : 'none';

    // Update map
    if (geojsonLayer) {
        geojsonLayer.setStyle(styleFeature);
    }
    updateLegend();

    // Update table
    buildRegionsTable();
}

// Make setMode available globally for onclick
window.setMode = setMode;

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------

function initMap() {
    map = L.map('map', {
        center: [42.0, 12.5],
        zoom: 6,
        minZoom: 5,
        maxZoom: 12,
        zoomSnap: 0.5,
        zoomDelta: 0.5,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
    }).addTo(map);
}

function styleFeature(feature) {
    const p = feature.properties;
    let fillColor;

    if (currentMode === 'affluenza') {
        fillColor = getAffluenzaColor(p.affluenza_perc || 0);
    } else {
        fillColor = getRisultatiColor(p.perc_si);
    }

    return {
        fillColor: fillColor,
        weight: 0.3,
        opacity: 0.6,
        color: '#333',
        fillOpacity: 0.85,
    };
}

function onEachFeature(feature, layer) {
    layer.on({
        mouseover: function(e) {
            e.target.setStyle({ weight: 2, color: '#000', fillOpacity: 0.95 });
            e.target.bringToFront();
        },
        mouseout: function(e) {
            geojsonLayer.resetStyle(e.target);
        },
        click: function(e) {
            const p = feature.properties;
            let html = `<div class="popup-title">${p.comune}</div>`;
            html += `<div class="popup-subtitle">${p.provincia || ''} — ${p.regione || ''}</div>`;

            if (p.elettori) {
                html += `<div class="popup-row"><span>Elettori</span><span class="popup-val">${fmtNum(p.elettori)}</span></div>`;
            }

            // Affluence snapshots
            html += `<div class="popup-section"><div class="popup-section-title">Affluenza</div>`;
            const labels = ['12:00', '19:00', '23:00', 'Finale'];
            for (let i = 1; i <= 4; i++) {
                const perc = p['com' + i + '_perc'];
                const vot = p['com' + i + '_vot'];
                if (vot > 0) {
                    html += `<div class="popup-row"><span>${labels[i-1]}</span><span class="popup-val">${fmtPerc(perc)} (${fmtNum(vot)})</span></div>`;
                }
            }
            html += '</div>';

            // Results
            if (p.perc_si != null) {
                html += `<div class="popup-section"><div class="popup-section-title">Risultati</div>`;
                html += `<div class="popup-row"><span>S\u00ec</span><span class="popup-val" style="color:var(--color-si)">${fmtPerc(p.perc_si)} (${fmtNum(p.si)})</span></div>`;
                html += `<div class="popup-row"><span>No</span><span class="popup-val" style="color:var(--color-no)">${fmtPerc(p.perc_no)} (${fmtNum(p.no)})</span></div>`;
                if (p.bianche != null) {
                    html += `<div class="popup-row"><span>Sch. bianche</span><span class="popup-val">${fmtNum(p.bianche)}</span></div>`;
                }
                if (p.nulle != null) {
                    html += `<div class="popup-row"><span>Sch. nulle</span><span class="popup-val">${fmtNum(p.nulle)}</span></div>`;
                }
                html += '</div>';
            }

            layer.bindPopup(html, { maxWidth: 280 }).openPopup();
        }
    });
}

async function loadMap() {
    initMap();

    try {
        const resp = await fetch('data/italy.geojson');
        const geojson = await resp.json();

        geojsonLayer = L.geoJSON(geojson, {
            style: styleFeature,
            onEachFeature: onEachFeature,
        }).addTo(map);

        updateLegend();
    } catch (e) {
        console.error('Failed to load GeoJSON:', e);
        document.getElementById('map').innerHTML =
            '<p style="text-align:center;padding:3rem;color:#666;">GeoJSON non disponibile. Eseguire prepare_site.py per generarlo.</p>';
    }
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function updateLegend() {
    const el = document.getElementById('legend');

    if (currentMode === 'affluenza') {
        const labels = ['0%', '10%', '20%', '30%', '40%', '50%', '60%', '70%', '80%+'];
        el.innerHTML = '<div class="legend-title">Affluenza</div>' +
            AFFLUENZA_COLORS.map((c, i) =>
                `<div class="legend-row"><span class="legend-swatch" style="background:${c}"></span>${labels[i]}</div>`
            ).join('');
    } else {
        const labels = ['0% S\u00ec', '20%', '35%', '45%', '50%', '55%', '65%', '80%', '100% S\u00ec'];
        el.innerHTML = '<div class="legend-title">% S\u00ec</div>' +
            RISULTATI_COLORS.map((c, i) =>
                `<div class="legend-row"><span class="legend-swatch" style="background:${c}"></span>${labels[i]}</div>`
            ).join('') +
            '<div class="legend-row"><span class="legend-swatch" style="background:#d0d0d0"></span>N/D</div>';
    }
}

// ---------------------------------------------------------------------------
// Regions table
// ---------------------------------------------------------------------------

function buildRegionsTable() {
    if (!regionsData) return;

    const thead = document.getElementById('regions-thead-row');
    const tbody = document.getElementById('regions-tbody');

    let columns;
    if (currentMode === 'affluenza') {
        columns = [
            { key: 'regione', label: 'Regione', align: 'left', fmt: v => v },
            { key: 'elettori', label: 'Elettori', fmt: fmtNum },
            { key: 'best_votanti', label: 'Votanti', fmt: fmtNum },
            { key: 'best_perc', label: 'Affluenza %', fmt: fmtPerc },
            { key: 'perc_12', label: '12:00', fmt: fmtPerc },
            { key: 'perc_19', label: '19:00', fmt: fmtPerc },
            { key: 'perc_23', label: '23:00', fmt: fmtPerc },
        ];
    } else {
        columns = [
            { key: 'regione', label: 'Regione', align: 'left', fmt: v => v },
            { key: 'elettori', label: 'Elettori', fmt: fmtNum },
            { key: 'perc_si', label: 'S\u00ec %', fmt: fmtPerc },
            { key: 'perc_no', label: 'No %', fmt: fmtPerc },
            { key: 'si', label: 'Voti S\u00ec', fmt: fmtNum },
            { key: 'no', label: 'Voti No', fmt: fmtNum },
            { key: 'validi', label: 'Validi', fmt: fmtNum },
        ];
    }

    // Build header
    thead.innerHTML = columns.map(c =>
        `<th data-col="${c.key}" onclick="sortTable('${c.key}')">${c.label}<span class="sort-arrow">${sortCol === c.key ? (sortAsc ? '\u25B2' : '\u25BC') : ''}</span></th>`
    ).join('');

    // Flatten data for table
    let rows = regionsData.map(r => {
        const flat = {
            regione: r.regione,
            elettori: r.elettori,
            best_votanti: r.affluenza.best_votanti,
            best_perc: r.affluenza.best_perc,
            perc_12: r.affluenza.snapshots[0].perc,
            perc_19: r.affluenza.snapshots[1].perc,
            perc_23: r.affluenza.snapshots[2].perc,
            perc_si: r.results.perc_si,
            perc_no: r.results.perc_no,
            si: r.results.si,
            no: r.results.no,
            validi: r.results.validi,
        };
        return flat;
    });

    // Sort
    if (sortCol) {
        rows.sort((a, b) => {
            let va = a[sortCol], vb = b[sortCol];
            if (va == null) va = -Infinity;
            if (vb == null) vb = -Infinity;
            if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            return sortAsc ? va - vb : vb - va;
        });
    }

    // Build body
    tbody.innerHTML = rows.map(r =>
        '<tr>' + columns.map(c => {
            const val = r[c.key];
            return `<td>${c.fmt(val)}</td>`;
        }).join('') + '</tr>'
    ).join('');
}

function sortTable(col) {
    if (sortCol === col) {
        sortAsc = !sortAsc;
    } else {
        sortCol = col;
        sortAsc = col === 'regione'; // ascending for text, descending for numbers
    }
    buildRegionsTable();
}

window.sortTable = sortTable;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', loadData);
