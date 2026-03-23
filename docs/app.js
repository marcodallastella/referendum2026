// ---------------------------------------------------------------------------
// Referendum 2026 — Main Application
// ---------------------------------------------------------------------------

let map;
let nationalData = null;
let regionsData = null;
let currentMode = 'risultati'; // 'affluenza' or 'risultati'
let sortCol = null;
let sortAsc = true;
let hoveredFeatureId = null;
let currentPopup = null;

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

// MapLibre step expressions for fill-color
function affluenzaFillExpression() {
    return [
        'step',
        ['coalesce', ['get', 'affluenza_perc'], 0],
        AFFLUENZA_COLORS[0],
        10, AFFLUENZA_COLORS[1],
        20, AFFLUENZA_COLORS[2],
        30, AFFLUENZA_COLORS[3],
        40, AFFLUENZA_COLORS[4],
        50, AFFLUENZA_COLORS[5],
        60, AFFLUENZA_COLORS[6],
        70, AFFLUENZA_COLORS[7],
        80, AFFLUENZA_COLORS[8]
    ];
}

function risultatiFillExpression() {
    return [
        'case',
        ['any',
            ['!', ['has', 'perc_si']],
            ['==', ['get', 'perc_si'], null]
        ],
        '#d0d0d0',
        [
            'step',
            ['get', 'perc_si'],
            RISULTATI_COLORS[0],
            20, RISULTATI_COLORS[1],
            35, RISULTATI_COLORS[2],
            45, RISULTATI_COLORS[3],
            50, RISULTATI_COLORS[4],
            55, RISULTATI_COLORS[5],
            65, RISULTATI_COLORS[6],
            80, RISULTATI_COLORS[7],
            100, RISULTATI_COLORS[8]
        ]
    ];
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

    updateChoroplethColors();
    updateLegend();
    buildRegionsTable();
}

window.setMode = setMode;

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------

function updateChoroplethColors() {
    if (!map || !map.getLayer('choropleth-fill')) return;
    var expr = currentMode === 'affluenza'
        ? affluenzaFillExpression()
        : risultatiFillExpression();
    map.setPaintProperty('choropleth-fill', 'fill-color', expr);
}

function buildPopupHTML(p) {
    let html = '<div class="popup-title">' + (p.comune || '') + '</div>';
    html += '<div class="popup-subtitle">' + (p.provincia || '') + ' \u2014 ' + (p.regione || '') + '</div>';

    if (p.elettori) {
        html += '<div class="popup-row"><span>Elettori</span><span class="popup-val">' + fmtNum(p.elettori) + '</span></div>';
    }

    html += '<div class="popup-section"><div class="popup-section-title">Affluenza</div>';
    var labels = ['12:00', '19:00', '23:00', 'Finale'];
    for (var i = 1; i <= 4; i++) {
        var perc = p['com' + i + '_perc'];
        var vot = p['com' + i + '_vot'];
        if (vot > 0) {
            html += '<div class="popup-row"><span>' + labels[i - 1] + '</span><span class="popup-val">' + fmtPerc(perc) + ' (' + fmtNum(vot) + ')</span></div>';
        }
    }
    html += '</div>';

    if (p.perc_si != null && p.perc_si !== undefined) {
        html += '<div class="popup-section"><div class="popup-section-title">Risultati</div>';
        html += '<div class="popup-row"><span>S\u00ec</span><span class="popup-val" style="color:var(--color-si)">' + fmtPerc(p.perc_si) + ' (' + fmtNum(p.si) + ')</span></div>';
        html += '<div class="popup-row"><span>No</span><span class="popup-val" style="color:var(--color-no)">' + fmtPerc(p.perc_no) + ' (' + fmtNum(p.no) + ')</span></div>';
        if (p.bianche != null && p.bianche !== undefined) {
            html += '<div class="popup-row"><span>Sch. bianche</span><span class="popup-val">' + fmtNum(p.bianche) + '</span></div>';
        }
        if (p.nulle != null && p.nulle !== undefined) {
            html += '<div class="popup-row"><span>Sch. nulle</span><span class="popup-val">' + fmtNum(p.nulle) + '</span></div>';
        }
        html += '</div>';
    }

    return html;
}

