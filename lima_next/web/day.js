/* The daily answering-machine workflow. Preparation never executes an outward action. */
let daySnapshot=null, dayPreviewLoading=false, dayPollTimer, visibleDayJob, googleCalendars=[];
const dayHome=el('section',undefined,'panel day-home');
dayHome.innerHTML='<div class="section-title"><div><h2>Process my day</h2><p>Let Lima prepare the breakdown. Come back to review what happens next.</p></div></div><form id="process-day-form"><div class="field-row"><label>Day<input id="day-date" type="date" required></label><label>Project<select id="day-project" class="project-select" required></select></label></div><details><summary>What to include</summary><label class="background-choice"><input id="day-bee" type="checkbox"> Include this day’s unassigned Bee transcripts in the selected project</label><label>Default for new Bee imports<select id="day-mode"><option value="mixed">Mixed conversations and learning</option><option value="reference">Course / reference material</option><option value="work">Ongoing project work</option></select></label><p class="fine">Uses the latest transcript versions. Unknown-date Bee items are held for you to place manually. Saved recordings must finish transcription and be imported first. Existing sources assigned to other projects are not reassigned.</p></details><p id="day-scope" role="status">Choose a day and project.</p><details><summary>Included sources</summary><ul id="day-source-list"></ul><button id="day-refresh-preview" type="button" class="secondary">Refresh source list</button></details><label class="background-choice"><input id="day-cloud-consent" type="checkbox"> Process this displayed source snapshot with Meta Muse, including the selected project’s reviewed context. Prepare proposals only.</label><div class="actions"><button id="day-start">Process my day</button><button id="day-open-latest" type="button" class="secondary">Open daily review</button></div></form><p id="day-home-progress" role="status"></p>';
$('#home').prepend(dayHome);$('#day-date').value=chicagoDay();
const scopeLabel=el('label','Prepare');const scopeSelect=el('select');scopeSelect.id='process-scope';
for(const [value,label] of [['day','My day'],['meeting','One meeting now']]){const option=el('option',label);option.value=value;scopeSelect.append(option);}scopeLabel.append(scopeSelect);$('#process-day-form').prepend(scopeLabel);
const meetingLabel=el('label','Meeting transcript');meetingLabel.hidden=true;const meetingSelect=el('select');meetingSelect.id='meeting-source';meetingLabel.append(meetingSelect);scopeLabel.after(meetingLabel);
async function loadMeetingChoices(){
 const selected=meetingSelect.value;meetingSelect.replaceChildren();const project=$('#day-project').value;
 const bee=await api('/api/bee');const latest=new Set();
 for(const item of [...bee.items].sort((a,b)=>(b.captured_at||b.received_at).localeCompare(a.captured_at||a.received_at))){if(latest.has(item.conversation_id))continue;latest.add(item.conversation_id);
  if(item.imported_record&&!state.associations.some(a=>a.project_id===project&&a.record_id===item.imported_record))continue;
  const option=el('option','Bee '+item.conversation_id+' · '+(item.captured_at?new Date(item.captured_at).toLocaleString():'Date unknown')+' · '+item.characters.toLocaleString()+' characters');option.value='bee:'+item.id;meetingSelect.append(option);}
 for(const item of state.records.filter(r=>!bee.items.some(b=>b.imported_record===r.id)&&state.associations.some(a=>a.project_id===project&&a.record_id===r.id))){const option=el('option',item.external_id+' · imported source');option.value='record:'+item.id;meetingSelect.append(option);}
 if([...meetingSelect.options].some(o=>o.value===selected))meetingSelect.value=selected;
}
scopeSelect.onchange=()=>{dayHome.classList.toggle('meeting-mode',scopeSelect.value==='meeting');meetingLabel.hidden=scopeSelect.value!=='meeting';$('#day-date').closest('label').hidden=scopeSelect.value==='meeting';$('#day-start').textContent=scopeSelect.value==='meeting'?'Process this meeting':'Process my day';dayHome.querySelector('h2').textContent=scopeSelect.value==='meeting'?'Process now':'Process my day';refreshDayPreview().catch(e=>notify(e.message,true));};
meetingSelect.onchange=()=>refreshDayPreview().catch(e=>notify(e.message,true));

