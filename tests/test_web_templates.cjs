// Pure template tests; these do not automate or claim to render a browser.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({state:{groups:[],config:{assistantReady:false}},esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
vm.runInContext(fs.readFileSync('web/helper.js','utf8'),context);
let html=vm.runInContext('helperPanel()',context);
assert.match(html,/Getting started \/ goal planning/);
assert.match(html,/AI is not configured yet/);
assert.match(html,/Compare a one-time goal/);
vm.runInContext(`helperMessages=[{role:'assistant',content:'<img src=x onerror=alert(1)>'}]; helperChats=[{id:'safe',title:'<script>bad()</script>'}];`,context);
html=vm.runInContext('helperPanel()',context);
assert(!html.includes('<img src=x'));
assert(!html.includes('<script>bad()'));
assert(html.includes('&lt;img'));
assert(html.includes('&lt;script&gt;'));
console.log('Helper onboarding and untrusted-text template checks passed.');

assert.match(html,/helper-consent/);
vm.runInContext('state.assistantConsent=true',context);
html=vm.runInContext('helperPanel()',context);
assert(!html.includes('id="helper-consent"'));
assert.match(html,/Revoke AI data-sharing consent/);

const elements={
  'helper-form':{requestSubmit(){this.sent=(this.sent||0)+1;}},
  'helper-message':{value:'Hello'},'helper-scope':{},
  'chat-messages':{scrollHeight:100,scrollTop:0}
};
context.$=id=>elements[id];
vm.runInContext('mountHelper()',context);
let prevented=false;
elements['helper-message'].onkeydown({key:'Enter',shiftKey:true,isComposing:false,preventDefault(){prevented=true;}});
assert.equal(elements['helper-form'].sent,undefined);
assert.equal(prevented,false);
elements['helper-message'].onkeydown({key:'Enter',shiftKey:false,isComposing:true,preventDefault(){prevented=true;}});
assert.equal(elements['helper-form'].sent,undefined);
elements['helper-message'].onkeydown({key:'Enter',shiftKey:false,isComposing:false,preventDefault(){prevented=true;}});
assert.equal(elements['helper-form'].sent,1);
assert.equal(prevented,true);
console.log('Consent display and Enter/Shift+Enter/composition behavior passed.');