async function loadMap() {
    map = new maplibregl.Map({
        container: 'map',
        style: 'https://api.maptiler.com/maps/streets-v2/style.json?key=YOUR_MAPTILER_KEY',
        center: [12.5, 42.5],
        zoom: 5.5,
        minZoom: 5,
        maxZoom: 12,
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', async function () {
        try {
            // Find the first symbol (label) layer in the basemap style
            var layers = map.getStyle().layers;
            var firstLabelLayer;
            for (var i = 0; i < layers.length; i++) {
                var layer = layers[i];
                if (layer.type === 'symbol' && layer.layout && layer.layout['text-field']) {
                    firstLabelLayer = layer.id;
                    break;
                }
            }

            // Load GeoJSON
            var resp = await fetch('data/italy.geojson');
            var geojson = await resp.json();

            // Add source with generateId for hover state management
            map.addSource('municipalities', {
                type: 'geojson',
                data: geojson,
                generateId: true,
            });

            // Choropleth fill layer — inserted below basemap labels
            var fillExpr = currentMode === 'affluenza'
                ? affluenzaFillExpression()
                : risultatiFillExpression();

            map.addLayer({
                id: 'choropleth-fill',
                type: 'fill',
                source: 'municipalities',
                paint: {
                    'fill-color': fillExpr,
                    'fill-opacity': [
                        'case',
                        ['boolean', ['feature-state', 'hover'], false],
                        0.95,
                        0.85
                    ],
                },
            }, firstLabelLayer);

            // Choropleth outline layer — also below basemap labels
            map.addLayer({
                id: 'choropleth-outline',
                type: 'line',
                source: 'municipalities',
                paint: {
                    'line-color': [
                        'case',
                        ['boolean', ['feature-state', 'hover'], false],
                        '#000',
                        '#333'
                    ],
                    'line-width': [
                        'case',
                        ['boolean', ['feature-state', 'hover'], false],
                        2,
                        0.3
                    ],
                    'line-opacity': 0.6,
                },
            }, firstLabelLayer);

            // Hover interaction
            map.on('mousemove', 'choropleth-fill', function (e) {
                if (e.features.length > 0) {
                    if (hoveredFeatureId !== null) {
                        map.setFeatureState(
                            { source: 'municipalities', id: hoveredFeatureId },
                            { hover: false }
                        );
                    }
                    hoveredFeatureId = e.features[0].id;
                    map.setFeatureState(
                        { source: 'municipalities', id: hoveredFeatureId },
                        { hover: true }
                    );
                    map.getCanvas().style.cursor = 'pointer';
                }
            });

            map.on('mouseleave', 'choropleth-fill', function () {
                if (hoveredFeatureId !== null) {
                    map.setFeatureState(
                        { source: 'municipalities', id: hoveredFeatureId },
                        { hover: false }
                    );
                }
                hoveredFeatureId = null;
                map.getCanvas().style.cursor = '';
            });

            // Click popup
            map.on('click', 'choropleth-fill', function (e) {
                if (!e.features.length) return;
                var p = e.features[0].properties;
                var html = buildPopupHTML(p);

                if (currentPopup) currentPopup.remove();
                currentPopup = new maplibregl.Popup({ maxWidth: '280px' })
                    .setLngLat(e.lngLat)
                    .setHTML(html)
                    .addTo(map);
            });

            updateLegend();
        } catch (e) {
            console.error('Failed to load GeoJSON:', e);
            document.getElementById('map').innerHTML =
                '<p style="padding:3rem;color:#666;">GeoJSON non disponibile.</p>';
        }
    });
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