const dayPage=el('section');dayPage.id='day-review';dayPage.className='page';dayPage.hidden=true;
dayPage.innerHTML='<div class="actions"><button id="day-back" class="secondary">Back to Today</button><button id="day-refresh-report" class="secondary">Refresh review</button></div><p id="day-report-status" role="status"></p><progress id="day-progress" hidden></progress><div class="actions"><button id="day-stop" class="secondary" hidden>Stop after this section</button><button id="day-resume" class="secondary" hidden>Resume preparation</button></div><p class="fine">Muse drafts messages, contacts, calendar entries and Notion updates. Nothing is sent, posted or confirmed without your approval. Review project interpretations first. Changing project context can require a fresh preparation.</p><div id="day-results"></div><details id="google-setup" class="google-setup"><summary>Google connection</summary><p>Connect a dedicated Lima Desktop OAuth client. Gmail is used for drafts and sending explicitly approved emails. Calendar access is limited here to calendars you own and personal events without attendees or recurring-series edits.</p><label>Downloaded Desktop OAuth client JSON<input id="google-client-file" type="file" accept=".json,application/json"></label><p class="fine">Loaded locally and protected for this Windows account. Do not paste credentials into chat. See the setup guide for enabling the two Google APIs and adding your account as a test user.</p><div class="actions"><button id="google-signin" class="secondary">Sign in with Google</button><button id="google-check" class="secondary">Check connection</button></div><a id="google-signin-link" target="_blank" rel="noopener noreferrer" hidden>Open Google sign-in in your regular browser</a><p id="google-status" role="status"></p></details>';
document.querySelector('main').append(dayPage);
const googleSettingsButton=el('button','Google connection','secondary');googleSettingsButton.onclick=()=>{page('day-review');$('#google-setup').open=true;refreshGoogleConnection().catch(e=>notify(e.message,true));};$('.workspace-options').append(googleSettingsButton);

async function refreshGoogleConnection(){
 const connection=await api('/api/google');
 $('#google-status').textContent=connection.connected?'Connected as '+connection.email+'. Each write still needs your exact approval.':connection.configured?'Desktop client saved. Sign in with your Google account.':'Load the dedicated Lima Desktop OAuth JSON, then sign in.';
 if(connection.connected){const result=await api('/api/google-calendars');googleCalendars=result.calendars;}
 return connection;
}
$('#google-client-file').onchange=e=>busy($('#google-signin'),async()=>{const file=e.target.files[0];if(!file)return;if(file.size>30000)throw Error('Choose the small downloaded Desktop OAuth client JSON.');const json=await file.text();await api('/api/google-client',{client_json:json});e.target.value='';await refreshGoogleConnection();notify('Desktop client saved locally. Google sign-in has not yet been completed.');});
$('#google-signin').onclick=e=>busy(e.target,async()=>{const result=await api('/api/google-connect',{});$('#google-signin-link').href=result.url;$('#google-signin-link').hidden=false;$('#google-status').textContent='Complete sign-in and permission review in your regular browser, then click Check connection here.';});
$('#google-check').onclick=e=>busy(e.target,refreshGoogleConnection);

