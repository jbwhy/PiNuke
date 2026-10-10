import {MeterPanel} from './meters.js';
import {PresenceGate} from './presence.js';

// Homepage integration: fixed same-origin source, no external device endpoints.
export function mountPiNUKE(host) {
  if (host.dataset.pinukeMounted) return;
  host.dataset.pinukeMounted = 'true';
  host.hidden = true;
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'pinuke-pip';
  button.setAttribute('aria-label', 'Open PiNuke amplifier controls');
  button.setAttribute('aria-haspopup', 'dialog');
  const header = document.createElement('div'); header.className = 'pinuke-pip-header';
  const title = document.createElement('span'); title.className = 'pinuke-pip-wordmark'; title.textContent = 'PiNuke';
  const amp = document.createElement('span'); amp.className = 'pinuke-pip-model'; amp.textContent = 'NU6000DSP';
  header.append(title, amp);
  const meterHost = document.createElement('div');
  button.append(header, meterHost); host.append(button);
  let panel = null;
  const startPanel = () => {
    if (!panel && !host.hidden && !dialog.open)
      panel = new MeterPanel(meterHost, {compact: true, endpoint: '/pinuke/api/meters'});
  };
  const stopPanel = () => { panel?.destroy(); panel = null; meterHost.replaceChildren(); };
  let dirty = false, loaded = false;
  const dialog = document.createElement('dialog'); dialog.className = 'pinuke-dialog';
  dialog.setAttribute('aria-label', 'PiNuke amplifier control');
  const frame = document.createElement('iframe'); frame.title = 'PiNuke amplifier controls';
  dialog.append(frame); document.body.append(dialog);
  const requestHome = () => {
    if (loaded) frame.contentWindow.postMessage({type: 'pinuke-request-home'}, window.location.origin);
    else close();
  };
  const close = () => {
    dirty = false; loaded = false; dialog.close(); frame.src = 'about:blank';
    startPanel();
    if (!host.hidden) button.focus({preventScroll: true});
  };
  frame.addEventListener('load', () => { loaded = frame.getAttribute('src') === '/pinuke/'; });
  button.addEventListener('click', () => {
    if (host.hidden) return;
    stopPanel(); loaded = false;
    dialog.showModal();
    frame.src = '/pinuke/';
    // Focus the editor surface, not the π link. No arrival outline on the icon.
    frame.focus();
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); requestHome(); });
  window.addEventListener('message', event => {
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow || !dialog.open) return;
    if (event.data?.type === 'pinuke-dirty') dirty = event.data.dirty === true;
    if (event.data?.type === 'pinuke-home') close();
  });
  const gate = new PresenceGate();
  let timer = null, inflight = null, hideTimer = null;
  const setPresence = data => {
    clearTimeout(hideTimer);
    const now = performance.now();
    host.hidden = !gate.update(data, now);
    if (host.hidden) stopPanel(); else startPanel();
    const remaining = gate.remaining(now);
    if (remaining !== null && gate.visible) hideTimer = setTimeout(() => {
      host.hidden = !gate.update(data, performance.now());
      if (host.hidden) stopPanel();
      // An open editor is retained so pending edits are not discarded.
    }, remaining);
  };
  const pollAvailability = async () => {
    clearTimeout(timer);
    if (document.hidden || inflight) return;
    const controller = new AbortController(); inflight = controller;
    const timeout = setTimeout(() => controller.abort(), 2500);
    try {
      const r = await fetch('/pinuke/api/availability', {cache: 'no-store', signal: controller.signal});
      if (!r.ok) throw Error('Availability unknown');
      setPresence(await r.json());
    } catch { setPresence(null); }
    finally {
      clearTimeout(timeout); inflight = null;
      if (!document.hidden) timer = setTimeout(pollAvailability, 2000);
    }
  };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearTimeout(timer); inflight?.abort(); }
    else pollAvailability();
  });
  pollAvailability();
  window.addEventListener('beforeunload', event => { if (dialog.open && dirty) { event.preventDefault(); event.returnValue = ''; } });
}

document.querySelectorAll('[data-pinuke-pip]').forEach(mountPiNUKE);
