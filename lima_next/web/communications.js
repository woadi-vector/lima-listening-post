/* Muse contact proposals and copyable text drafts use the same versioned queue. */
function communicationCard(initial){
 let action=initial,plan=null;const card=el('article',undefined,'panel outgoing-card');
 card.append(el('h3',action.subject),badge(action.kind==='contact'?'Google contact proposal':'Text message draft'));
 const frozen=action.receipts.some(r=>['sending','unknown','completed'].includes(r.status));
 card.append(el('p',action.stale?'Project context changed. Prepare again before delivery.':action.kind==='text'?'Copy this draft into your messaging app. Lima cannot send SMS.':'Review literal contact details before adding to your Google account.','fine'));
 const details=el('details');details.append(el('summary','Review and amend'),el('blockquote',action.evidence.quote));
 const form=el('form');const fields={};
 for(const [key,label] of [['subject','Title'],['contact_name','Name'],['contact_email','Email'],['phone','Phone, including country code'],['body',action.kind==='text'?'Message text':'Local context note']]){
  const wrapper=el('label',label);const input=el(key==='body'?'textarea':'input');input.value=action[key]||'';input.disabled=frozen;fields[key]=input;wrapper.append(input);form.append(wrapper);
 }
 const save=el('button','Save amendments','secondary');save.disabled=frozen;form.append(save);details.append(form);
 async function saveCurrent(){const payload={...action};for(const [key,input] of Object.entries(fields))payload[key]=input.value;action=await api('/api/outgoing-edit',{id:action.id,version_id:action.version_id,payload});plan=null;previewBox.replaceChildren();}
 form.onsubmit=e=>{e.preventDefault();busy(save,async()=>{await saveCurrent();notify('Draft amendments saved.');});};
 const previewBox=el('div');const controls=el('div',undefined,'actions');
 if(action.kind==='text'){
  const copy=el('button','Copy message','secondary');copy.disabled=action.stale||action.dismissed;
  copy.onclick=()=>busy(copy,async()=>{await saveCurrent();await navigator.clipboard.writeText(action.body);notify('Message copied. Review the recipient and send it yourself in your messaging app.');});controls.append(copy);
 }else{
  const preview=el('button','Preview Google contact','secondary');preview.disabled=frozen||action.stale||action.dismissed;
  preview.onclick=()=>busy(preview,async()=>{await saveCurrent();plan=await api('/api/outgoing-preview',{id:action.id,version_id:action.version_id,operation:'contact_create'});const thisPlan=plan;
   previewBox.append(el('h3','Approve this contact'),el('p','Google Contacts account: '+plan.account_email),el('pre',`${plan.value.contact_name}\n${plan.value.contact_email}\n${plan.value.phone}`,'brief-text'));
   const prior=el('input');prior.type='checkbox';if(plan.prior_deliveries?.length){const priorLabel=el('label','I checked prior contact receipts from this passage and intentionally want this additional contact');priorLabel.prepend(prior);previewBox.append(priorLabel);}
   const check=el('input');check.type='checkbox';const label=el('label','I approve these exact details in this Google account');label.prepend(check);previewBox.append(label);
   const execute=el('button','Add approved Google contact');execute.onclick=()=>busy(execute,async()=>{if(plan?.id!==thisPlan.id||!check.checked)throw Error('Review and approve this exact contact first.');try{await api('/api/outgoing-execute',{id:thisPlan.id,confirmed:true,acknowledge_prior:prior.checked});const next=(await api('/api/day-actions',{ids:[action.id]})).items[0];card.replaceWith(communicationCard(next));notify('Google contact created and read back.');}catch(error){const next=(await api('/api/day-actions',{ids:[action.id]})).items[0];card.replaceWith(communicationCard(next));throw error;}});previewBox.append(execute);
  });controls.append(preview);
 }
 const dismiss=el('button','Dismiss','secondary');dismiss.disabled=frozen||action.dismissed;dismiss.onclick=()=>busy(dismiss,async()=>{action=await api('/api/outgoing-dismiss',{id:action.id,version_id:action.version_id});card.replaceWith(communicationCard(action));});controls.append(dismiss);
 for(const input of Object.values(fields))input.addEventListener('input',()=>{plan=null;previewBox.replaceChildren();});
 details.append(controls,previewBox);
 for(const receipt of action.receipts.filter(r=>r.status!=='prepared')){details.append(el('p',receipt.status==='completed'?'Contact creation and read-back completed.':receipt.status==='rejected'?'Google rejected this action. Fix the connection or fields before a fresh preview.':'Contact delivery unconfirmed. Inspect Google Contacts; Lima will not retry automatically.','fine'));if(receipt.result?.url){const link=el('a','Open Google Contacts');link.href=receipt.result.url;link.target='_blank';link.rel='noopener noreferrer';details.append(link);}}
 card.append(details);return card;
}
const contactsConnect=el('button','Enable Google Contacts permission','secondary');contactsConnect.onclick=e=>busy(e.target,async()=>{const result=await api('/api/google-connect',{include_contacts:true});$('#google-signin-link').href=result.url;$('#google-signin-link').hidden=false;$('#google-status').textContent='Enable People API in the Lima Google Cloud project, then complete this additional Google Contacts permission in your regular browser.';});$('#google-setup').append(el('p','Optional: contact creation needs People API enabled and additional Google Contacts access. Existing Gmail/Calendar access is unchanged until you reconnect.'),contactsConnect);
