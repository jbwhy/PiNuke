// Visual-guide math adapted from Ryan Mathewson's MIT inuke-oscd.
// See UPSTREAM_LICENSE. These are idealized previews, not amp/room measurements.
export function peqBandDb(type, freq, gain, q, f) {
  if (!type || type === 'OFF' || !(freq > 0) || !gain) return 0;
  if (type === 'PEQ') return gain / Math.sqrt(1 + (q * (f / freq - freq / f)) ** 2);
  const order = {LS6: 1, LS12: 2, HS6: 1, HS12: 2}[type];
  if (!order) return 0;
  const ratio = type.startsWith('LS') ? f / freq : freq / f;
  return gain / (1 + ratio ** (2 * order));
}
export function peqDb(bands, f) {
  return bands.reduce((sum, b) => sum + peqBandDb(b.type, b.freq, b.gain, b.q, f), 0);
}
export function crossoverDb(c, f) {
  let db = c.gain_db;
  for (const [key, hp] of [['high_pass', true], ['low_pass', false]]) {
    const b = c[key];
    if (b.type === 'OFF') continue;
    const slope = Number(/(\d+)$/.exec(b.type)?.[1] || 0);
    db -= 10 * Math.log10(1 + (hp ? b.freq / f : f / b.freq) ** (2 * slope / 6));
  }
  return db;
}
export function compressionDb(inputDb, threshold, ratio) {
  return inputDb > threshold ? threshold + (inputDb - threshold) / ratio : inputDb;
}
export function deqDb(bands, f, inputDb) {
  return bands.reduce((sum, band) => {
    const b = band.filter, c = band.compressor;
    if (b.type === 'OFF') return sum;
    const delta = c.gain + compressionDb(inputDb, c.threshold, c.ratio) - inputDb;
    if (b.type === 'BP') return sum + peqBandDb('PEQ', b.freq, delta, b.q, f);
    return sum + peqBandDb(b.type.replace('LP', 'LS').replace('HP', 'HS'), b.freq, delta, b.q, f);
  }, 0);
}

const NS = 'http://www.w3.org/2000/svg';
function node(name, attrs = {}, content) {
  const n = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) n.setAttribute(key, value);
  if (content !== undefined) n.textContent = content;
  return n;
}
export class ResponseGraph {
  constructor(host, {title, min = -24, max = 12, transfer = false}) {
    this.host = host; this.title = title; this.min = min; this.max = max; this.transfer = transfer;
    this.svg = node('svg', {role: 'img', 'aria-label': title, class: 'response-graph'});
    host.append(this.svg);
    this.lines = [];
    this.observer = new ResizeObserver(() => this.draw());
    this.observer.observe(host);
  }
  set(lines) { this.lines = lines; this.draw(); }
  destroy() { this.observer.disconnect(); }
  draw() {
    const width = Math.max(230, this.host.clientWidth), height = this.transfer ? 190 : 210;
    const left = 40, right = width - 16, top = 18, bottom = height - 32;
    const x = this.transfer ? v => left + (v + 60) / 60 * (right - left)
      : v => left + Math.log10(v / 20) / 3 * (right - left);
    const y = v => top + (this.max - Math.max(this.min, Math.min(this.max, v))) / (this.max - this.min) * (bottom - top);
    this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    this.svg.replaceChildren(node('title', {}, this.title), node('desc', {}, 'Idealized model preview. Channel A solid, channel B dashed.'));
    const yticks = this.transfer ? [-60, -40, -20, 0] : [this.min, -12, 0, this.max];
    for (const db of [...new Set(yticks)]) {
      this.svg.append(node('line', {x1: left, y1: y(db), x2: right, y2: y(db), class: db === 0 ? 'graph-zero' : 'graph-grid'}));
      this.svg.append(node('text', {x: left - 9, y: y(db) + 4, 'text-anchor': 'end', class: 'graph-label'}, db));
    }
    const ticks = this.transfer ? [-60, -40, -20, 0] : width < 440 ? [20, 100, 1000, 20000] : [20, 50, 100, 500, 1000, 5000, 20000];
    for (const f of ticks) {
      this.svg.append(node('line', {x1: x(f), y1: top, x2: x(f), y2: bottom, class: 'graph-grid'}));
      const edge = f === ticks[0] ? 'start' : f === ticks.at(-1) ? 'end' : 'middle';
      this.svg.append(node('text', {x: x(f), y: bottom + 20, 'text-anchor': edge, class: 'graph-label'}, this.transfer ? `${f}` : f >= 1000 ? `${f / 1000}k` : f));
    }
    this.svg.append(node('text', {x: 4, y: 10, class: 'graph-label'}, 'dB'));
    this.svg.append(node('text', {x: right, y: 10, 'text-anchor': 'end', class: 'graph-label'}, this.transfer ? 'Input dB → output dB' : 'Hz'));
    for (const line of this.lines) {
      const samples = Array.from({length: 240}, (_, i) => this.transfer ? -60 + 60 * i / 239 : 20 * 1000 ** (i / 239));
      const points = samples.map(f => [x(f), y(line.fn(f))]);
      if (points.some(p => p.some(v => !Number.isFinite(v)))) continue;
      const d = points.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');
      const path = node('path', {d, class: `graph-curve ${line.className || ''}`});
      path.append(node('title', {}, line.label));
      this.svg.append(path);
    }
  }
}
