/* ──────────────────────────────────────────────────────────────
   SoundIntelligence Studio Pro · Apple Client Engine
   Multi-harmonic visualizer, studio parametric canvas & WebSocket sync
   ────────────────────────────────────────────────────────────── */

// ── Application State ─────────────────────────────────────────
let ws = null;
let presets = {};
let activeMode = 'auto';
let currentPresetId = null;

// Visualizer Configuration (48 High-Density Radial Bands)
const NUM_VIZ_BARS = 48;
const targetBars  = new Float32Array(NUM_VIZ_BARS);
const currentBars = new Float32Array(NUM_VIZ_BARS);
let peakEnergy = 0.01;
let currentAccent = '#0A84FF';
let currentAccentRgb = '10, 132, 255';

// Band Keys
const BAND_KEYS = ['sub_bass', 'bass', 'low_mid', 'mid', 'high_mid', 'treble'];
let latestSpectral = {};
BAND_KEYS.forEach(k => latestSpectral[k] = 0);

// EQ Curve Engine
let currentEqFilters = null;
let targetEqFilters = null;
let eqAnimProgress = 1;
let eqColor = '#0A84FF';

// Waveform Animation Phase
let wavePhase = 0;

// ── DOM References ───────────────────────────────────────────
const beacon            = document.getElementById('connection-beacon');
const connectionLabel   = document.getElementById('connection-label');
const heroCanvas        = document.getElementById('heroCanvas');
const heroCtx           = heroCanvas ? heroCanvas.getContext('2d') : null;
const eqCanvas          = document.getElementById('eqCanvas');
const eqCtx             = eqCanvas ? eqCanvas.getContext('2d') : null;
const fluidCanvas       = document.getElementById('fluidMeshCanvas');
const fluidCtx          = fluidCanvas ? fluidCanvas.getContext('2d') : null;
const hudHalo           = document.getElementById('hud-halo');
const centerIcon        = document.getElementById('center-icon');
const centerLabel       = document.getElementById('center-label');
const centerConf        = document.getElementById('center-confidence');
const chipIcon          = document.getElementById('chip-icon');
const chipName          = document.getElementById('chip-name');
const predsStack        = document.getElementById('predictions-stack');
const dynamicBarsRack   = document.getElementById('dynamic-bars');
const affinityRow       = document.getElementById('affinity-row');
const modeControl       = document.getElementById('mode-control');
const dwellSlider       = document.getElementById('dwell-slider');
const dwellDisplay      = document.getElementById('dwell-display');
const applyBtn          = document.getElementById('apply-btn');
const timelineEl        = document.getElementById('timeline-scroll');
const timelineEmpty     = document.getElementById('timeline-empty');
const eventCount        = document.getElementById('event-count');
const toastBox          = document.getElementById('toast-container');
const ambientMesh       = document.getElementById('ambient-mesh');
const fpIndicator       = document.getElementById('fp-indicator');
const fpChip            = document.getElementById('fp-chip');
const stripSpace        = document.getElementById('strip-space');
const stripCache        = document.getElementById('strip-cache');

// ── Interactive Fluid Mesh Backdrop ───────────────────────────
const fluidBlobs = [
    { x: 0.25, y: 0.35, r: 420, vx: 0.0006, vy: 0.0008, color: '#0A84FF', baseColor: '#0A84FF' },
    { x: 0.75, y: 0.45, r: 460, vx: -0.0007, vy: 0.0005, color: '#5E5CE6', baseColor: '#5E5CE6' },
    { x: 0.50, y: 0.80, r: 520, vx: 0.0005, vy: -0.0007, color: '#BF5AF2', baseColor: '#BF5AF2' },
    { x: 0.85, y: 0.20, r: 380, vx: -0.0008, vy: 0.0006, color: '#30D158', baseColor: '#30D158' }
];
let mousePos = { x: 0.5, y: 0.5 };

