const canvas = document.getElementById('mindmapCanvas');
const ctx = canvas.getContext('2d');
const searchInput = document.getElementById('searchInput');
const resetBtn = document.getElementById('resetBtn');
const addRelBtn = document.getElementById('addRelBtn');
const relModal = document.getElementById('relModal');
const relFrom = document.getElementById('relFrom');
const relTo = document.getElementById('relTo');
const relColor = document.getElementById('relColor');
const relLabel = document.getElementById('relLabel');
const relError = document.getElementById('relError');
const relCancelBtn = document.getElementById('relCancelBtn');
const relSaveBtn = document.getElementById('relSaveBtn');
const relFromDropdown = document.getElementById('relFromDropdown');
const relToDropdown = document.getElementById('relToDropdown');

// Edit-Modal
const ctxMenu = document.getElementById('ctxMenu');
const editModal = document.getElementById('editModal');
const editFrom = document.getElementById('editFrom');
const editTo = document.getElementById('editTo');
const editColor = document.getElementById('editColor');
const editLabel = document.getElementById('editLabel');
const editError = document.getElementById('editError');
const editCancelBtn = document.getElementById('editCancelBtn');
const editSaveBtn = document.getElementById('editSaveBtn');
const editDeleteBtn = document.getElementById('editDeleteBtn');
const zoomInBtn = document.getElementById('zoomInBtn');
const zoomOutBtn = document.getElementById('zoomOutBtn');
const personModal = document.getElementById('personModal');
const personName = document.getElementById('personName');
const personPhotoInput = document.getElementById('personPhotoInput');
const personPortraitPreview = document.getElementById('personPortraitPreview');
const personDeletePhotoBtn = document.getElementById('personDeletePhotoBtn');
const personCancelBtn = document.getElementById('personCancelBtn');
const personSaveBtn = document.getElementById('personSaveBtn');
const personError = document.getElementById('personError');

const COLORS = {
  rot: '#ef4444',
  blau: '#3b82f6',
  orange: '#f59e0b'
};

const state = {
  nodes: [],
  edges: [],
  nodeMap: new Map(),
  activeNode: null,
  hoveredNode: null,
  searchTerm: '',
  viewport: {
    x: 0,
    y: 0,
    scale: 1,
    minScale: 0.25,
    maxScale: 4
  }
};