async function refreshDayPreview(){
 if(dayPreviewLoading||!$('#day-project').value)return;
 dayPreviewLoading=true;daySnapshot=null;$('#day-cloud-consent').checked=false;$('#day-cloud-consent').disabled=true;$('#day-start').disabled=true;$('#day-scope').textContent='Loading the selected source snapshot…';$('#day-source-list').replaceChildren();
 try{
  const meeting=scopeSelect.value==='meeting';
  if(meeting)await loadMeetingChoices();
  const choice=meetingSelect.value;
  if(meeting&&!choice)throw Error('No transcripts are available for this project yet. Sync Bee or import the meeting first.');
  const snapshot=meeting?await api('/api/meeting-preview',{project_id:$('#day-project').value,source_type:choice.split(':')[0],source_id:choice.split(':')[1],mode:$('#day-mode').value}):await api('/api/day-preview',{day:$('#day-date').value,project_id:$('#day-project').value,include_bee:$('#day-bee').checked,mode:$('#day-mode').value});
  // Ignore a response if the user has changed the selection during the read.
  if(meeting!==(scopeSelect.value==='meeting')||snapshot.project_id!==$('#day-project').value||(!meeting&&(snapshot.day!==$('#day-date').value||snapshot.include_bee!==$('#day-bee').checked))||snapshot.mode!==$('#day-mode').value|| (meeting&&choice!==meetingSelect.value)){dayPreviewLoading=false;return refreshDayPreview();}
  daySnapshot=snapshot;$('#day-scope').textContent=`${snapshot.sources.length} source versions for ${snapshot.project} on ${snapshot.day}.`+(snapshot.unknown_date_bee?` ${snapshot.unknown_date_bee} undated Bee items held.`:'');
  $('#day-source-list').replaceChildren();for(const source of snapshot.sources)$('#day-source-list').append(el('li',`${source.name} · ${source.characters.toLocaleString()} characters · ${source.date_basis} · ${source.mode||'mixed'}`));
 }finally{dayPreviewLoading=false;$('#day-cloud-consent').disabled=!daySnapshot;$('#day-start').disabled=!daySnapshot?.sources.length;}
}
function renderDayHome(){if(!daySnapshot&&!dayPreviewLoading&&$('#day-project').value)refreshDayPreview().catch(e=>{$('#day-scope').textContent=e.message;});}
for(const id of ['day-date','day-project','day-bee','day-mode'])$('#'+id).addEventListener('change',()=>refreshDayPreview().catch(e=>notify(e.message,true)));
$('#day-refresh-preview').onclick=e=>busy(e.target,refreshDayPreview);
$('#process-day-form').onsubmit=e=>{e.preventDefault();busy($('#day-start'),async()=>{if(!daySnapshot)throw Error('Refresh the source list first.');if(!$('#day-cloud-consent').checked)throw Error('Review the included sources and confirm Meta processing for this snapshot.');const job=await api('/api/day-start',{id:daySnapshot.id,cloud_consent:true});$('#day-cloud-consent').checked=false;await openDayReview(job.id);});};
$('#day-open-latest').onclick=e=>busy(e.target,async()=>{const jobs=await api('/api/day-jobs');if(!jobs.length)throw Error('Process a day first.');await openDayReview(jobs[0].id);});
$('#day-back').onclick=()=>page('home');
$('#day-refresh-report').onclick=e=>busy(e.target,async()=>{if(visibleDayJob)await loadDayReview(visibleDayJob);else await refreshGoogleConnection();});
$('#day-stop').onclick=e=>busy(e.target,async()=>{await api('/api/day-stop',{id:visibleDayJob});notify('Stopping after the current model section. Already prepared items are preserved.');});
$('#day-resume').onclick=e=>busy(e.target,async()=>{await api('/api/day-resume',{id:visibleDayJob});await openDayReview(visibleDayJob);});

