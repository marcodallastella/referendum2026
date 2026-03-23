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

// Risultati: RdBu diverging scale (colorblind-safe: red=No, blue=Sì).
// Avoids red/green which is indistinguishable for ~8% of male users (deuteranopia).
const RISULTATI_BREAKS = [0, 20, 35, 45, 50, 55, 65, 80, 100];
const RISULTATI_COLORS = [
    '#b2182b', '#d6604d', '#f4a582', '#fddbc7',
    '#f7f7f7',
    '#d1e5f0', '#92c5de', '#4393c3', '#2166ac'
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
// Security: HTML escaping for API-sourced strings inserted into innerHTML
// ---------------------------------------------------------------------------

function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
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
// Tug-of-war results bar
// ---------------------------------------------------------------------------

function renderResultsBarHTML(percSi, percNo, size) {
    const hasData = percSi != null && percNo != null;
    const siW = hasData ? percSi : 50;
    const noW = hasData ? (100 - percSi) : 50;
    const barCls = 'tow-bar tow-bar--' + size + (hasData ? '' : ' tow-bar--empty');

    let html = '';

    // Hero bar: show labels and percentages above
    if (size === 'hero') {
        html += '<div class="bar-header">';
        if (hasData) {
            html += '<div class="bar-side bar-side-si">';
            html += '<span class="bar-side-label">S\u00ec</span>';
            html += '<span class="bar-side-perc">' + fmtPerc(percSi) + '</span>';
            html += '</div>';
            html += '<div class="bar-side bar-side-no">';
            html += '<span class="bar-side-label">No</span>';
            html += '<span class="bar-side-perc">' + fmtPerc(percNo) + '</span>';
            html += '</div>';
        }
        html += '</div>';
    }

    // The bar
    html += '<div class="' + barCls + '">';
    html += '<div class="tow-si" style="width:' + siW + '%"></div>';
    html += '<div class="tow-no" style="width:' + noW + '%"></div>';
    if (!hasData && size !== 'mini') {
        html += '<span class="tow-empty-label">In attesa dei risultati</span>';
    }
    html += '</div>';

    return html;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
    try {
        // --- CACHE BUSTER: Forces the browser to get the newest files ---
        const cb = '?t=' + new Date().getTime();
        const [natResp, regResp] = await Promise.all([
            fetch('data/national.json' + cb),
            fetch('data/regions.json' + cb),
        ]);
        if (!natResp.ok) throw new Error('national.json: HTTP ' + natResp.status);
        if (!regResp.ok) throw new Error('regions.json: HTTP ' + regResp.status);
        nationalData = await natResp.json();
        regionsData = await regResp.json();

        updateSummaryPanel();
        buildRegionsTable();
        loadMap();
    } catch (e) {
        console.error('Failed to load data:', e);
        document.getElementById('summary').innerHTML =
            '<p style="padding:2rem;color:#c0392b;">Errore nel caricamento dei dati. Riprova più tardi.</p>';
    }
}

// ---------------------------------------------------------------------------
// Summary panel
// ---------------------------------------------------------------------------

function updateSummaryPanel() {
    if (!nationalData) return;
    const d = nationalData;

    // --- Affluenza elements ---
    document.getElementById('nat-affluenza').textContent = fmtPerc(d.affluenza.best_perc);

    document.getElementById('stats-inline').textContent =
        'Elettori: ' + fmtNum(d.elettori) + ' \u00b7 Votanti: ' + fmtNum(d.affluenza.best_votanti);

    // Progression
    const progEl = document.getElementById('progression');
    const parts = d.affluenza.snapshots
        .filter(s => s.votanti > 0)
        .map(s => 'ore ' + s.label + ' ' + fmtPerc(s.perc));
    progEl.textContent = parts.join(' \u2192 ');

    // --- Results bar (shared data for both modes) ---
    const percSi = d.has_results ? d.results.perc_si : null;
    const percNo = d.has_results ? d.results.perc_no : null;

    // Compact bar in affluenza section
    document.getElementById('hero-bar-affluenza').innerHTML =
        renderResultsBarHTML(percSi, percNo, 'compact');

    // Hero bar in risultati section
    document.getElementById('hero-bar-risultati').innerHTML =
        renderResultsBarHTML(percSi, percNo, 'hero');

    // --- Risultati secondary info ---
    const sezioniEl = document.getElementById('bar-sezioni');
    if (d.has_results) {
        if (d.results.sezioni_scrutinate != null && d.results.sezioni_totali != null && d.results.sezioni_totali > 0) {
            const percSez = d.results.sezioni_scrutinate / d.results.sezioni_totali * 100;
            sezioniEl.textContent = 'Sezioni scrutinate: ' + fmtNum(d.results.sezioni_scrutinate) +
                ' su ' + fmtNum(d.results.sezioni_totali) + ' (' + fmtPerc(percSez) + ')';
        } else {
            sezioniEl.textContent = 'Scrutinio in corso';
        }
    } else {
        sezioniEl.textContent = 'Scrutinio non ancora iniziato';
    }

    const secEl = document.getElementById('risultati-secondary');
    if (d.has_results) {
        const secParts = ['Voti validi: ' + fmtNum(d.results.validi)];
        if (d.results.bianche != null) secParts.push('Schede bianche: ' + fmtNum(d.results.bianche));
        if (d.results.nulle != null) secParts.push('Schede nulle: ' + fmtNum(d.results.nulle));
        secEl.textContent = secParts.join(' \u00b7 ');
    } else {
        secEl.textContent = '';
    }

    // Affluenza summary line in risultati mode
    document.getElementById('affluenza-summary-line').textContent =
        'Affluenza: ' + fmtPerc(d.affluenza.best_perc) +
        ' (' + fmtNum(d.affluenza.best_votanti) + ' su ' + fmtNum(d.elettori) + ')';

    // Last update timestamp: use actual data scrape time from national.json, not browser time
    const updateEl = document.getElementById('last-update');
    if (d.fetched_at) {
        try {
            const ts = new Date(d.fetched_at).toLocaleString('it-IT', {
                day: 'numeric', month: 'long', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
                timeZone: 'Europe/Rome',
            });
            updateEl.textContent = 'Dati aggiornati: ' + ts;
        } catch (_) {
            updateEl.textContent = 'Dati aggiornati: ' + d.fetched_at;
        }
    } else {
        updateEl.textContent = '';
    }
}

// ---------------------------------------------------------------------------
// Mode toggle
// ---------------------------------------------------------------------------

function setMode(mode) {
    currentMode = mode;

    const btnAff = document.getElementById('btn-affluenza');
    const btnRis = document.getElementById('btn-risultati');
    btnAff.classList.toggle('active', mode === 'affluenza');
    btnRis.classList.toggle('active', mode === 'risultati');
    btnAff.setAttribute('aria-pressed', mode === 'affluenza' ? 'true' : 'false');
    btnRis.setAttribute('aria-pressed', mode === 'risultati' ? 'true' : 'false');

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
    // escapeHtml() prevents XSS from API-sourced strings (municipality/province names)
    let html = '<div class="popup-title">' + escapeHtml(p.comune) + '</div>';
    html += '<div class="popup-subtitle">' + escapeHtml(p.provincia) + ' \u2014 ' + escapeHtml(p.regione) + '</div>';

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
        html += '<div class="popup-section"><div class="popup-section-title">Risultati (dati provinciali)</div>';
        html += '<div class="popup-row"><span>S\u00ec</span><span class="popup-val" style="color:var(--color-si)">' + fmtPerc(p.perc_si) + '</span></div>';
        html += '<div class="popup-row"><span>No</span><span class="popup-val" style="color:var(--color-no)">' + fmtPerc(p.perc_no) + '</span></div>';
        html += '</div>';
    }

    return html;
}