let dragInfo = null;
let panInfo = null;
let dpr = Math.max(window.devicePixelRatio || 1, 1);

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * dpr);
  canvas.height = Math.floor(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function screenToWorld(point) {
  return {
    x: (point.x - state.viewport.x) / state.viewport.scale,
    y: (point.y - state.viewport.y) / state.viewport.scale
  };
}

function zoomAt(screenPoint, factor) {
  const worldBefore = screenToWorld(screenPoint);
  const nextScale = clamp(
    state.viewport.scale * factor,
    state.viewport.minScale,
    state.viewport.maxScale
  );

  state.viewport.scale = nextScale;
  state.viewport.x = screenPoint.x - worldBefore.x * nextScale;
  state.viewport.y = screenPoint.y - worldBefore.y * nextScale;
}

function hashColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 60% 56%)`;
}

function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0].toUpperCase())
    .join('');
}

function normalizeText(value) {
  return value.trim().toLowerCase();
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function newId(prefix) {
  let max = 0;
  for (const node of state.nodes) {
    if (node.person_id && node.person_id.startsWith(`${prefix}_`)) {
      const n = parseInt(node.person_id.slice(prefix.length + 1), 10);
      if (!isNaN(n) && n > max) max = n;
    }
  }
  for (const edge of state.edges) {
    if (edge.relation_id && edge.relation_id.startsWith(`${prefix}_`)) {
      const n = parseInt(edge.relation_id.slice(prefix.length + 1), 10);
      if (!isNaN(n) && n > max) max = n;
    }
  }
  return `${prefix}_${max + 1}`;
}

// ── Portrait image cache ───────────────────────────
// Maps person_id → HTMLImageElement | 'loading' | 'error'
const imageCache = new Map();

function loadPortrait(personId) {
  if (imageCache.has(personId)) return;
  imageCache.set(personId, 'loading');

  const tryExtensions = (exts) => {
    if (exts.length === 0) {
      // All person-specific extensions failed → try placeholder
      const img = new Image();
      img.onload = () => imageCache.set(personId, img);
      img.onerror = () => imageCache.set(personId, 'error');
      img.src = '/portraits/placeholder.svg';
      return;
    }
    const img = new Image();
    img.onload = () => imageCache.set(personId, img);
    img.onerror = () => tryExtensions(exts.slice(1));
    img.src = `/portraits/${personId}.${exts[0]}`;
  };

  tryExtensions(['jpg', 'jpeg', 'png']);
}

const API = '/api/data';

async function loadData() {
  const response = await fetch(API);
  const data = await response.json();
  const hasSavedPositions = parseData(data.persons || [], data.connections || []);
  initializeLayout(!hasSavedPositions);
  animate();
}

async function persist() {
  const persons = state.nodes.map(n => ({
    person_id:    n.person_id,
    display_name: n.display_name,
    x: Number.isFinite(n.x) ? Number(n.x.toFixed(2)) : null,
    y: Number.isFinite(n.y) ? Number(n.y.toFixed(2)) : null
  }));
  const connections = state.edges.map(e => ({
    relation_id: e.relation_id,
    from_id:     e.from_id,
    to_id:       e.to_id,
    color:       e.color,
    label:       e.label || ''
  }));
  try {
    await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persons, connections })
    });
  } catch (err) {
    console.error('Speichern fehlgeschlagen:', err);
  }
}

function parseData(persons, connections) {
  const positionMap = new Map();

  state.nodes = persons.map((p, index) => {
    const x = toNumber(p.x);
    const y = toNumber(p.y);
    if (x !== null && y !== null) positionMap.set(p.person_id, true);
    return {
      id:           index,
      person_id:    p.person_id,
      display_name: p.display_name,
      x,
      y,
      radius:    28,
      fill:      hashColor(p.person_id),
      labelWidth: 0,
      initials:  initials(p.display_name),
      degree:    0
    };
  });

  state.nodeMap = new Map(state.nodes.map(node => [node.person_id, node]));

  const validConns = connections.filter(
    c => COLORS[c.color] && state.nodeMap.has(c.from_id) && state.nodeMap.has(c.to_id)
  );
  for (const c of validConns) {
    state.nodeMap.get(c.from_id).degree += 1;
    state.nodeMap.get(c.to_id).degree   += 1;
  }

  const pairCounts = new Map();
  state.edges = validConns.map((c, index) => {
    const pairKey   = [c.from_id, c.to_id].sort().join('|');
    const pairIndex = pairCounts.get(pairKey) || 0;
    pairCounts.set(pairKey, pairIndex + 1);
    return {
      id:          index,
      relation_id: c.relation_id,
      from_id:     c.from_id,
      to_id:       c.to_id,
      source:      state.nodeMap.get(c.from_id),
      target:      state.nodeMap.get(c.to_id),
      color:       c.color,
      label:       c.label || '',
      curveOffset: (pairIndex % 2 === 0 ? 1 : -1) * (10 + Math.floor(pairIndex / 2) * 12)
    };
  });

  return positionMap.size > 0;
}

function initializeLayout(force = false) {
  const viewportCenter = screenToWorld({
    x: canvas.clientWidth / 2,
    y: canvas.clientHeight / 2
  });
  const centerX = viewportCenter.x;
  const centerY = viewportCenter.y;
  const sorted = [...state.nodes].sort((a, b) => b.degree - a.degree || a.display_name.localeCompare(b.display_name));
  const nodesToLayout = force
    ? sorted
    : sorted.filter(node => !Number.isFinite(node.x) || !Number.isFinite(node.y));

  if (nodesToLayout.length === 0) return;

  let index = 0;
  let ring = 0;

  while (index < nodesToLayout.length) {
    const ringCount = Math.max(1, ring === 0 ? 1 : Math.round(6 + ring * 5.5));
    const ringRadius = 40 + ring * 88;

    for (let i = 0; i < ringCount && index < nodesToLayout.length; i++, index++) {
      const node = nodesToLayout[index];
      const angle = (Math.PI * 2 * i) / ringCount + ring * 0.35;
      const jitter = (index % 3) * 6;
      node.x = centerX + Math.cos(angle) * (ringRadius + jitter);
      node.y = centerY + Math.sin(angle) * (ringRadius + jitter * 0.6);
    }

    ring += 1;
  }
}

function quadraticPoint(p0, p1, p2, t) {
  const mt = 1 - t;
  return {
    x: mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x,
    y: mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y
  };
}

function drawArrowHead(tipX, tipY, ctrlX, ctrlY, color, alpha) {
  const angle = Math.atan2(tipY - ctrlY, tipX - ctrlX);
  const size = 8;

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(tipX, tipY);
  ctx.lineTo(tipX - Math.cos(angle - Math.PI / 6) * size, tipY - Math.sin(angle - Math.PI / 6) * size);
  ctx.lineTo(tipX - Math.cos(angle + Math.PI / 6) * size, tipY - Math.sin(angle + Math.PI / 6) * size);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawEdgeLabel(edge, ctrlX, ctrlY, alpha) {
  if (!edge.label) return;

  const point = quadraticPoint(
    { x: edge.source.x, y: edge.source.y },
    { x: ctrlX, y: ctrlY },
    { x: edge.target.x, y: edge.target.y },
    0.5
  );

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = '600 11px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const paddingX = 8;
  const width = ctx.measureText(edge.label).width + paddingX * 2;
  const height = 20;
  const x = point.x - width / 2;
  const y = point.y - height / 2;

  ctx.fillStyle = 'rgba(255, 255, 255, 0.96)';
  ctx.beginPath();
  ctx.roundRect(x, y, width, height, 8);
  ctx.fill();

  ctx.strokeStyle = 'rgba(0,0,0,0.18)';
  ctx.stroke();
  ctx.fillStyle = '#000000';
  ctx.fillText(edge.label, point.x, point.y + 0.5);
  ctx.restore();
}

function drawEdge(edge) {
  const { source, target } = edge;
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const nx = -dy / dist;
  const ny = dx / dist;
  const bend = Math.min(42, Math.max(16, dist * 0.16)) + edge.curveOffset;
  const directionSeed = source.id < target.id ? 1 : -1;
  const cx = (source.x + target.x) / 2 + nx * bend * directionSeed;
  const cy = (source.y + target.y) / 2 + ny * bend * directionSeed;
  const color = COLORS[edge.color];
  const alpha = state.searchTerm && source !== state.activeNode && target !== state.activeNode ? 0.18 : 0.72;

  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = state.activeNode && source !== state.activeNode && target !== state.activeNode ? 1.2 : 2.2;
  ctx.globalAlpha = alpha;
  ctx.beginPath();
  ctx.moveTo(source.x, source.y);
  ctx.quadraticCurveTo(cx, cy, target.x, target.y);
  ctx.stroke();
  ctx.restore();

  drawArrowHead(target.x, target.y, cx, cy, color, alpha);
  drawEdgeLabel(edge, cx, cy, alpha);
}

function drawNode(node) {
  const isActive = state.activeNode === node || state.hoveredNode === node;
  const isDimmed = state.searchTerm && state.activeNode !== node;

  loadPortrait(node.person_id);

  const img = imageCache.get(node.person_id);
  const hasImage = img && img !== 'loading' && img !== 'error';

  ctx.save();
  ctx.globalAlpha = isDimmed ? 0.28 : 1;

  // Halo / hover shadow
  ctx.beginPath();
  ctx.arc(node.x, node.y, node.radius + (isActive ? 5 : 0), 0, Math.PI * 2);
  ctx.fillStyle = isActive ? 'rgba(0,0,0,0.10)' : 'rgba(0,0,0,0.04)';
  ctx.fill();

  if (hasImage) {
    // Portrait: clip circle, draw image
    ctx.save();
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
    ctx.clip();
    const d = node.radius * 2;
    ctx.drawImage(img, node.x - node.radius, node.y - node.radius, d, d);
    ctx.restore();
  } else {
    // Fallback: colored circle + initials
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
    ctx.fillStyle = node.fill;
    ctx.fill();
    ctx.fillStyle = '#000000';
    ctx.font = 'bold 13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(node.initials, node.x, node.y + 0.5);
  }

  // Border ring
  ctx.beginPath();
  ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
  ctx.lineWidth = isActive ? 3 : 1.5;
  ctx.strokeStyle = isActive ? '#000000' : 'rgba(0,0,0,0.45)';
  ctx.stroke();

  // Label below node
  ctx.fillStyle = '#000000';
  ctx.textAlign = 'center';
  ctx.font = isActive ? '600 12px Inter, sans-serif' : '500 12px Inter, sans-serif';
  ctx.textBaseline = 'top';
  wrapText(node.display_name, node.x, node.y + node.radius + 10, 120, 14);
  ctx.restore();
}

function wrapText(text, x, y, maxWidth, lineHeight) {
  const words = text.split(' ');
  let line = '';
  const lines = [];

  for (const word of words) {
    const testLine = line ? `${line} ${word}` : word;
    if (ctx.measureText(testLine).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = testLine;
    }
  }
  if (line) lines.push(line);

  lines.forEach((entry, index) => {
    ctx.fillStyle = '#000000';
    ctx.fillText(entry, x, y + index * lineHeight);
  });
}

function render() {
  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  ctx.save();
  ctx.translate(state.viewport.x, state.viewport.y);
  ctx.scale(state.viewport.scale, state.viewport.scale);
  for (const edge of state.edges) drawEdge(edge);
  for (const node of state.nodes) drawNode(node);
  ctx.restore();
}

function animate() {
  render();
  requestAnimationFrame(animate);
}

function getPointerPosition(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  };
}

function hitTest(point) {
  const worldPoint = screenToWorld(point);
  for (let i = state.nodes.length - 1; i >= 0; i--) {
    const node = state.nodes[i];
    const dx = worldPoint.x - node.x;
    const dy = worldPoint.y - node.y;
    if (Math.sqrt(dx * dx + dy * dy) <= node.radius + 6) {
      return node;
    }
  }
  return null;
}

canvas.addEventListener('pointerdown', event => {
  const point = getPointerPosition(event);
  const node = hitTest(point);

  if (event.button === 1 || (event.button === 0 && !node)) {
    panInfo = {
      lastX: event.clientX,
      lastY: event.clientY
    };
    canvas.style.cursor = 'grabbing';
    canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
    return;
  }

  if (!node || event.button !== 0) return;

  const worldPoint = screenToWorld(point);
  dragInfo = {
    node,
    offsetX: worldPoint.x - node.x,
    offsetY: worldPoint.y - node.y,
    moved: false
  };
  state.activeNode = node;
  canvas.style.cursor = 'grabbing';
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener('pointermove', event => {
  const point = getPointerPosition(event);

  if (dragInfo) {
    const worldPoint = screenToWorld(point);
    if (Math.abs(worldPoint.x - dragInfo.node.x) > 0.01 || Math.abs(worldPoint.y - dragInfo.node.y) > 0.01) {
      dragInfo.moved = true;
    }
    dragInfo.node.x = worldPoint.x - dragInfo.offsetX;
    dragInfo.node.y = worldPoint.y - dragInfo.offsetY;
    return;
  }

  if (panInfo) {
    const dx = event.clientX - panInfo.lastX;
    const dy = event.clientY - panInfo.lastY;
    state.viewport.x += dx;
    state.viewport.y += dy;
    panInfo.lastX = event.clientX;
    panInfo.lastY = event.clientY;
    return;
  }

  state.hoveredNode = hitTest(point);
  canvas.style.cursor = state.hoveredNode ? 'grab' : 'default';
});

canvas.addEventListener('pointerup', event => {
  const shouldPersist = Boolean(dragInfo && dragInfo.moved);
  dragInfo = null;
  panInfo = null;
  if (canvas.hasPointerCapture(event.pointerId)) {
    canvas.releasePointerCapture(event.pointerId);
  }
  canvas.style.cursor = state.hoveredNode ? 'grab' : 'default';
  if (shouldPersist) {
    persist();
  }
});

canvas.addEventListener('pointerleave', () => {
  if (!dragInfo) state.hoveredNode = null;
  if (!dragInfo && !panInfo) canvas.style.cursor = 'default';
});

canvas.addEventListener('wheel', event => {
  event.preventDefault();
  const point = getPointerPosition(event);
  const zoomFactor = event.deltaY < 0 ? 1.12 : 0.89;
  zoomAt(point, zoomFactor);
}, { passive: false });

canvas.addEventListener('dblclick', event => {
  const point = getPointerPosition(event);
  zoomAt(point, 1.2);
});

searchInput.addEventListener('input', event => {
  const term = normalizeText(event.target.value);
  state.searchTerm = term;
  state.activeNode = state.nodes.find(node => normalizeText(node.display_name).includes(term)) || null;
});

resetBtn.addEventListener('click', () => {
  initializeLayout(true);
  persist();
});

// ── Zoom-Buttons ────────────────────────────────────

let zoomAnimation = null;

function smoothZoom(factor, durationMs = 220) {
  if (zoomAnimation) cancelAnimationFrame(zoomAnimation);
  const center = {
    x: canvas.clientWidth  / 2,
    y: canvas.clientHeight / 2
  };
  const startScale = state.viewport.scale;
  const targetScale = clamp(startScale * factor, state.viewport.minScale, state.viewport.maxScale);
  if (targetScale === startScale) return;

  const startX = state.viewport.x;
  const startY = state.viewport.y;
  const worldCenter = screenToWorld(center);
  const startTime = performance.now();

  function step(now) {
    const t = Math.min((now - startTime) / durationMs, 1);
    const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    const s = startScale + (targetScale - startScale) * ease;
    state.viewport.scale = s;
    state.viewport.x = center.x - worldCenter.x * s;
    state.viewport.y = center.y - worldCenter.y * s;
    if (t < 1) {
      zoomAnimation = requestAnimationFrame(step);
    } else {
      zoomAnimation = null;
    }
  }
  zoomAnimation = requestAnimationFrame(step);
}

zoomInBtn.addEventListener('click',  () => smoothZoom(1.4));
zoomOutBtn.addEventListener('click', () => smoothZoom(1 / 1.4));

window.addEventListener('resize', () => {
  resizeCanvas();
  initializeLayout(false);
});

resizeCanvas();
loadData().catch(error => {
  console.error(error);
  document.body.insertAdjacentHTML('beforeend', '<div style="position:fixed;bottom:16px;left:16px;background:#7f1d1d;color:#fff;padding:10px 12px;border-radius:8px;">Fehler beim Laden der CSV-Daten.</div>');
});

attachDropdown(relFrom, relFromDropdown);
attachDropdown(relTo, relToDropdown);

// ── Custom person dropdown ──────────────────────────

function getPersonOptions(filterText) {
  const nameCounts = new Map();
  for (const node of state.nodes) {
    nameCounts.set(node.display_name, (nameCounts.get(node.display_name) || 0) + 1);
  }
  const q = filterText.trim().toLowerCase();
  return state.nodes
    .map(node => ({
      label: nameCounts.get(node.display_name) > 1
        ? `${node.display_name} (${node.person_id})`
        : node.display_name,
      node
    }))
    .filter(({ label }) => !q || label.toLowerCase().includes(q));
}

function attachDropdown(inputEl, dropdownEl) {
  let activeIndex = -1;

  function showDropdown(filter = '') {
    const options = getPersonOptions(filter);
    dropdownEl.innerHTML = '';
    activeIndex = -1;
    if (options.length === 0) { dropdownEl.hidden = true; return; }
    options.forEach(({ label }, i) => {
      const item = document.createElement('div');
      item.className = 'person-dropdown-item';
      item.textContent = label;
      item.addEventListener('mousedown', e => {
        e.preventDefault();
        inputEl.value = label;
        dropdownEl.hidden = true;
      });
      dropdownEl.appendChild(item);
    });
    dropdownEl.hidden = false;
  }

  function setActive(index) {
    const items = dropdownEl.querySelectorAll('.person-dropdown-item');
    items.forEach(el => el.classList.remove('active'));
    activeIndex = Math.max(-1, Math.min(index, items.length - 1));
    if (activeIndex >= 0) {
      items[activeIndex].classList.add('active');
      items[activeIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  inputEl.addEventListener('focus', () => showDropdown(inputEl.value));
  inputEl.addEventListener('input', () => showDropdown(inputEl.value));
  inputEl.addEventListener('blur', () => { setTimeout(() => { dropdownEl.hidden = true; }, 150); });
  inputEl.addEventListener('keydown', e => {
    if (dropdownEl.hidden) return;
    const items = dropdownEl.querySelectorAll('.person-dropdown-item');
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIndex + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIndex - 1); }
    else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      inputEl.value = items[activeIndex].textContent;
      dropdownEl.hidden = true;
    } else if (e.key === 'Escape') { dropdownEl.hidden = true; }
  });
}

// ── Modal: Beziehung hinzufügen ────────────────────────

function openModal() {
  relFrom.value = '';
  relTo.value = '';
  relColor.value = 'rot';
  relLabel.value = '';
  relError.hidden = true;
  relModal.hidden = false;
  relFrom.focus();
}

function closeModal() {
  relModal.hidden = true;
}

function showError(msg) {
  relError.textContent = msg;
  relError.hidden = false;
}

function resolvePersonInput(inputValue) {
  const val = inputValue.trim();
  // If user selected a disambiguated option like "Thomas (p_abc123)", extract the ID
  const idMatch = val.match(/\(([^)]+)\)$/);
  if (idMatch) {
    const pid = idMatch[1].trim();
    if (state.nodeMap.has(pid)) return state.nodeMap.get(pid);
  }
  // Fall back to exact display_name match (case-insensitive)
  const lower = val.toLowerCase();
  return state.nodes.find(n => n.display_name.toLowerCase() === lower) || null;
}

function addRelationship() {
  const fromVal = relFrom.value.trim();
  const toVal   = relTo.value.trim();
  const color   = relColor.value;
  const label   = relLabel.value.trim();

  if (!fromVal) { showError('Bitte eine "Von"-Person eingeben.'); return; }
  if (!toVal)   { showError('Bitte eine "Zu"-Person eingeben.'); return; }

  const viewportCenter = screenToWorld({
    x: canvas.clientWidth / 2,
    y: canvas.clientHeight / 2
  });

  function ensureNode(inputValue) {
    let node = resolvePersonInput(inputValue);
    if (!node) {
      const pid  = newId('p');
      // Strip any trailing "(id)" in case the user typed it manually
      const displayName = inputValue.replace(/\s*\([^)]+\)$/, '').trim();
      node = {
        id:           state.nodes.length,
        person_id:    pid,
        display_name: displayName,
        x: viewportCenter.x + (Math.random() - 0.5) * 200,
        y: viewportCenter.y + (Math.random() - 0.5) * 200,
        radius:    28,
        fill:      hashColor(pid),
        labelWidth: 0,
        initials:  initials(displayName),
        degree:    0
      };
      state.nodes.push(node);
      state.nodeMap.set(pid, node);
    }
    return node;
  }

  const sourceNode = ensureNode(fromVal);
  const targetNode = ensureNode(toVal);

  if (sourceNode.person_id === targetNode.person_id) {
    showError('Von- und Zu-Person dürfen nicht identisch sein.');
    return;
  }

  sourceNode.degree += 1;
  targetNode.degree += 1;

  const pairKey  = [sourceNode.person_id, targetNode.person_id].sort().join('|');
  const existing = state.edges.filter(
    e => [e.from_id, e.to_id].sort().join('|') === pairKey
  ).length;
  const curveOffset = (existing % 2 === 0 ? 1 : -1) * (10 + Math.floor(existing / 2) * 12);

  const rid = newId('r');
  state.edges.push({
    id:          state.edges.length,
    relation_id: rid,
    from_id:     sourceNode.person_id,
    to_id:       targetNode.person_id,
    source:      sourceNode,
    target:      targetNode,
    color,
    label,
    curveOffset
  });

  closeModal();
  persist();
}

addRelBtn.addEventListener('click', openModal);
relCancelBtn.addEventListener('click', closeModal);
relSaveBtn.addEventListener('click', addRelationship);
relModal.addEventListener('click', e => { if (e.target === relModal) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeModal(); closeEditModal(); hideCtxMenu(); } });

// ── Kontextmenü (Rechtsklick auf Knoten) ───────────

let ctxEdge = null; // die aktuell zu bearbeitende Kante

function hideCtxMenu() {
  ctxMenu.hidden = true;
}

function showCtxMenu(node, screenX, screenY) {
  const edges = state.edges.filter(e => e.source === node || e.target === node);
  ctxMenu.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'ctx-menu-header';
  header.textContent = node.display_name;
  ctxMenu.appendChild(header);

  // ── Person bearbeiten ──
  const editPersonItem = document.createElement('div');
  editPersonItem.className = 'ctx-menu-item ctx-menu-item--person';
  editPersonItem.textContent = 'Person bearbeiten …';
  editPersonItem.addEventListener('click', () => {
    hideCtxMenu();
    openPersonModal(node);
  });
  ctxMenu.appendChild(editPersonItem);

  if (edges.length > 0) {
    const sep = document.createElement('div');
    sep.className = 'ctx-menu-separator';
    ctxMenu.appendChild(sep);
  }

  const COLOR_HEX = { rot: '#ef4444', blau: '#3b82f6', orange: '#f59e0b' };

  for (const edge of edges) {
    const other = edge.source === node ? edge.target : edge.source;
    const item = document.createElement('div');
    item.className = 'ctx-menu-item';

    const dot = document.createElement('span');
    dot.className = 'ctx-color-dot';
    dot.style.background = COLOR_HEX[edge.color] || '#888';

    const label = document.createElement('span');
    const rel = edge.label ? ` (${edge.label})` : '';
    label.textContent = `→ ${other.display_name}${rel}`;

    item.appendChild(dot);
    item.appendChild(label);
    item.addEventListener('click', () => {
      hideCtxMenu();
      openEditModal(edge);
    });
    ctxMenu.appendChild(item);
  }

  // Position sicherstellen (nicht außerhalb des Fensters)
  ctxMenu.hidden = false;
  const mw = ctxMenu.offsetWidth;
  const mh = ctxMenu.offsetHeight;
  ctxMenu.style.left = (Math.min(screenX, window.innerWidth  - mw - 8)) + 'px';
  ctxMenu.style.top  = (Math.min(screenY, window.innerHeight - mh - 8)) + 'px';
}

canvas.addEventListener('contextmenu', e => {
  e.preventDefault();
  const point = getPointerPosition(e);
  const node = hitTest(point);
  if (node) {
    showCtxMenu(node, e.clientX, e.clientY);
  } else {
    hideCtxMenu();
  }
});

document.addEventListener('pointerdown', e => {
  if (!ctxMenu.contains(e.target)) hideCtxMenu();
});

// ── Edit-Modal ──────────────────────────────────────

function openEditModal(edge) {
  ctxEdge = edge;
  editFrom.value = edge.source.display_name;
  editTo.value = edge.target.display_name;
  editColor.value = edge.color;
  editLabel.value = edge.label || '';
  editError.hidden = true;
  editModal.hidden = false;
  editLabel.focus();
}

function closeEditModal() {
  editModal.hidden = true;
  ctxEdge = null;
}

function saveEdit() {
  if (!ctxEdge) return;
  ctxEdge.color = editColor.value;
  ctxEdge.label = editLabel.value.trim();
  closeEditModal();
  persist();
}

function deleteEdge() {
  if (!ctxEdge) return;
  ctxEdge.source.degree = Math.max(0, ctxEdge.source.degree - 1);
  ctxEdge.target.degree = Math.max(0, ctxEdge.target.degree - 1);
  state.edges = state.edges.filter(e => e !== ctxEdge);
  closeEditModal();
  persist();
}

editSaveBtn.addEventListener('click', saveEdit);
editDeleteBtn.addEventListener('click', deleteEdge);
editCancelBtn.addEventListener('click', closeEditModal);
editModal.addEventListener('click', e => { if (e.target === editModal) closeEditModal(); });

// ── Modal: Person bearbeiten ────────────────────────

let personModalNode = null; // the node currently being edited

function _currentPortraitSrc(personId) {
  const cached = imageCache.get(personId);
  if (cached && cached !== 'loading' && cached !== 'error') return cached.src;
  return '/portraits/placeholder.svg';
}

function openPersonModal(node) {
  personModalNode = node;
  personName.value = node.display_name;
  personPortraitPreview.src = _currentPortraitSrc(node.person_id);
  personPhotoInput.value = '';
  personError.hidden = true;
  personModal.hidden = false;
  personName.focus();
}

function closePersonModal() {
  personModal.hidden = true;
  personModalNode = null;
}

async function readApiError(response, fallbackMessage) {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      const body = await response.json();
      return body.error || fallbackMessage;
    } catch {
      return fallbackMessage;
    }
  }
  return fallbackMessage;
}

personPhotoInput.addEventListener('change', () => {
  const file = personPhotoInput.files[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  personPortraitPreview.src = url;
});

personDeletePhotoBtn.addEventListener('click', async () => {
  if (!personModalNode) return;
  try {
    const resp = await fetch(`/api/portrait/${personModalNode.person_id}`, { method: 'DELETE' });
    if (!resp.ok) {
      personError.textContent = await readApiError(resp, 'Foto konnte nicht geloescht werden.');
      personError.hidden = false;
      return;
    }
    imageCache.delete(personModalNode.person_id);
    personPortraitPreview.src = '/portraits/placeholder.svg';
    personPhotoInput.value = '';
    personError.hidden = true;
  } catch {
    personError.textContent = 'Netzwerkfehler beim Loeschen des Fotos.';
    personError.hidden = false;
  }
});

personSaveBtn.addEventListener('click', async () => {
  if (!personModalNode) return;
  const newName = personName.value.trim();
  if (!newName) {
    personError.textContent = 'Name darf nicht leer sein.';
    personError.hidden = false;
    return;
  }

  // Upload photo if a new file was selected
  const file = personPhotoInput.files[0];
  if (file) {
    const formData = new FormData();
    formData.append('portrait', file);
    let resp;
    try {
      resp = await fetch(`/api/portrait/${personModalNode.person_id}`, {
        method: 'POST',
        body: formData
      });
    } catch {
      personError.textContent = 'Netzwerkfehler beim Foto-Upload.';
      personError.hidden = false;
      return;
    }
    if (!resp.ok) {
      personError.textContent = await readApiError(resp, 'Foto-Upload fehlgeschlagen.');
      personError.hidden = false;
      return;
    }
    // Bust the image cache so the canvas reloads the new portrait
    imageCache.delete(personModalNode.person_id);
  }

  // Update display name
  personModalNode.display_name = newName;
  personModalNode.initials = initials(newName);

  closePersonModal();
  persist();
});

personCancelBtn.addEventListener('click', closePersonModal);
personModal.addEventListener('click', e => { if (e.target === personModal) closePersonModal(); });