async function openDayReview(identity){
 visibleDayJob=identity;page('day-review');clearTimeout(dayPollTimer);
 await refreshGoogleConnection().catch(e=>{$('#google-status').textContent=e.message;});
 await loadDayReview(identity);
}
async function loadDayReview(identity){
 const job=await api('/api/day-jobs/'+identity);if(visibleDayJob!==identity)return;
 const running=['running','queued'].includes(job.status);
 $('#day-report-status').textContent=`${job.project} · ${job.day} · ${job.status}. ${job.stage}`+(job.context_changed?' Project context changed; refresh preparation before using stale items.':'');
 $('#day-home-progress').textContent=`${job.day}: ${job.status} · ${job.processed}/${job.total} preparation steps.`;
 $('#day-progress').hidden=!running;$('#day-progress').max=job.total||1;$('#day-progress').value=job.processed;
 $('#day-stop').hidden=!running;$('#day-resume').hidden=!['partial','failed','cancelled','interrupted'].includes(job.status);
 if(running){dayPollTimer=setTimeout(()=>loadDayReview(identity).catch(e=>notify(e.message,true)),2000);return;}
 clearTimeout(dayPollTimer);
 await refresh();const proposals=[];const reports=[];for(let offset=0;offset<job.action_ids.length;offset+=100)proposals.push(...(await api('/api/day-actions',{ids:job.action_ids.slice(offset,offset+100)})).items);for(let offset=0;offset<job.report_ids.length;offset+=100)reports.push(...(await api('/api/day-comparisons',{ids:job.report_ids.slice(offset,offset+100)})).items);const draftSummaries=await api('/api/drafts');
 const box=$('#day-results');box.replaceChildren();
 const summary=el('div',undefined,'panel');summary.append(el('h2',job.scope==='meeting'?'Your meeting follow-ups':'Your daily breakdown'),el('p',`${job.sources.length} source${job.sources.length===1?'':'s'} · ${job.report_ids.length} comparison report${job.report_ids.length===1?'':'s'} · ${job.draft_ids.length} proposed note${job.draft_ids.length===1?'':'s'} · ${job.action_ids.length} follow-up proposals`));
 const projectState=state.projects.find(p=>p.id===job.project_id);const sourceRecords=new Set(Object.values(job.records));
 const pending=(projectState?.history||[]).filter(c=>sourceRecords.has(c.record_id)&&c.review==='pending');
 summary.append(el('p',`${reviewUnits(pending)} review decisions remain (${pending.length} supporting interpretations). They have not become confirmed work.`));
 if(pending.length){const pendingDetails=el('details');pendingDetails.append(el('summary','Interpretations to review'));
  for(const source of job.sources){const record=job.records[source.id];const count=pending.filter(c=>c.record_id===record).length;if(!count)continue;const button=el('button',`${source.name} · ${count} to review`,'record-button');button.onclick=()=>{reviewFilter=job.project_id+':'+record;render();page('review');};pendingDetails.append(button);}summary.append(pendingDetails);}
 const sourceDetails=el('details');sourceDetails.append(el('summary','Review conversations and work interpretations'));
 for(const source of job.sources){const record=job.records[source.id];if(!record)continue;const button=el('button',source.name,'record-button');button.onclick=()=>busy(button,()=>openRecord(record,job.project_id));sourceDetails.append(button);}
 summary.append(sourceDetails);
 if(job.errors.length){const errors=el('details');errors.append(el('summary',`${job.errors.length} preparation problems to inspect`));for(const error of job.errors)errors.append(el('p',`${error.source} · ${error.stage}: ${error.reason}`));summary.append(errors);}
 const coverage=el('div',undefined,'day-coverage');coverage.append(el('h3','Your sessions and conversations'));
 for(const source of job.sources){const record=job.records[source.id];if(!record)continue;const claims=(projectState?.history||[]).filter(c=>c.record_id===record&&c.review!=='rejected');const categories=new Map();for(const c of claims){const category=c.context_category||'uncertain';if(!categories.has(category))categories.set(category,[]);categories.get(category).push(c);}
  const entry=el('div',undefined,'session-overview');entry.append(el('strong',source.name));for(const [category,items] of categories){const label={class:'Class lesson',meeting:'Meeting',conversation:'Conversation',personal:'Personal',uncertain:'Needs sorting'}[category]||'Needs sorting';const waiting=items.filter(c=>c.review==='pending').length;entry.append(el('p',`${label} · ${items.length} supporting points · ${waiting} awaiting review`,'fine'));}const open=el('button','Review this recording','secondary');open.onclick=()=>{reviewFilter=job.project_id+':'+record;render();page('review');};entry.append(open);coverage.append(entry);
 }summary.append(coverage);if(!job.action_ids.length)summary.append(el('p','No outgoing drafts were proposed. Check possible requests and assignments before concluding nothing needs follow-up.','fine'));
 box.append(summary);
 const newestReports=new Map();for(const report of reports){const old=newestReports.get(report.record_id);if(!old||(report.prompt_version||0)>(old.prompt_version||0)||report.prompt_version===old.prompt_version&&report.created_at>old.created_at)newestReports.set(report.record_id,report);}
 if(job.report_ids.length){const comparisons=el('details',undefined,'panel');comparisons.append(el('summary','What may have changed, and what needs clarification'));
  for(const report of newestReports.values()){const meaningful=report.sections.some(s=>s.items.some(i=>i.kind!=='reference'));if(meaningful)comparisons.append(reconciliationCard(report));else{comparisons.append(el('p',`${state.records.find(r=>r.id===report.record_id)?.external_id||'Recording'}: no material changes or clarification questions proposed.`,'fine'));if(report.sections.some(s=>s.items.length)){const reference=el('details');reference.append(el('summary','Reference overlap with existing notes'),reconciliationCard(report));comparisons.append(reference);}}}const older=reports.filter(r=>newestReports.get(r.record_id)?.id!==r.id);if(older.length){const history=el('details');history.append(el('summary',`Earlier comparison reports · ${older.length}`));for(const report of older)history.append(reconciliationCard(report));comparisons.append(history);}box.append(comparisons);}
 const repository=el('div',undefined,'panel');repository.append(el('h2','Notion daily repository'),el('p','Muse drafts a daily review with evidence and a snapshot of follow-up destinations and receipts. Refresh after sending or amending actions; publishing still needs exact approval.'));
 const noteConsent=el('input');noteConsent.type='checkbox';const noteLabel=el('label','Allow Muse to draft from this day’s interpretations and current reviewed project context');noteLabel.prepend(noteConsent);repository.append(noteLabel);
 const prepareNote=el('button','Draft / refresh Muse daily note','secondary');prepareNote.onclick=()=>busy(prepareNote,async()=>{if(!noteConsent.checked)throw Error('Confirm Meta drafting for this daily repository note first.');const note=await api('/api/day-note',{id:job.id,cloud_consent:true});if(!note)throw Error('No supported evidence or follow-ups are available for a note yet.');page('drafts');await refreshDrafts();showDraft(note);});repository.append(prepareNote);box.append(repository);
 if(job.historical_draft_ids?.length){const history=el('details',undefined,'panel');history.append(el('summary',`Earlier proposed notes · ${job.historical_draft_ids.length}`));for(const id of job.historical_draft_ids){const b=el('button',draftSummaries.find(d=>d.id===id)?.subject||'Earlier note','record-button');b.onclick=()=>busy(b,async()=>{page('drafts');await refreshDrafts();showDraft(await api('/api/drafts/'+id));});history.append(b);}box.append(history);}
 if(job.draft_ids.length){const notes=el('div',undefined,'panel');notes.append(el('h2','Notes for review and Notion'));
  for(const draftId of job.draft_ids){const button=el('button',draftSummaries.find(d=>d.id===draftId)?.subject||'Open proposed follow-up note','record-button');button.onclick=()=>busy(button,async()=>{const draft=await api('/api/drafts/'+draftId);page('drafts');await refreshDrafts();showDraft(draft);});notes.append(button);}box.append(notes);}
 const actionList=el('div');actionList.append(el('h2','Muse follow-ups for review'));
 for(const identity of job.action_ids){const action=proposals.find(a=>a.id===identity);if(action)actionList.append(outgoingCard(action));}
 if(!job.action_ids.length)actionList.append(el('p','No supported email or calendar proposals were prepared. Missing or uncertain follow-ups can remain questions.'));
 box.append(actionList);
}