async function loadMap() {
    map = new maplibregl.Map({
        container: 'map',
        style: 'https://api.maptiler.com/maps/streets-v2/style.json?key=i42Day2QPvdGffgVmXQI',
        center: [12.5, 42.5],
        zoom: 5.5,
        minZoom: 5,
        maxZoom: 12,
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('error', function (e) {
        console.error('Map error:', e.error);
    });

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
            if (!resp.ok) throw new Error('italy.geojson: HTTP ' + resp.status);
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

function buildRegionsTable() {
    if (!regionsData) return;

    const thead = document.getElementById('regions-thead-row');
    const tbody = document.getElementById('regions-tbody');

    let columns;
    if (currentMode === 'affluenza') {
        columns = [
            { key: 'regione', label: 'Regione', fmt: v => v },
            { key: 'elettori', label: 'Elettori', fmt: fmtNum },
            { key: 'best_votanti', label: 'Votanti', fmt: fmtNum },
            { key: 'best_perc', label: 'Affluenza %', fmt: fmtPerc },
        ];
    } else {
        columns = [
            { key: 'regione', label: 'Regione', fmt: v => v },
            { key: 'elettori', label: 'Elettori', fmt: fmtNum },
            { key: 'bar', label: 'S\u00ec/No', sortKey: 'perc_si', fmt: null },
            { key: 'perc_si', label: '% S\u00ec', fmt: fmtPerc },
            { key: 'perc_no', label: '% No', fmt: fmtPerc },
            { key: 'best_perc', label: 'Affluenza %', fmt: fmtPerc },
        ];
    }

    // Build header
    thead.innerHTML = columns.map(c => {
        const sk = c.sortKey || c.key;
        return `<th data-col="${sk}" onclick="sortTable('${sk}')">${c.label}<span class="sort-arrow">${sortCol === sk ? (sortAsc ? '\u25B2' : '\u25BC') : ''}</span></th>`;
    }).join('');

    // Flatten data for table
    let rows = regionsData.map(r => ({
        regione: r.regione,
        elettori: r.elettori,
        best_votanti: r.affluenza.best_votanti,
        best_perc: r.affluenza.best_perc,
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

    // Build body
    tbody.innerHTML = rows.map(r =>
        '<tr>' + columns.map(c => {
            if (c.key === 'bar') {
                return '<td class="cell-mini-bar">' +
                    renderResultsBarHTML(r.perc_si, r.perc_no, 'mini') + '</td>';
            }
            return `<td>${c.fmt(r[c.key])}</td>`;
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
