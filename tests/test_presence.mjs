import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../pinuke/static/presence.js', import.meta.url));
const {PresenceGate} = await import('data:text/javascript;base64,' + source.toString('base64'));
const yes = {available:true,status:'available',age_ms:20};
const gate = new PresenceGate();
assert.equal(gate.update(null, 0), false); // Initial offline never renders a card.
assert.equal(gate.update(yes, 10), true);
assert.equal(gate.update({...yes, levels:null, meter_status:'stale'}, 20), true);
assert.equal(gate.update({available:false,status:'unavailable'}, 30), true);
assert.equal(gate.remaining(1030), 1000);
assert.equal(gate.update(yes, 1500), true); // Brief loss recovered, no flicker.
assert.equal(gate.remaining(1500), null);
assert.equal(gate.update(null, 2000), true);
assert.equal(gate.update(null, 3999), true);
assert.equal(gate.update(null, 4000), false); // Sustained loss hides.
assert.equal(gate.update(yes, 4001), true);
assert.equal(gate.update({...yes,age_ms:13000}, 4002), true);
assert.equal(gate.update({...yes,age_ms:13000}, 6002), false); // Old confirmation expires.
for (const data of [{available:true}, {...yes,age_ms:null}, {...yes,age_ms:-1}, {...yes,status:'unknown'}]) {
 const fresh = new PresenceGate(); assert.equal(fresh.update(data, 0), false);
}
const css=readFileSync(new URL('../pinuke/static/pip.css',import.meta.url),'utf8');
assert.ok(css.includes('[data-pinuke-pip][hidden]{display:none}'));
for(const external of ['#pip-card','.pi-listen-row','.pip-anchor']) assert.ok(!css.includes(external));
console.log('Conditional presence and own-area scope checks passed');