function sizeFluidCanvas() {
    if (!fluidCanvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    fluidCanvas.width = window.innerWidth * dpr;
    fluidCanvas.height = window.innerHeight * dpr;
    if (fluidCtx) {
        fluidCtx.setTransform(1, 0, 0, 1, 0, 0);
        fluidCtx.scale(dpr, dpr);
    }
}

function drawFluidMesh() {
    if (!fluidCtx || !fluidCanvas) return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (w === 0 || h === 0) return;

    fluidCtx.clearRect(0, 0, w, h);

    // Audio-reactive expansion factor
    const audioBoost = 1 + (peakEnergy * 0.4);

    fluidBlobs.forEach((blob, idx) => {
        blob.x += blob.vx;
        blob.y += blob.vy;
        if (blob.x < 0.1 || blob.x > 0.9) blob.vx *= -1;
        if (blob.y < 0.1 || blob.y > 0.9) blob.vy *= -1;

        // Subtle attraction to pointer
        const dx = mousePos.x - blob.x;
        const dy = mousePos.y - blob.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 0.4) {
            blob.x += dx * 0.002;
            blob.y += dy * 0.002;
        }

        const bx = blob.x * w;
        const by = blob.y * h;
        const br = blob.r * audioBoost;

        const grad = fluidCtx.createRadialGradient(bx, by, br * 0.05, bx, by, br);
        const col = idx === 0 ? currentAccent : blob.color;
        grad.addColorStop(0, hexToRgba(col, 0.22));
        grad.addColorStop(0.5, hexToRgba(col, 0.07));
        grad.addColorStop(1, 'transparent');

        fluidCtx.fillStyle = grad;
        fluidCtx.beginPath();
        fluidCtx.arc(bx, by, br, 0, Math.PI * 2);
        fluidCtx.fill();
    });
}

// ── High-DPI Canvas Sizing ────────────────────────────────────
function sizeCanvas(canvas) {
    if (!canvas || !canvas.parentElement) return;
    const r = canvas.parentElement.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = r.width * dpr;
    canvas.height = r.height * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
}

function sizeAll() {
    sizeCanvas(heroCanvas);
    sizeCanvas(eqCanvas);
    sizeFluidCanvas();
}
window.addEventListener('resize', sizeAll);

// ── WebSocket Client ──────────────────────────────────────────
function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        if (beacon) beacon.classList.add('live');
        if (connectionLabel) connectionLabel.textContent = 'STUDIO CONNECTED';
        toast('Connected to Studio Engine', 'success');
    };

    ws.onmessage = e => {
        try {
            const msg = JSON.parse(e.data);
            if (msg.type === 'init') onInit(msg);
            if (msg.type === 'state') onState(msg.state);
        } catch (err) {
            console.error('[WS Parse Error]', err);
        }
    };

    ws.onclose = () => {
        if (beacon) beacon.classList.remove('live');
        if (connectionLabel) connectionLabel.textContent = 'DISCONNECTED';
        toast('Engine disconnected — Reconnecting…', 'error');
        setTimeout(connect, 2000);
    };

    ws.onerror = () => {
        if (beacon) beacon.classList.remove('live');
    };
}

function onInit(msg) {
    presets = msg.presets || {};
    buildModeButtons();
    if (msg.min_dwell_seconds && dwellSlider && dwellDisplay) {
        dwellSlider.value = msg.min_dwell_seconds;
        dwellDisplay.textContent = parseFloat(msg.min_dwell_seconds).toFixed(1) + 's';
    }
    if (msg.manual_override) setActiveMode(msg.manual_override);
}

// ── Concentric Liquid Glass Tab Bar ───────────────────────────
const miniArtIcon   = document.getElementById('mini-art-icon');
const miniTitle     = document.getElementById('mini-title');
const miniSubtitle  = document.getElementById('mini-subtitle');
const btnToggleEngine = document.getElementById('btn-toggle-engine');
const btnNextPreset   = document.getElementById('btn-next-preset');

function buildModeButtons() {
    if (!modeControl) return;
    while (modeControl.children.length > 1) modeControl.lastChild.remove();

    for (const [id, p] of Object.entries(presets)) {
        const btn = document.createElement('button');
        btn.className = 'dock-tab-item';
        btn.dataset.value = id;
        btn.innerHTML = `
            <div class="tab-icon-wrap">${p.icon}</div>
            <span class="tab-label">${p.name}</span>
        `;
        modeControl.appendChild(btn);
    }

    modeControl.onclick = e => {
        const btn = e.target.closest('.dock-tab-item');
        if (!btn) return;
        setActiveMode(btn.dataset.value);
    };
}

