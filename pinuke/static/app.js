import {ResponseGraph, crossoverDb, peqDb, peqBandDb, deqDb, compressionDb} from './graphs.js';
import {MeterPanel} from './meters.js';
const $ = id => document.getElementById(id);
const statusEl = $('device-status');
const readStatusEl = $('read-status');
const readButton = $('read-button');
const saveButton = $('save-button');
const applyButton = $('apply-button');
const discardButton = $('discard-button');
let snapshot = null;
let revision = null;
let controls = null;
let busy = false;
let editors = [];
let changes = [];
let graphs = [];
let modelInput = -30;

function text(tag, value, className = '') {
  const element = document.createElement(tag);
  element.textContent = String(value ?? '—');
  if (className) element.className = className;
  return element;
}
function fact(target, label, value) {
  const group = document.createElement('div');
  group.append(text('dt', label), text('dd', value));
  target.append(group);
}
function display(value) {
  return typeof value === 'number' ? String(Number(value.toFixed(4))) : String(value);
}
function valueFor(data, change) {
  const ch = data.channels[String(change.channel)];
  if (['high_pass', 'low_pass'].includes(change.block)) return ch.crossover[change.block];
  if (change.block === 'gain_db') return {gain_db: ch.crossover.gain_db};
  if (change.block === 'peq') return ch.peq[change.band - 1];
  if (change.block.startsWith('deq_')) {
    const part = {deq_filter: 'filter', deq_compressor: 'compressor', deq_timing: 'timing'}[change.block];
    return ch.dynamic_eq[change.band - 1][part];
  }
  return ch[change.block];
}
function titleFor(change) {
  return `Channel ${change.channel === 1 ? 'A' : 'B'} · ${controls.groups[change.block].label}${change.band ? ` ${change.band}` : ''}`;
}
function availability() {
  const canEdit = controls?.enabled && revision && !busy;
  editors.forEach(editor => Object.values(editor.inputs).forEach(input => { input.disabled = !canEdit; }));
  readButton.disabled = busy || changes.length > 0;
  saveButton.disabled = busy || !snapshot;
  applyButton.disabled = !canEdit || !changes.length;
  discardButton.disabled = busy || !changes.length;
  $('home-button').setAttribute('aria-disabled', String(busy));
  window.parent.postMessage({type: 'pinuke-dirty', dirty: changes.length > 0 || busy}, window.location.origin);
}
function collectChanges() {
  const pending = [];
  const review = $('change-list');
  review.replaceChildren();
  for (const editor of editors) {
    const value = {...editor.original};
    const lines = [];
    for (const [key, input] of Object.entries(editor.inputs)) {
      // Retain the exact device float for every untouched field.
      if (input.value === editor.initial[key]) continue;
      value[key] = typeof editor.original[key] === 'number' ? (input.value === '' ? NaN : Number(input.value)) : input.value;
      if (value[key] !== editor.original[key]) lines.push(`${controls.groups[editor.change.block].fields[key].label}: ${display(editor.original[key])} → ${input.value || 'empty'}`);
    }
    editor.element.classList.toggle('changed', lines.length > 0);
    if (lines.length) {
      pending.push({...editor.change, value});
      review.append(text('li', `${titleFor(editor.change)} — ${lines.join('; ')}`));
    }
  }
  changes = pending;
  $('change-count').textContent = changes.length ? `${changes.length} DSP group${changes.length === 1 ? '' : 's'} ready to apply` : 'No pending changes';
  $('change-review').hidden = !changes.length;
  availability();
  updateGraphs();
  window.parent.postMessage({type: 'pinuke-dirty', dirty: changes.length > 0 || busy}, window.location.origin);
}
function group(channel, block, band) {
  const spec = controls.groups[block];
  const change = {channel, block, ...(band ? {band} : {})};
  const original = valueFor(snapshot, change);
  const element = document.createElement('fieldset');
  element.className = 'control-group';
  element.append(text('legend', `${spec.label}${band ? ` ${band}` : ''}`));
  const fields = document.createElement('div');
  fields.className = 'fields';
  const editor = {change, original, inputs: {}, initial: {}, element};
  for (const [key, rule] of Object.entries(spec.fields)) {
    const label = document.createElement('label');
    label.append(text('span', rule.label));
    let input;
    if (rule.choices) {
      input = document.createElement('select');
      rule.choices.forEach(value => {
        const option = text('option', value === 'OFF' ? 'Off' : value);
        option.value = String(value);
        input.append(option);
      });
      // Preserve an unknown live value visibly; backend rejects it on a changed group.
      if (!rule.choices.some(v => String(v) === String(original[key]))) {
        const option = text('option', `${original[key]} (reported)`);
        option.value = String(original[key]);
        input.append(option);
      }
    } else {
      input = document.createElement('input');
      input.type = 'number';
      input.min = rule.min;
      input.max = rule.max;
      input.step = 'any';
      input.required = true;
    }
    input.value = display(original[key]);
    input.setAttribute('aria-label', `${titleFor(change)} ${rule.label}`);
    input.addEventListener('input', collectChanges);
    input.addEventListener('change', collectChanges);
    editor.inputs[key] = input;
    editor.initial[key] = input.value;
    label.append(input);
    fields.append(label);
  }
  element.append(fields);
  editors.push(editor);
  return element;
}
function render(data, newRevision) {
  snapshot = data;
  revision = newRevision;
  $('summary').hidden = false;
  $('editor').hidden = false;
  $('empty-state').hidden = true;
  const summary = $('summary-fields');
  summary.replaceChildren();
  fact(summary, 'Amplifier', data.info.amp_name);
  fact(summary, 'Firmware', data.info.firmware);
  fact(summary, 'Mode', data.mode);
  fact(summary, 'Read at', new Date(data.captured_at).toLocaleTimeString());
  $('readback-label').textContent = `Readback details · ${new Date(data.captured_at).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})}`;
  $('amp-name').textContent = data.info.amp_name;
  $('amp-detail').textContent = `${data.info.firmware} · ${data.mode}`;
  graphs.forEach(g => g.graph.destroy());
  graphs = [];
  $('channels').replaceChildren();
  editors = [];
  const sections = [
    ['01', 'Crossover', 'Shape the passband', ['high_pass', 'low_pass', 'gain_db'], 'crossover'],
    ['02', 'Parametric EQ', 'Eight bands per channel', [], 'peq'],
    ['03', 'Dynamic EQ', 'Two bands per channel', [], 'deq'],
    ['04', 'Delay & limiter', 'Timing, polarity and output ceiling', ['delay', 'limiter'], 'output'],
  ];
  for (const [number, name, sub, blocks, kind] of sections) {
    const section = document.createElement('section');
    section.className = 'signal-section'; section.id = kind;
    const heading = document.createElement('div'); heading.className = 'section-heading';
    const title = document.createElement('div');
    title.append(text('span', number, 'section-number'), text('h2', name), text('p', sub, 'muted'));
    const legend = document.createElement('div'); legend.className = 'channel-legend';
    legend.append(text('span', 'A', 'legend-a'), text('span', 'B', 'legend-b'));
    heading.append(title, legend); section.append(heading);
    if (kind !== 'output') {
      const host = document.createElement('div'); host.className = 'graph-host';
      section.append(host);
      graphs.push({kind, graph: new ResponseGraph(host, {title: `${name} idealized frequency-response preview`, min: kind === 'deq' ? -36 : -24})});
    }
    if (kind === 'deq') {
      const detail = document.createElement('details'); detail.className = 'model-detail';
      detail.append(text('summary', 'Dynamics model · input / output'));
      const label = document.createElement('label'); label.className = 'model-level';
      const value = text('span', `Model input: ${modelInput} dB`);
      const slider = document.createElement('input'); slider.type = 'range'; slider.min = '-60'; slider.max = '0'; slider.step = '1'; slider.value = modelInput;
      slider.setAttribute('aria-label', 'Dynamic EQ model input level, preview only');
      slider.addEventListener('input', () => { modelInput = Number(slider.value); value.textContent = `Model input: ${modelInput} dB`; updateGraphs(); });
      label.append(value, slider); detail.append(label);
      const host = document.createElement('div'); host.className = 'graph-host'; detail.append(host);
      graphs.push({kind: 'transfer', graph: new ResponseGraph(host, {title: 'Idealized per-band dynamics transfer, A/B bands 1/2', min: -60, max: 0, transfer: true})});
      detail.append(text('p', 'Steady-state illustration; band 2 uses a finer line. Actual DEQ behavior and timing require measurement.', 'graph-note'));
      section.append(detail);
    }
    const columns = document.createElement('div'); columns.className = 'channel-grid';
    for (const channel of [1, 2]) {
      const card = document.createElement('div'); card.className = `channel channel-${channel}`;
      card.append(text('h3', `Channel ${channel === 1 ? 'A' : 'B'}`));
      for (const block of blocks) card.append(group(channel, block));
      if (kind === 'peq' || kind === 'deq') {
        for (let band = 1; band <= (kind === 'peq' ? 8 : 2); band++) {
          const bandData = kind === 'peq' ? data.channels[String(channel)].peq[band - 1] : data.channels[String(channel)].dynamic_eq[band - 1].filter;
          const detail = document.createElement('details'); detail.className = 'band-detail'; detail.open = bandData.type !== 'OFF';
          const caption = document.createElement('summary');
          caption.append(text('span', `Band ${String(band).padStart(2, '0')}`), text('span', bandData.type === 'OFF' ? 'Off' : `${bandData.type} · ${display(bandData.freq)} Hz`, 'band-state'));
          detail.append(caption);
          for (const block of kind === 'peq' ? ['peq'] : ['deq_filter', 'deq_compressor', 'deq_timing']) detail.append(group(channel, block, band));
          card.append(detail);
        }
      }
      columns.append(card);
    }
    section.append(columns);
    if (kind === 'crossover') section.append(text('p', 'Preview uses idealized roll-off by slope; Butterworth, Bessel and Linkwitz–Riley differences are not modeled.', 'graph-note'));
    if (kind === 'peq') section.append(text('p', 'Fine lines: individual bands. Strong lines: combined EQ. Configured response preview, not a speaker or room measurement.', 'graph-note'));
    if (kind === 'deq') section.append(text('p', 'Frequency illustration at the model input level; this is not a live DEQ response measurement.', 'graph-note'));
    $('channels').append(section);
  }
  $('edit-note').textContent = controls.enabled
    ? 'Edit either channel, review the changes below, then Apply. Typing does not change the amplifier.'
    : 'This service is running in read-only mode.';
  $('edit-actions').hidden = !controls.enabled;
  collectChanges();
}
function message(value, error = false) {
  readStatusEl.textContent = value;
  readStatusEl.className = error ? 'error' : 'muted';
}
function draftState() {
  if (!snapshot) return null;
  const data = structuredClone(snapshot);
  for (const editor of editors) {
    const value = valueFor(data, editor.change);
    for (const [key, input] of Object.entries(editor.inputs)) {
      if (input.value === editor.initial[key]) continue;
      const next = typeof editor.original[key] === 'number' ? Number(input.value) : input.value;
      if (input.value === '' || (typeof next === 'number' && !Number.isFinite(next))) return null;
      value[key] = next;
    }
    if (editor.change.block === 'gain_db') data.channels[String(editor.change.channel)].crossover.gain_db = value.gain_db;
  }
  return data;
}
function updateGraphs() {
  const data = draftState(); if (!data) return;
  for (const {kind, graph} of graphs) {
    const lines = [];
    for (const channel of [1, 2]) {
      const ch = data.channels[String(channel)], letter = channel === 1 ? 'A' : 'B', className = `curve-${letter.toLowerCase()}`;
      if (kind === 'peq') {
        ch.peq.forEach((b, i) => {
          if (b.type !== 'OFF') lines.push({label: `${letter} band ${i + 1}`, className: `${className} band-curve`, fn: f => peqBandDb(b.type, b.freq, b.gain, b.q, f)});
        });
      }
      if (kind === 'transfer') {
        ch.dynamic_eq.forEach((b, i) => {
          if (b.filter.type !== 'OFF') lines.push({label: `${letter} band ${i + 1}`, className: `${className} ${i ? 'band-curve' : ''}`, fn: f => compressionDb(f, b.compressor.threshold, b.compressor.ratio) + b.compressor.gain});
        });
        continue;
      }
      lines.push({label: `Channel ${letter}`, className,
        fn: kind === 'crossover' ? f => crossoverDb(ch.crossover, f) : kind === 'peq' ? f => peqDb(ch.peq, f) : f => deqDb(ch.dynamic_eq, f, modelInput)});
    }
    graph.set(lines);
  }
  for (const editor of editors) {
    const label = editor.element.closest('.band-detail')?.querySelector('.band-state');
    if (label && ['peq', 'deq_filter'].includes(editor.change.block)) {
      const v = valueFor(data, editor.change);
      label.textContent = v.type === 'OFF' ? 'Off' : `${v.type} · ${display(v.freq)} Hz`;
    }
  }
}
async function load() {
  try {
    const [scanResponse, controlsResponse] = await Promise.all([fetch('api/scan', {cache: 'no-store'}), fetch('api/controls', {cache: 'no-store'})]);
    const data = await scanResponse.json();
    controls = await controlsResponse.json();
    if (!scanResponse.ok || !controlsResponse.ok) throw Error(data.error || 'Connection check failed');
    const amp = data.devices.find(d => d.vendor_id === 5015 && d.product_id === 4353);
    statusEl.textContent = amp ? `${amp.product || 'iNuke USB device'} detected on the Pi.` : 'NU6000DSP is not connected to the Pi.';
    $('mode-badge').textContent = controls.enabled ? 'DSP editor' : 'Read-only';
    readButton.disabled = false;
  } catch (error) {
    statusEl.textContent = error.message;
    statusEl.className = 'error';
  }
}
readButton.addEventListener('click', async () => {
  busy = true;
  availability();
  message('Reading the amplifier…');
  try {
    const response = await fetch('api/readback', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Readback failed');
    render(result.snapshot, result.revision);
    message('Live readback complete. You can now review the settings.');
  } catch (error) {
    revision = null;
    message(`Readback failed: ${error.message}`, true);
  } finally { busy = false; availability(); }
});
discardButton.addEventListener('click', () => { render(snapshot, revision); message('Pending edits discarded. The amplifier was not changed.'); });
applyButton.addEventListener('click', async () => {
  for (const editor of editors) {
    for (const input of Object.values(editor.inputs)) if (!input.reportValidity()) return;
  }
  const requested = changes.map(change => ({...change, value: {...change.value}}));
  busy = true;
  availability();
  message('Checking current settings, applying changes, and reading them back…');
  try {
    const response = await fetch('api/apply', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({revision, changes: requested})});
    const result = await response.json();
    if (result.snapshot) render(result.snapshot, result.revision);
    if (!response.ok || !result.complete) throw Error(result.error || 'Apply could not be verified. Read the amp before continuing.');
    message('Changes applied and confirmed by a fresh read from the amplifier.');
  } catch (error) {
    revision = null;
    // An interrupted request may already have changed hardware; force a new read.
    changes = [];
    $('change-review').hidden = true;
    $('change-count').textContent = 'Read the amplifier before editing again';
    message(error.message, true);
  } finally { busy = false; availability(); }
});
saveButton.addEventListener('click', () => {
  if (!snapshot) return;
  const blob = new Blob([JSON.stringify(snapshot, null, 2) + '\n'], {type: 'application/json'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `pinuke-${new Date(snapshot.captured_at).toISOString().replaceAll(':', '-')}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});
// Enter in a numeric field must never implicitly submit settings.
$('editor').addEventListener('submit', event => event.preventDefault());
$('editor').querySelector('.chain-nav').addEventListener('click', event => {
  const link = event.target.closest('a');
  if (!link) return;
  event.preventDefault();
  document.querySelector(link.getAttribute('href'))?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
});
const meters = new MeterPanel($('live-meters'));
function returnHome(event) {
  event?.preventDefault();
  if (busy) { message('Wait for the amplifier transaction to finish before returning.'); return; }
  if (changes.length && !confirm('Discard pending edits and return to Pi?')) return;
  changes = [];
  if (window.parent !== window) window.parent.postMessage({type: 'pinuke-home'}, window.location.origin);
  else window.location.assign('/');
}
$('home-button').addEventListener('click', returnHome);
window.addEventListener('message', event => {
  if (event.origin === window.location.origin && event.source === window.parent && event.data?.type === 'pinuke-request-home') returnHome();
});
window.addEventListener('beforeunload', event => { if (changes.length || busy) { event.preventDefault(); event.returnValue = ''; } });
load();
