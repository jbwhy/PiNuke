// Own-host visibility. Fresh device confirmation, never meter freshness.
export class PresenceGate {
  constructor({graceMs = 2000} = {}) {
    this.graceMs = graceMs; this.visible = false; this.failedAt = null;
  }
  update(data, now) {
    const confirmed = data?.available === true && data.status === 'available'
      && Number.isFinite(data.age_ms) && data.age_ms >= 0 && data.age_ms <= 12000;
    if (confirmed) { this.visible = true; this.failedAt = null; }
    else {
      this.failedAt ??= now;
      if (now - this.failedAt >= this.graceMs) this.visible = false;
    }
    return this.visible;
  }
  remaining(now) {
    return this.failedAt === null ? null : Math.max(0, this.graceMs - (now - this.failedAt));
  }
}
