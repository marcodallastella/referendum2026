// ---------------------------------------------------------------------------
// Referendum 2026 — Main Application
// ---------------------------------------------------------------------------

let map, geojsonLayer, regionLayer, cityLabelsLayer;
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
    if (n == null || isNaN(n)) return '\u2014';
    return n.toLocaleString('it-IT');
}

function fmtPerc(n) {
    if (n == null || isNaN(n)) return '\u2014';
    return n.toFixed(1).replace('.', ',') + '%';
}

function fmtPerc2(n) {
    if (n == null || isNaN(n)) return '\u2014';
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
            '<p style="padding:2rem;color:#c0392b;">Errore nel caricamento dei dati.</p>';
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

    // Progression — compact inline text
    const progEl = document.getElementById('progression');
    const parts = d.affluenza.snapshots
        .filter(s => s.votanti > 0)
        .map(s => `${s.label}\u00a0\u2192\u00a0${fmtPerc(s.perc)}`);
    progEl.textContent = parts.join('  |\u00a0\u00a0');

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

    // Last update timestamp
    const now = new Date();
    const ts = now.toLocaleString('it-IT', {
        day: 'numeric', month: 'long', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
    document.getElementById('last-update').textContent = 'Ultimo aggiornamento: ' + ts;
}

// ---------------------------------------------------------------------------
// Mode toggle
// ---------------------------------------------------------------------------

function setMode(mode) {
    currentMode = mode;

    document.getElementById('btn-affluenza').classList.toggle('active', mode === 'affluenza');
    document.getElementById('btn-risultati').classList.toggle('active', mode === 'risultati');

    document.getElementById('summary-affluenza').style.display = mode === 'affluenza' ? '' : 'none';
    document.getElementById('summary-risultati').style.display = mode === 'risultati' ? '' : 'none';

    if (geojsonLayer) {
        geojsonLayer.setStyle(styleFeature);
    }
    updateLegend();
    buildRegionsTable();
}

window.setMode = setMode;

// ---------------------------------------------------------------------------
// City labels (20 capoluoghi di regione)
// ---------------------------------------------------------------------------

const CITY_COORDS = [
    { name: 'Roma', lat: 41.9028, lng: 12.4964 },
    { name: 'Milano', lat: 45.4642, lng: 9.1900 },
    { name: 'Napoli', lat: 40.8518, lng: 14.2681 },
    { name: 'Torino', lat: 45.0703, lng: 7.6869 },
    { name: 'Palermo', lat: 38.1157, lng: 13.3615 },
    { name: 'Genova', lat: 44.4056, lng: 8.9463 },
    { name: 'Bologna', lat: 44.4949, lng: 11.3426 },
    { name: 'Firenze', lat: 43.7696, lng: 11.2558 },
    { name: 'Bari', lat: 41.1171, lng: 16.8719 },
    { name: 'Catania', lat: 37.5079, lng: 15.0830 },
    { name: 'Venezia', lat: 45.4408, lng: 12.3155 },
    { name: 'Verona', lat: 45.4384, lng: 10.9916 },
    { name: 'Messina', lat: 38.1938, lng: 15.5540 },
    { name: 'Padova', lat: 45.4064, lng: 11.8768 },
    { name: 'Trieste', lat: 45.6495, lng: 13.7768 },
    { name: 'Brescia', lat: 45.5416, lng: 10.2118 },
    { name: 'Cagliari', lat: 39.2238, lng: 9.1217 },
    { name: 'Perugia', lat: 43.1107, lng: 12.3908 },
    { name: 'Reggio Calabria', lat: 38.1114, lng: 15.6473 },
    { name: "L\u2019Aquila", lat: 42.3498, lng: 13.3995 },
];

function createCityLabels() {
    cityLabelsLayer = L.layerGroup();

    CITY_COORDS.forEach(function(city) {
        // Small dot at exact coordinate
        var dot = L.circleMarker([city.lat, city.lng], {
            radius: 2,
            fillColor: '#1a1a1a',
            fillOpacity: 0.7,
            color: '#fff',
            weight: 1,
            interactive: false,
        });
        cityLabelsLayer.addLayer(dot);

        // Text label offset to the right/above
        var label = L.marker([city.lat, city.lng], {
            interactive: false,
            icon: L.divIcon({
                className: 'city-label',
                html: '<span>' + city.name + '</span>',
                iconSize: null,
                iconAnchor: [-5, 12],
            }),
        });
        cityLabelsLayer.addLayer(label);
    });

    return cityLabelsLayer;
}

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
            if (regionLayer) regionLayer.bringToFront();
        },
        click: function(e) {
            const p = feature.properties;
            let html = `<div class="popup-title">${p.comune}</div>`;
            html += `<div class="popup-subtitle">${p.provincia || ''} \u2014 ${p.regione || ''}</div>`;

            if (p.elettori) {
                html += `<div class="popup-row"><span>Elettori</span><span class="popup-val">${fmtNum(p.elettori)}</span></div>`;
            }

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

        // Layer 1: Municipality choropleth (interactive)
        geojsonLayer = L.geoJSON(geojson, {
            style: styleFeature,
            onEachFeature: onEachFeature,
        }).addTo(map);

        // Layer 2: Region outlines (non-interactive, on top of choropleth)
        try {
            const regResp = await fetch('data/regions.geojson');
            const regGeojson = await regResp.json();
            regionLayer = L.geoJSON(regGeojson, {
                interactive: false,
                style: {
                    color: '#333',
                    weight: 1.5,
                    opacity: 0.6,
                    fill: false,
                },
            }).addTo(map);
        } catch (e) {
            console.warn('Region boundaries not available:', e);
        }

        // Layer 3: City labels (non-interactive, topmost)
        createCityLabels().addTo(map);

        updateLegend();
    } catch (e) {
        console.error('Failed to load GeoJSON:', e);
        document.getElementById('map').innerHTML =
            '<p style="padding:3rem;color:#666;">GeoJSON non disponibile.</p>';
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

// Map column keys to their bar color CSS variable
const BAR_COLORS = {
    best_perc: 'var(--color-turnout-light)',
    perc_12: 'var(--color-turnout-light)',
    perc_19: 'var(--color-turnout-light)',
    perc_23: 'var(--color-turnout-light)',
    perc_si: 'var(--color-si-light)',
    perc_no: 'var(--color-no-light)',
};

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
    let rows = regionsData.map(r => ({
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
    }));

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

    // Build body with inline data bars
    tbody.innerHTML = rows.map(r =>
        '<tr>' + columns.map(c => {
            const val = r[c.key];
            const barColor = BAR_COLORS[c.key];
            if (barColor && val != null && !isNaN(val)) {
                // Percentage columns: bar width = value clamped to 100
                const w = Math.min(val, 100);
                return `<td class="cell-bar" style="--bar-width:${w}%;--bar-color:${barColor}"><span>${c.fmt(val)}</span></td>`;
            }
            return `<td>${c.fmt(val)}</td>`;
        }).join('') + '</tr>'
    ).join('');
}

function sortTable(col) {
    if (sortCol === col) {
        sortAsc = !sortAsc;
    } else {
        sortCol = col;
        sortAsc = col === 'regione';
    }
    buildRegionsTable();
}

window.sortTable = sortTable;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', loadData);