function setActiveMode(val) {
    activeMode = val;
    if (!modeControl) return;
    modeControl.querySelectorAll('.dock-tab-item').forEach(b => {
        b.classList.toggle('active', b.dataset.value === val);
    });
}

// Miniplayer Controls
if (btnNextPreset) {
    btnNextPreset.onclick = () => {
        const keys = Object.keys(presets);
        if (!keys.length) return;
        const currIdx = keys.indexOf(activeMode);
        const nextKey = keys[(currIdx + 1) % keys.length];
        setActiveMode(nextKey);
        toast(`Selected Profile: ${presets[nextKey].name}`, 'success');
    };
}

if (btnToggleEngine) {
    btnToggleEngine.onclick = () => {
        setActiveMode(activeMode === 'auto' ? Object.keys(presets)[0] || 'auto' : 'auto');
        toast(`Engine Mode: ${activeMode === 'auto' ? 'Auto AI' : 'Manual Lock'}`, 'success');
    };
}

// ── State Dispatcher ──────────────────────────────────────────
function onState(s) {
    if (!s) return;

    // 1. Spectral Data
    if (s.spectral) {
        latestSpectral = s.spectral;
        mapBandsToVizBars();
    }

    // 2. Predictions
    renderPredictions(s.ml_predictions || []);

    // 3. Dynamic Gain Rider
    if (s.dynamic_adjustments) {
        renderDynamicBars(s.dynamic_adjustments);
    }

    // 4. Profile Affinity
    renderAffinity(s.scores || {}, s.candidate);

    // 5. Active Profile Change
    const pid = s.current_preset;
    if (pid && presets[pid] && pid !== currentPresetId) {
        currentPresetId = pid;
        const p = presets[pid];
        setThemeColor(p.color);

        if (centerIcon) centerIcon.textContent = p.icon;
        if (centerLabel) centerLabel.textContent = p.name;
        if (chipIcon) chipIcon.textContent = p.icon;
        if (chipName) chipName.textContent = p.name;
        if (stripSpace) stripSpace.textContent = `${p.name} Space`;
        if (miniArtIcon) miniArtIcon.textContent = p.icon;
        if (miniTitle) miniTitle.textContent = `${p.name} DSP`;

        morphEqCurve(p.filters, p.color);
        toast(`Acoustic Profile → ${p.name}`, 'success');
    }

    // 6. Confidence readout
    if (s.ml_predictions && s.ml_predictions.length > 0) {
        const top = s.ml_predictions[0];
        if (centerConf) centerConf.textContent = `${top.class_name} · ${(top.confidence * 100).toFixed(0)}% Confidence`;
        if (miniSubtitle) miniSubtitle.textContent = `Neural Match: ${top.class_name} (${(top.confidence * 100).toFixed(0)}%)`;
    }

    // 7. Fingerprint Cache Status
    if (fpChip && stripCache) {
        if (s.is_cached) {
            fpChip.textContent = 'Instant Lock';
            fpChip.style.background = 'rgba(48, 209, 88, 0.2)';
            fpChip.style.color = '#30D158';
            stripCache.textContent = 'Instant Recall (Cached)';
            stripCache.className = 'strip-value green';
        } else {
            fpChip.textContent = 'Analyzing';
            fpChip.style.background = 'rgba(255,255,255,0.08)';
            fpChip.style.color = '#ffffff';
            stripCache.textContent = 'Learning Signature…';
            stripCache.className = 'strip-value';
        }
    }

    // 8. Session Timeline
    renderTimeline(s.history || []);
}

// ── Apple Dynamic Theme Colors ────────────────────────────────
function setThemeColor(hex) {
    currentAccent = hex;
    const r = document.documentElement;
    r.style.setProperty('--accent', hex);

    const rgb = hexToRgbValues(hex);
    if (rgb) {
        currentAccentRgb = `${rgb.r}, ${rgb.g}, ${rgb.b}`;
        r.style.setProperty('--accent-rgb', currentAccentRgb);
        r.style.setProperty('--accent-glow', `rgba(${currentAccentRgb}, 0.35)`);
        r.style.setProperty('--accent-dim', `rgba(${currentAccentRgb}, 0.14)`);
    }

    if (hudHalo) {
        hudHalo.style.background = `radial-gradient(circle, rgba(${currentAccentRgb}, 0.45) 0%, transparent 70%)`;
    }
}

