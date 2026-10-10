export const METER_KEYS = ['input_a', 'input_b', 'output_a', 'output_b'];
export function amplitudeDb(value, reference = 1) {
  return value > 0 && reference > 0 ? 20 * Math.log10(value / reference) : -Infinity;
}
const el = (tag, className, content) => {
  const n = document.createElement(tag); n.className = className;
  if (content !== undefined) n.textContent = content;
  return n;
};
export class MeterPanel {
  constructor(host, {compact = false, endpoint = 'api/meters'} = {}) {
    this.host = host; this.endpoint = endpoint; this.compact = compact;
    host.classList.add('nuke-meter-panel');
    this.status = el('span', 'nuke-meter-status', 'Connecting');
    const header = el('div', 'nuke-meter-heading');
    header.append(el('span', 'nuke-meter-title', compact ? 'Live levels' : 'Signal monitor'), this.status);
    this.groups = el('div', 'nuke-meter-groups');
    this.rows = {};
    for (const [label, keys] of [['INPUT', METER_KEYS.slice(0, 2)], ['OUTPUT', METER_KEYS.slice(2)]]) {
      const group = el('div', 'nuke-meter-group');
      group.append(el('div', 'nuke-meter-kicker', label));
      for (const key of keys) {
        const row = el('div', `nuke-meter-row nuke-${key.endsWith('a') ? 'a' : 'b'}`);
        const track = el('div', 'nuke-meter-track');
        const fill = el('div', 'nuke-meter-fill'), peak = el('div', 'nuke-meter-peak'), threshold = el('div', 'nuke-meter-threshold');
        track.append(fill, peak, threshold);
        const value = el('span', 'nuke-meter-value', '—');
        row.append(el('span', 'nuke-meter-channel', key.endsWith('a') ? 'A' : 'B'), track, value);
        track.setAttribute('role', 'meter'); track.setAttribute('aria-label', `${label.toLowerCase()} channel ${key.endsWith('a') ? 'A' : 'B'}`);
        track.setAttribute('aria-valuemin', '-80'); track.setAttribute('aria-valuemax', '0');
        group.append(row);
        this.rows[key] = {track, fill, peak, threshold, value, peakDb: -Infinity, peakUntil: 0};
      }
      this.groups.append(group);
    }
    this.note = el('p', 'nuke-meter-note', 'Waiting for fresh readings');
    host.append(header, this.groups, this.note);
    this.stopped = false; this.inflight = null; this.timer = null;
    this.visibility = () => {
      if (document.hidden) { clearTimeout(this.timer); this.inflight?.abort(); this.clear('Paused', 'Monitoring pauses while this page is hidden'); }
      else this.poll();
    };
    document.addEventListener('visibilitychange', this.visibility);
    this.poll();
  }
  clear(status, note) {
    this.status.textContent = status; this.host.classList.remove('nuke-live');
    for (const r of Object.values(this.rows)) {
      r.fill.style.width = '0%'; r.peak.hidden = true; r.threshold.hidden = true; r.value.textContent = '—';
      r.track.removeAttribute('aria-valuenow'); r.peakDb = -Infinity;
    }
    this.note.textContent = note;
  }
  update(data) {
    if (data.status !== 'live' || !data.levels || data.age_ms > 2000) {
      const label = {disabled: 'Offline', connecting: 'Connecting', paused: 'Reading / applying', unavailable: 'Unavailable', stale: 'No signal data', idle: 'Waiting'}[data.status] || 'Waiting';
      this.clear(label, data.status === 'disabled' ? 'Live monitoring is not enabled' : data.status === 'paused' ? 'Meters resume after the amplifier transaction' : 'No fresh meter readings');
      return;
    }
    this.status.textContent = 'Live'; this.host.classList.add('nuke-live');
    const cal = data.calibration, headrooms = [];
    const now = performance.now();
    for (const key of METER_KEYS) {
      const r = this.rows[key], raw = data.levels[key];
      if (!Number.isFinite(raw) || raw < 0) { this.clear('Unavailable', 'Invalid meter reading'); return; }
      const db = amplitudeDb(raw, cal?.reference_amplitude[key] || 1);
      const pct = Math.max(0, Math.min(100, (db + 80) / 80 * 100));
      r.fill.style.width = `${pct}%`;
      r.value.textContent = Number.isFinite(db) ? `${db.toFixed(1)}` : '−∞';
      r.track.setAttribute('aria-valuenow', String(Math.max(-80, Math.min(0, db))));
      r.track.setAttribute('aria-valuetext', `${r.value.textContent} ${cal ? 'dBFS' : 'dB relative to amplitude 1'}`);
      if (db >= r.peakDb || now > r.peakUntil) { r.peakDb = db; r.peakUntil = now + 1400; }
      r.peak.hidden = !Number.isFinite(r.peakDb); r.peak.style.left = `${Math.max(0, Math.min(100, (r.peakDb + 80) / 80 * 100))}%`;
      const thresholdVp = data.threshold_vp?.[key], scale = cal?.output_vp_per_amplitude[key];
      r.threshold.hidden = !(thresholdVp > 0 && scale > 0);
      if (!r.threshold.hidden) {
        const thresholdDb = amplitudeDb(thresholdVp / scale, cal.reference_amplitude[key]);
        r.threshold.style.left = `${Math.max(0, Math.min(100, (thresholdDb + 80) / 80 * 100))}%`;
        headrooms.push(`${key.endsWith('a') ? 'A' : 'B'} ${Number.isFinite(db) ? (thresholdDb - db).toFixed(1) : '∞'} dB`);
      }
    }
    this.note.textContent = cal ? headrooms.length ? `Last-read threshold headroom · ${headrooms.join(' / ')}` : 'dBFS · Read amplifier to show limiter thresholds'
      : 'Relative dB · calibration pending';
  }
  async poll() {
    clearTimeout(this.timer);
    if (this.stopped || document.hidden || this.inflight) return;
    const controller = new AbortController(); this.inflight = controller;
    const timeout = setTimeout(() => controller.abort(), 2000);
    try {
      const r = await fetch(this.endpoint, {cache: 'no-store', signal: controller.signal});
      if (!r.ok) throw Error('Meter stream unavailable');
      this.update(await r.json());
    } catch {
      this.clear('Disconnected', 'No fresh meter readings');
    } finally {
      clearTimeout(timeout); this.inflight = null;
      if (!this.stopped && !document.hidden) this.timer = setTimeout(() => this.poll(), 100);
    }
  }
  destroy() {
    this.stopped = true; clearTimeout(this.timer); this.inflight?.abort();
    document.removeEventListener('visibilitychange', this.visibility);
  }
}
