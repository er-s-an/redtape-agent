// Regression: arbitrary real model options must not inherit old demo labels.
// Uses Node built-ins only. No browser, model, network, or generated state.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../redtape/static/index.html',import.meta.url),'utf8');
const scripts=[...source.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join('\n');
new vm.Script(scripts);
const nodes=new Map();
const context={window:{},$:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);},esc:x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),prettyDate:x=>x};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function exactSubmissionProblem'),source.indexOf('async function resolve')),context);
const choice={label:'Recommended later option',slot_id:'S-1017',processing_tier:'expedited',fee_usd:97,expected_in_hand:'2026-11-14',trip_margin_days:6};
const decision={id:7,kind:'model_generated_booking_choice',context:{context:'Synthetic regression fixture'},options:[choice,{label:'Take the later expedited appointment',slot_id:'S-1031'},{label:'Renew the license before surrendering the passport',slot_id:null}]};
context.renderInbox([decision],[],true);
const inbox=nodes.get('inbox').innerHTML;
assert(inbox.includes(decision.options[1].label)&&inbox.includes(decision.options[2].label));
assert(!inbox.includes('Choose $23 regular processing')&&!inbox.includes('Wait for an earlier slot'));
assert(inbox.includes('$97')&&inbox.includes('2026-11-14')&&inbox.includes('6 days'));
context.renderInbox([],[{action:'decision_resolved',detail:{choice}},{action:'appointment_booked',detail:{slot_id:'S-1017',date:'2026-10-17',time:'13:00',confirmation:'CNF-TEST'}}],true);
const receipt=nodes.get('inbox').innerHTML;
assert(receipt.includes('CNF-TEST')&&receipt.includes('2026-10-17')&&receipt.includes('2026-11-14')&&receipt.includes('$97')&&receipt.includes('6 days'));
assert(!receipt.includes('October 3')&&!receipt.includes('20 days'));
console.log('PASS: script syntax, actual alternative labels, structured option values, matching receipt fields, no stale fixed receipt values.');