function hexToRgbValues(hex) {
    const clean = hex.replace('#', '');
    const num = parseInt(clean, 16);
    if (isNaN(num)) return null;
    return {
        r: (num >> 16) & 255,
        g: (num >> 8) & 255,
        b: num & 255
    };
}

function hexToRgba(hex, a) {
    const rgb = hexToRgbValues(hex);
    if (!rgb) return `rgba(10, 132, 255, ${a})`;
    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${a})`;
}

// ── Gaussian Band Spreading ───────────────────────────────────
function mapBandsToVizBars() {
    const vals = BAND_KEYS.map(k => latestSpectral[k] || 0);
    const mx = Math.max(...vals);
    peakEnergy = Math.max(mx, peakEnergy * 0.992);
    const scale = Math.max(peakEnergy, 0.001);

    for (let i = 0; i < NUM_VIZ_BARS; i++) {
        const pos = (i / NUM_VIZ_BARS) * vals.length;
        let value = 0;
        let weight = 0;
        for (let b = 0; b < vals.length; b++) {
            const dist = Math.abs(pos - (b + 0.5));
            const w = Math.exp(-dist * dist * 1.8);
            value += vals[b] * w;
            weight += w;
        }
        targetBars[i] = (value / weight) / scale;
    }
}

// ── Predictions Render ────────────────────────────────────────
function renderPredictions(preds) {
    if (!predsStack || !preds.length) return;
    predsStack.innerHTML = '';
    preds.slice(0, 4).forEach((p, i) => {
        const pct = (p.confidence * 100).toFixed(0);
        const row = document.createElement('div');
        row.className = 'pred-row';
        row.innerHTML = `
            <span class="pred-rank">0${i + 1}</span>
            <span class="pred-name">${p.class_name}</span>
            <div class="pred-track">
                <div class="pred-fill" style="width:${pct}%;background:linear-gradient(90deg, var(--accent), var(--apple-purple))"></div>
            </div>
            <span class="pred-pct">${pct}%</span>`;
        predsStack.appendChild(row);
    });
}

// ── Dynamic Gain Rider Render ─────────────────────────────────
function renderDynamicBars(adjustments) {
    if (!dynamicBarsRack) return;

    if (!dynamicBarsRack.children.length) {
        BAND_KEYS.forEach(k => {
            const col = document.createElement('div');
            col.className = 'dyn-bar-col';
            col.innerHTML = `
                <span class="dyn-db-label" id="db-${k}">0.0</span>
                <div class="dyn-bar-track">
                    <div class="dyn-bar-fill" id="dyn-${k}" style="bottom: 50%; height: 0%"></div>
                </div>
                <span class="dyn-bar-label">${k.replace('_', ' ').slice(0, 4)}</span>
            `;
            dynamicBarsRack.appendChild(col);
        });
    }

    BAND_KEYS.forEach(k => {
        const gain = adjustments[k] || 0;
        const fill = document.getElementById(`dyn-${k}`);
        const lbl = document.getElementById(`db-${k}`);
        if (!fill || !lbl) return;

        lbl.textContent = gain > 0 ? `+${gain.toFixed(1)}` : gain.toFixed(1);
        lbl.style.color = gain === 0 ? 'var(--text-muted)' : (gain < 0 ? '#FF453A' : '#30D158');

        const pct = Math.min((Math.abs(gain) / 3.0) * 50, 50);
        if (gain < 0) {
            fill.style.bottom = `${50 - pct}%`;
            fill.style.height = `${pct}%`;
            fill.style.background = '#FF453A';
            fill.style.boxShadow = '0 0 10px rgba(255, 69, 58, 0.6)';
        } else if (gain > 0) {
            fill.style.bottom = '50%';
            fill.style.height = `${pct}%`;
            fill.style.background = '#30D158';
            fill.style.boxShadow = '0 0 10px rgba(48, 209, 88, 0.6)';
        } else {
            fill.style.height = '0%';
        }
    });
}

// ── Affinity Matrix Render ────────────────────────────────────
function renderAffinity(scores, candidate) {
    if (!affinityRow || !Object.keys(scores).length) return;
    affinityRow.innerHTML = '';
    for (const [id, score] of Object.entries(scores)) {
        const p = presets[id];
        if (!p) continue;
        const isTarget = id === candidate;
        const col = isTarget ? p.color : 'rgba(255,255,255,0.18)';
        const item = document.createElement('div');
        item.className = 'affinity-item';
        item.innerHTML = `
            <div class="affinity-bar-track">
                <div class="affinity-bar-fill" style="height:${Math.max(score, 6)}%;background:${col}"></div>
            </div>
            <span class="affinity-icon" title="${p.name}">${p.icon}</span>
            <span class="affinity-score">${Math.round(score)}</span>`;
        affinityRow.appendChild(item);
    }
}

// ── Studio Parametric EQ Spline Canvas ────────────────────────
function morphEqCurve(filters, color) {
    if (currentEqFilters) {
        targetEqFilters = filters;
        eqColor = color;
        eqAnimProgress = 0;
    } else {
        currentEqFilters = filters;
        targetEqFilters = filters;
        eqColor = color;
        eqAnimProgress = 1;
    }
}

function drawEqCurve() {
    if (!eqCtx || !eqCanvas) return;
    const c = eqCtx;
    const r = eqCanvas.parentElement.getBoundingClientRect();
    const w = r.width;
    const h = r.height;
    if (w === 0 || h === 0) return;

    c.clearRect(0, 0, w, h);
    if (!currentEqFilters) return;

    if (eqAnimProgress < 1) {
        eqAnimProgress = Math.min(1, eqAnimProgress + 0.045);
    }
    const t = easeOutQuint(eqAnimProgress);

    const filters = targetEqFilters.map((tf, i) => {
        if (currentEqFilters[i]) {
            const cf = currentEqFilters[i];
            return [tf[0], cf[1] + (tf[1] - cf[1]) * t, tf[2]];
        }
        return tf;
    });

    if (eqAnimProgress >= 1) currentEqFilters = targetEqFilters;

    // Grid lines
    c.strokeStyle = 'rgba(255, 255, 255, 0.04)';
    c.lineWidth = 1;
    for (let i = 1; i <= 4; i++) {
        const y = (h / 5) * i;
        c.beginPath();
        c.moveTo(0, y);
        c.lineTo(w, y);
        c.stroke();
    }

    // Zero dB center baseline
    c.strokeStyle = 'rgba(255, 255, 255, 0.12)';
    c.setLineDash([4, 4]);
    c.beginPath();
    c.moveTo(0, h / 2);
    c.lineTo(w, h / 2);
    c.stroke();
    c.setLineDash([]);

    // Compute logarithmic points
    const points = filters.map(f => ({
        x: Math.max(0, Math.min(w, (Math.log10(f[0] / 20) / Math.log10(20000 / 20)) * w)),
        y: h / 2 - (f[1] * (h / 26)),
        gain: f[1],
        freq: f[0]
    })).sort((a, b) => a.x - b.x);

    // Build smooth cubic path
    const path = new Path2D();
    path.moveTo(0, h / 2);

    if (points.length) {
        path.bezierCurveTo(points[0].x * 0.5, h / 2, points[0].x * 0.8, points[0].y, points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
            const prev = points[i - 1];
            const curr = points[i];
            const cx = (prev.x + curr.x) / 2;
            path.bezierCurveTo(cx, prev.y, cx, curr.y, curr.x, curr.y);
        }
        const last = points[points.length - 1];
        path.bezierCurveTo(last.x + (w - last.x) * 0.5, last.y, w * 0.95, h / 2, w, h / 2);
    } else {
        path.lineTo(w, h / 2);
    }

    // Glowing Fill Gradient
    const fillPath = new Path2D(path);
    fillPath.lineTo(w, h);
    fillPath.lineTo(0, h);
    fillPath.closePath();

    const grad = c.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, hexToRgba(eqColor, 0.28));
    grad.addColorStop(0.55, hexToRgba(eqColor, 0.06));
    grad.addColorStop(1, 'transparent');
    c.fillStyle = grad;
    c.fill(fillPath);

    // Stroke curve
    c.shadowColor = eqColor;
    c.shadowBlur = 14;
    c.strokeStyle = eqColor;
    c.lineWidth = 2.8;
    c.stroke(path);
    c.shadowBlur = 0;

    // Filter nodes
    points.forEach(p => {
        c.beginPath();
        c.arc(p.x, p.y, 5, 0, Math.PI * 2);
        c.fillStyle = '#ffffff';
        c.shadowColor = eqColor;
        c.shadowBlur = 10;
        c.fill();
        c.shadowBlur = 0;
    });
}

function easeOutQuint(x) {
    return 1 - Math.pow(1 - x, 5);
}

// ── Liquid Dynamic iOS Acoustic Canvas ────────────────────────
const liquidParticles = Array.from({ length: 24 }, (_, i) => ({
    angle: (i / 24) * Math.PI * 2,
    radiusOffset: Math.random() * 20 - 10,
    speed: 0.008 + Math.random() * 0.012,
    size: 2 + Math.random() * 3,
    alpha: 0.3 + Math.random() * 0.5
}));

function drawCircularViz() {
    if (!heroCtx || !heroCanvas) return;
    const c = heroCtx;
    const r = heroCanvas.parentElement.getBoundingClientRect();
    const w = r.width;
    const h = r.height;
    if (w === 0 || h === 0) return;

    c.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;
    const innerR = Math.min(w, h) * 0.22;
    const maxBar = Math.min(w, h) * 0.28;
    const barAngle = (Math.PI * 2) / NUM_VIZ_BARS;

    wavePhase += 0.024;

    // Smooth spring physics lerp
    for (let i = 0; i < NUM_VIZ_BARS; i++) {
        currentBars[i] += (targetBars[i] - currentBars[i]) * 0.24;
    }

    // 1. Fluid Ambient Concentric Waves
    for (let ring = 1; ring <= 3; ring++) {
        const ringR = innerR + (ring * 34) + (Math.sin(wavePhase + ring * 1.5) * 4);
        c.beginPath();
        c.arc(cx, cy, ringR, 0, Math.PI * 2);
        c.strokeStyle = `rgba(255, 255, 255, ${0.035 / ring})`;
        c.lineWidth = 1.2;
        c.stroke();
    }

    // 2. Liquid Outer Spline Perimeter
    const outerPoints = [];
    for (let i = 0; i < NUM_VIZ_BARS; i++) {
        const val = Math.max(currentBars[i], 0.03);
        const barH = val * maxBar;
        const angle = (i * barAngle) - Math.PI / 2;
        const rad = innerR + barH;
        outerPoints.push({
            x: cx + Math.cos(angle) * rad,
            y: cy + Math.sin(angle) * rad
        });
    }

    if (outerPoints.length > 2) {
        c.beginPath();
        c.moveTo((outerPoints[0].x + outerPoints[outerPoints.length - 1].x) / 2, (outerPoints[0].y + outerPoints[outerPoints.length - 1].y) / 2);
        for (let i = 0; i < outerPoints.length; i++) {
            const next = outerPoints[(i + 1) % outerPoints.length];
            const mx = (outerPoints[i].x + next.x) / 2;
            const my = (outerPoints[i].y + next.y) / 2;
            c.quadraticCurveTo(outerPoints[i].x, outerPoints[i].y, mx, my);
        }
        c.closePath();

        // Liquid Plasma Fill
        const plasmaGrad = c.createRadialGradient(cx, cy, innerR * 0.5, cx, cy, innerR + maxBar);
        plasmaGrad.addColorStop(0, hexToRgba(currentAccent, 0.28));
        plasmaGrad.addColorStop(0.5, hexToRgba(currentAccent, 0.08));
        plasmaGrad.addColorStop(1, 'transparent');
        c.fillStyle = plasmaGrad;
        c.fill();

        // Liquid Membrane Glow Stroke
        c.strokeStyle = hexToRgba(currentAccent, 0.45);
        c.lineWidth = 1.8;
        c.shadowColor = currentAccent;
        c.shadowBlur = 18;
        c.stroke();
        c.shadowBlur = 0;
    }

    // 3. High-Density Radial Liquid Pillars
    const barWidth = barAngle * 0.42;
    for (let i = 0; i < NUM_VIZ_BARS; i++) {
        const val = Math.max(currentBars[i], 0.025);
        const barH = val * maxBar;
        const angle = (i * barAngle) - Math.PI / 2;

        const r1 = innerR;
        const r2 = innerR + barH;
        const a1 = angle - barWidth / 2;
        const a2 = angle + barWidth / 2;

        const ratio = i / NUM_VIZ_BARS;
        let barColor;
        if (ratio < 0.33) {
            barColor = lerpColor('#BF5AF2', currentAccent, ratio / 0.33);
        } else if (ratio < 0.66) {
            barColor = currentAccent;
        } else {
            barColor = lerpColor(currentAccent, '#30D158', (ratio - 0.66) / 0.34);
        }

        c.beginPath();
        c.arc(cx, cy, r1, a1, a2);
        c.arc(cx, cy, r2, a2, a1, true);
        c.closePath();
        c.fillStyle = barColor;
        c.fill();
    }

    // 4. Orbiting Liquid Energy Particles
    liquidParticles.forEach(p => {
        p.angle += p.speed;
        const particleR = innerR + (maxBar * 0.8) + p.radiusOffset + Math.sin(wavePhase * 2 + p.angle) * 8;
        const px = cx + Math.cos(p.angle) * particleR;
        const py = cy + Math.sin(p.angle) * particleR;

        c.beginPath();
        c.arc(px, py, p.size, 0, Math.PI * 2);
        c.fillStyle = hexToRgba(currentAccent, p.alpha);
        c.shadowColor = currentAccent;
        c.shadowBlur = 10;
        c.fill();
        c.shadowBlur = 0;
    });

    // 5. Liquid Core Droplet Breathing
    const corePulse = Math.sin(wavePhase * 1.8) * 4;
    c.beginPath();
    c.arc(cx, cy, innerR + corePulse, 0, Math.PI * 2);
    c.strokeStyle = hexToRgba(currentAccent, 0.3);
    c.lineWidth = 2;
    c.stroke();
}

function lerpColor(a, b, t) {
    const ca = hexToRgbValues(a) || { r: 10, g: 132, b: 255 };
    const cb = hexToRgbValues(b) || { r: 10, g: 132, b: 255 };
    const r = Math.round(ca.r + (cb.r - ca.r) * t);
    const g = Math.round(ca.g + (cb.g - ca.g) * t);
    const bl = Math.round(ca.b + (cb.b - ca.b) * t);
    return `rgb(${r}, ${g}, ${bl})`;
}

// ── Timeline Render ───────────────────────────────────────────
const seenEvents = new Set();
function renderTimeline(history) {
    if (!timelineEl || !history.length) return;

    let added = false;
    history.forEach(ev => {
        const key = ev.timestamp.toFixed(2);
        if (seenEvents.has(key)) return;
        seenEvents.add(key);
        added = true;

        if (timelineEmpty) timelineEmpty.style.display = 'none';

        const p = presets[ev.preset];
        const color = p ? p.color : '#0A84FF';
        const name  = p ? `${p.icon} ${p.name}` : ev.preset;

        const date = new Date(ev.timestamp * 1000);
        const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        const item = document.createElement('div');
        item.className = 'tl-event';
        item.style.borderLeftColor = color;
        item.innerHTML = `
            <span class="tl-time">${timeStr}</span>
            <div class="tl-body">
                <span class="tl-preset" style="color:${color}">${name}</span>
                <span class="tl-reason">Trigger: ${ev.top_class}</span>
            </div>`;
        timelineEl.prepend(item);
    });

    if (added && eventCount) {
        eventCount.textContent = `${seenEvents.size} event${seenEvents.size !== 1 ? 's' : ''}`;
    }
}

// ── Control Settings Sync ─────────────────────────────────────
if (dwellSlider && dwellDisplay) {
    dwellSlider.addEventListener('input', () => {
        dwellDisplay.textContent = parseFloat(dwellSlider.value).toFixed(1) + 's';
    });
}

if (applyBtn) {
    applyBtn.addEventListener('click', async () => {
        const btnText = applyBtn.querySelector('.btn-text');
        if (btnText) btnText.textContent = 'Syncing…';

        try {
            const res = await fetch('/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    min_dwell_seconds: parseFloat(dwellSlider ? dwellSlider.value : 6.0),
                    manual_override: activeMode
                })
            });
            if (res.ok) toast('Studio Settings Synchronized', 'success');
        } catch {
            toast('Failed to sync settings', 'error');
        }
        if (btnText) btnText.textContent = 'Sync Configuration';
    });
}

// ── Toast Notifications ───────────────────────────────────────
function toast(msg, type = 'success') {
    if (!toastBox) return;
    const el = document.createElement('div');
    el.className = 'apple-toast';
    const dotColor = type === 'success' ? '#30D158' : '#FF453A';
    el.innerHTML = `<span class="toast-dot" style="background:${dotColor}"></span><span>${msg}</span>`;
    toastBox.appendChild(el);

    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
        el.classList.remove('show');
        setTimeout(() => el.remove(), 450);
    }, 3200);
}

// ── Liquid Parallax, 3D Tilt & Specular Tracking ──────────────
const masterToolbar = document.querySelector('.master-toolbar');
window.addEventListener('scroll', () => {
    if (masterToolbar) {
        if (window.scrollY > 40) {
            masterToolbar.classList.add('scrolled');
        } else {
            masterToolbar.classList.remove('scrolled');
        }
    }
}, { passive: true });

window.addEventListener('mousemove', e => {
    mousePos.x = e.clientX / window.innerWidth;
    mousePos.y = e.clientY / window.innerHeight;

    const xRatio = (mousePos.x - 0.5) * 24;
    const yRatio = (mousePos.y - 0.5) * 24;
    
    if (ambientMesh) {
        ambientMesh.style.transform = `translate(${xRatio * 0.8}px, ${yRatio * 0.8}px)`;
    }
});

// Interactive Physical Glass 3D Tilt
const tiltCards = document.querySelectorAll('.hero-stage, .glass-deck');
tiltCards.forEach(card => {
    card.addEventListener('mousemove', e => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        card.style.setProperty('--mouse-x', `${x}px`);
        card.style.setProperty('--mouse-y', `${y}px`);

        const rx = ((y / rect.height) - 0.5) * -4;
        const ry = ((x / rect.width) - 0.5) * 4;
        card.style.transform = `perspective(1000px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) translateZ(4px)`;
    });

    card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) translateZ(0px)';
    });
});

// Specular highlight tracking (no tilt) for smaller / pill-shaped glass
// surfaces, so light still "catches" the glass under the cursor without
// the 3D rotation looking odd on thin bars and circular buttons.
const glowSurfaces = document.querySelectorAll(
    '.dynamic-capsule, .dock-miniplayer-pill, .dock-tabbar-pill, .fingerprint-indicator'
);
glowSurfaces.forEach(el => {
    el.addEventListener('mousemove', e => {
        const rect = el.getBoundingClientRect();
        el.style.setProperty('--mouse-x', `${e.clientX - rect.left}px`);
        el.style.setProperty('--mouse-y', `${e.clientY - rect.top}px`);
    });
});

// ── 60fps Main Render Loop ────────────────────────────────────
function renderFrame() {
    drawFluidMesh();
    drawCircularViz();
    drawEqCurve();
    requestAnimationFrame(renderFrame);
}

// ── Compact Dynamic Island Mode Toggle ────────────────────────
const btnCompactToggle = document.getElementById('btn-compact-toggle');
function toggleCompactMode(forceState = null) {
    const isCompact = forceState !== null ? forceState : !document.body.classList.contains('compact-mode');
    document.body.classList.toggle('compact-mode', isCompact);
    localStorage.setItem('soundintelligence_compact', isCompact ? '1' : '0');
    sizeAll();
    toast(isCompact ? 'Compact Mini Mode' : 'Studio Pro Mode', 'success');
}

if (btnCompactToggle) {
    btnCompactToggle.addEventListener('click', () => toggleCompactMode());
}

// ── Initialization ────────────────────────────────────────────
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('mode') === 'compact' || localStorage.getItem('soundintelligence_compact') === '1') {
    document.body.classList.add('compact-mode');
}

sizeAll();
requestAnimationFrame(renderFrame);
setTimeout(connect, 200);