function outgoingCard(initial){
 if(['contact','text'].includes(initial.kind))return communicationCard(initial);
 let action=initial,currentPlan=null;
 const card=el('article',undefined,'panel outgoing-card');
 card.append(el('h3',action.subject),badge(action.kind==='email'?'Email draft':action.kind==='calendar_create'?'New personal event':'Update personal event'));
 const status=el('p',action.stale?'Project context changed. Prepare the day again before delivery.':action.dismissed?'Dismissed':'Proposed. Review and fill any missing details.','fine');card.append(status);
 const evidence=el('details');evidence.open=true;evidence.append(el('summary','Original evidence'),el('blockquote',action.evidence.quote),el('small',action.evidence.external_id,'fine'));card.append(evidence);
 const form=el('form');
 function field(label,key,type='input'){const wrapper=el('label',label),input=el(type);input.value=action[key]||'';input.name=key;if(type==='textarea')input.rows=6;wrapper.append(input);form.append(wrapper);return input;}
 const subject=field(action.kind==='email'?'Subject':'Event title','subject');subject.required=true;subject.maxLength=200;
 const body=field(action.kind==='email'?'Email text':'Event notes','body','textarea');body.required=action.kind==='email';
 let recipient,cc,bcc,calendar,start,end,zone,eventSelect;
 if(action.kind==='email'){
  recipient=field('To (complete addresses, separated by commas)','to');recipient.value=action.to.join(', ');
  const more=el('details');more.append(el('summary','Cc and Bcc'));cc=field('Cc','cc');bcc=field('Bcc','bcc');cc.value=action.cc.join(', ');bcc.value=action.bcc.join(', ');more.append(cc.closest('label'),bcc.closest('label'));form.append(more);
 }else{
  const label=el('label','Your calendar');calendar=el('select');calendar.name='calendar_id';const blank=el('option',googleCalendars.length?'Choose a calendar you own':'Connect Google to load calendars');blank.value='';calendar.append(blank);
  for(const cal of googleCalendars){const option=el('option',cal.name);option.value=cal.id;calendar.append(option);}calendar.value=action.calendar_id;label.append(calendar);form.append(label);
  start=field('Start (YYYY-MM-DDTHH:MM, or include an explicit offset)','start');start.placeholder='2026-11-03T14:00';end=field('End','end');end.placeholder='2026-11-03T15:00';zone=field('Time zone','timezone');
  form.append(el('p','Exact times need your review. Ambiguous or missing dates are held. Availability checks cover calendars you own; shared calendars are outside this release.','fine'));
  if(action.kind==='calendar_update'){
   const lookupLabel=el('label','Find the existing personal event on');const lookup=el('input');lookup.type='date';lookup.value=$('#day-date').value;lookupLabel.append(lookup);form.append(lookupLabel);
   const load=el('button','Find personal events','secondary');load.type='button';form.append(load);
   const eventLabel=el('label','Exact event to update');eventSelect=el('select');eventSelect.name='event_id';let option=el('option','Choose an event');option.value='';eventSelect.append(option);
   if(action.event_id){option=el('option','Previously selected event (reload to inspect)');option.value=action.event_id;eventSelect.append(option);eventSelect.value=action.event_id;}eventLabel.append(eventSelect);form.append(eventLabel);
   let events=[];
   load.onclick=()=>busy(load,async()=>{if(!calendar.value||!lookup.value)throw Error('Choose a calendar and lookup day.');const next=new Date(lookup.value+'T12:00:00Z');next.setUTCDate(next.getUTCDate()+1);const high=next.toISOString().slice(0,10);const result=await api('/api/google-events',{calendar_id:calendar.value,start:lookup.value+'T00:00',end:high+'T00:00',timezone:zone.value});events=result.events;eventSelect.replaceChildren();const none=el('option','Choose an event');none.value='';eventSelect.append(none);for(const item of events.filter(e=>e.can_update)){const o=el('option',item.title+' · '+(item.start?.dateTime||item.start?.date||''));o.value=item.id;eventSelect.append(o);}if(result.more)notify('Only the first 100 events are shown. Refine the date if needed.');});
   eventSelect.onchange=()=>{const selected=events.find(e=>e.id===eventSelect.value);if(selected){if(!start.value)start.value=selected.start?.dateTime||'';if(!end.value)end.value=selected.end?.dateTime||'';}currentPlan=null;previewBox.hidden=true;};
  }
 }
 const save=el('button','Save amendments','secondary');save.type='submit';form.append(save);card.append(form);
 const previewBox=el('div',undefined,'action-preview');previewBox.hidden=true;
 function payload(){return {kind:action.kind,subject:subject.value,body:body.value,to:recipient?recipient.value:[],cc:cc?cc.value:[],bcc:bcc?bcc.value:[],calendar_id:calendar?.value||'',event_id:eventSelect?.value||'',start:start?.value||'',end:end?.value||'',timezone:zone?.value||'America/Chicago'};}
 async function saveCurrent(){action=await api('/api/outgoing-edit',{id:action.id,version_id:action.version_id,payload:payload()});currentPlan=null;previewBox.hidden=true;return action;}
 form.onsubmit=e=>{e.preventDefault();busy(save,async()=>{await saveCurrent();const replacement=outgoingCard(action);replacement.querySelector('.action-review').open=true;card.replaceWith(replacement);notify('Amendments saved locally. A new exact preview is required before delivery.');});};
 form.addEventListener('input',()=>{currentPlan=null;previewBox.hidden=true;});form.addEventListener('change',()=>{currentPlan=null;previewBox.hidden=true;});
 const controls=el('div',undefined,'actions');
 const hasReceipt=action.receipts.some(r=>['sending','unknown','completed'].includes(r.status));if(hasReceipt){save.disabled=true;for(const input of form.querySelectorAll('input,textarea,select'))input.disabled=true;status.textContent='This version has a delivery receipt. Inspect the result below before any further action.';}
 for(const [label,operation] of action.kind==='email'?[['Preview Gmail draft','gmail_draft'],['Preview sending email','gmail_send']]:[[action.kind==='calendar_create'?'Preview adding event':'Preview event update',action.kind]]){
  const button=el('button',label,'secondary');button.disabled=action.stale||action.dismissed||hasReceipt;
  button.onclick=()=>busy(button,async()=>{await saveCurrent();currentPlan=await api('/api/outgoing-preview',{id:action.id,version_id:action.version_id,operation});renderPreview();});controls.append(button);
 }
 const dismiss=el('button','Dismiss','secondary');dismiss.disabled=action.dismissed||hasReceipt;dismiss.onclick=()=>busy(dismiss,async()=>{action=await api('/api/outgoing-dismiss',{id:action.id,version_id:action.version_id});card.replaceWith(outgoingCard(action));});controls.append(dismiss);card.append(controls,previewBox);
 for(const receipt of action.receipts.filter(r=>r.status!=='prepared')){const text=el('p',receipt.status==='completed'?(receipt.operation==='gmail_draft'?'Saved to Gmail as an unsent draft. Complete it in Gmail.':receipt.operation==='gmail_send'?'Google acknowledged sending this approved email.':'Calendar write and read-back completed.'):receipt.status==='rejected'?'Google rejected the action. Fix the connection or fields and prepare a fresh preview.':'Delivery unconfirmed. Inspect Gmail or Calendar; Lima will not retry automatically.','fine');card.append(text);if(receipt.result?.url){const link=el('a','Open in Google');link.href=receipt.result.url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}}
 function renderPreview(){
  previewBox.hidden=false;previewBox.replaceChildren();const plan=currentPlan,value=plan.value;
  previewBox.append(el('h3',plan.operation==='gmail_send'?'Review before sending':plan.operation==='gmail_draft'?'Review unsent Gmail draft':'Review calendar change'),el('p','Google account: '+plan.account_email));
  if(action.kind==='email')previewBox.append(el('pre',`To: ${value.to.join(', ')}\nCc: ${value.cc.join(', ')}\nBcc: ${value.bcc.join(', ')}\nSubject: ${value.subject}\n\n${value.body}`,'brief-text'));
  else{
   previewBox.append(el('p','Calendar: '+(googleCalendars.find(c=>c.id===value.calendar_id)?.name||value.calendar_id)),el('pre',`${value.subject}\n${value.start} → ${value.end}\nTime zone: ${value.timezone}\n\n${value.body}`,'brief-text'));
   if(plan.before){const before=el('details');before.append(el('summary','Existing event being replaced'),el('pre',`${plan.before.summary||''}\n${plan.before.start?.dateTime||plan.before.start?.date||''} → ${plan.before.end?.dateTime||plan.before.end?.date||''}\n\n${plan.before.description||''}`,'brief-text'));previewBox.append(before);}
  }
  const conflicts=el('input');conflicts.type='checkbox';
  if(plan.conflicts.length){previewBox.append(el('h3','Calendar overlaps'));for(const conflict of plan.conflicts)previewBox.append(el('p',`${conflict.title} · ${conflict.start?.dateTime||conflict.start?.date||''}`));const label=el('label','I reviewed these overlaps and still want this time');label.prepend(conflicts);previewBox.append(label);}
  const prior=el('input');prior.type='checkbox';if(plan.prior_deliveries?.length){previewBox.append(el('h3','Earlier follow-ups from this passage'));for(const receipt of plan.prior_deliveries)previewBox.append(el('p',receipt.operation+' · '+receipt.status));const label=el('label','I checked those earlier deliveries and intentionally want this additional action');label.prepend(prior);previewBox.append(label);}const approve=el('input');approve.type='checkbox';const approval=el('label',action.kind==='email'?'Approve exactly this operation, message and recipients':'Approve exactly this personal calendar change');approval.prepend(approve);previewBox.append(approval);
  previewBox.append(el('p','This preview expires in 15 minutes. Changing the message, recipients, event or project context requires a fresh preview.','fine'));
  const execute=el('button',plan.operation==='gmail_send'?'Send approved email':plan.operation==='gmail_draft'?'Save approved Gmail draft':'Apply approved calendar change');
  execute.onclick=()=>busy(execute,async()=>{if(!currentPlan||currentPlan.id!==plan.id||!approve.checked)throw Error('Review and approve this exact action first.');try{const result=await api('/api/outgoing-execute',{id:plan.id,confirmed:true,acknowledge_conflicts:conflicts.checked,acknowledge_prior:prior.checked});const updated=(await api('/api/day-actions',{ids:[action.id]})).items[0];card.replaceWith(outgoingCard(updated));notify(result.operation==='gmail_draft'?'Unsent Gmail draft created.':result.operation==='gmail_send'?'Google acknowledged the approved email send.':'Calendar change and read-back completed.');}catch(error){try{const updated=(await api('/api/day-actions',{ids:[action.id]})).items[0];card.replaceWith(outgoingCard(updated));}catch{}throw error;}});previewBox.append(execute);
 }
 const review=el('details',undefined,'action-review');review.append(el('summary',hasReceipt?'Inspect delivery receipt':'Review and amend'));for(const child of [...card.children].slice(3))review.append(child);card.append(review);return card;
}
if(state)render();
api('/api/day-jobs').then(jobs=>{if(jobs.length)$('#day-home-progress').textContent=`Latest day: ${jobs[0].day} · ${jobs[0].status}. Open daily review to continue.`;}).catch(()=>{});

const quickWorkspaceActions=el('details',undefined,'quick-workspace-actions');quickWorkspaceActions.append(el('summary','Other workspace actions'),$('.today-flow'));dayHome.after(quickWorkspaceActions);

const meetingNow=el('button','Process this meeting','secondary');meetingNow.type='button';$('#associate').parentElement.append(meetingNow);
meetingNow.onclick=()=>busy(meetingNow,async()=>{if(!selectedRecord)throw Error('Open a source first.');const project=$('#source-project').value;page('home');$('#day-project').value=project;scopeSelect.value='meeting';dayHome.classList.add('meeting-mode');meetingLabel.hidden=false;$('#day-date').closest('label').hidden=true;$('#day-start').textContent='Process this meeting';dayHome.querySelector('h2').textContent='Process now';await loadMeetingChoices();meetingSelect.value='record:'+selectedRecord.id;await refreshDayPreview();dayHome.scrollIntoView({behavior:'smooth'});});
