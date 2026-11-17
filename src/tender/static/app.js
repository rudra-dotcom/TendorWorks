const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const words = value => String(value ?? '').replaceAll('_', ' ');
const money = value => value == null ? 'Unresolved' : new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR',maximumFractionDigits:0}).format(Number(value));
const num = value => value == null ? '—' : new Intl.NumberFormat('en-IN', {maximumFractionDigits:3}).format(Number(value));
const badge = (text, kind = text) => `<span class="badge ${esc(kind)}">${esc(words(text))}</span>`;
const state = {config:null, projects:[], result:null, tab:'overview', view:'projects', poll:null, routeVersion:0, blobURLs:[]};
const main = $('#main');

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = sessionStorage.getItem('tender-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  const response = await fetch(`/api${path}`, {...options, headers});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || `Request failed (${response.status})`));
    error.status = response.status;
    throw error;
  }
  if (options.download) return response.blob();
  return response.json();
}
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.className = `visible${error ? ' error' : ''}`;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = '', 5500);
}
function bind(action, fn, root = main) {
  $$(`[data-action="${action}"]`, root).forEach(el => el.addEventListener('click', async event => {
    event.preventDefault();
    try { await fn(el, event); } catch (error) { toast(error.message, true); }
  }));
}
function modal(title, content, eyebrow = 'PROJECT DETAIL') {
  $('#dialog-eyebrow').textContent = eyebrow;
  $('#dialog-body').innerHTML = `<h2>${esc(title)}</h2>${content}`;
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
}
$('#dialog-close').addEventListener('click', () => $('#detail-dialog').close());
$('#detail-dialog').addEventListener('click', event => { if (event.target === $('#detail-dialog')) $('#detail-dialog').close(); });
async function askText(title, description, action) {
  modal(title, `<p>${esc(description)}</p><form id="note-form"><label for="review-note">Review note</label><textarea id="review-note" required minlength="10" placeholder="Record the basis for your decision…"></textarea><div class="dialog-actions"><button class="btn primary" type="submit">Confirm decision</button></div></form>`, 'REVIEW');
  $('#note-form').addEventListener('submit', async event => {
    event.preventDefault(); const button = $('button', event.target); button.disabled = true;
    try { await action($('#review-note').value); $('#detail-dialog').close(); }
    catch (error) { toast(error.message, true); } finally { button.disabled = false; }
  });
}
function intro(kicker, title, description, actions = '') {
  return `<div class="intro"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="intro-actions">${actions}</div>` : ''}</div>`;
}
function empty(title, description, action = '') {
  return `<div class="empty"><div class="empty-symbol">⌑</div><h3>${title}</h3><p>${description}</p>${action}</div>`;
}
async function refreshProjects() {
  state.projects = await api('/projects'); $('#project-count').textContent = state.projects.length;
}
const blueprint = `<svg viewBox="0 0 350 220" fill="none" aria-hidden="true"><g stroke="#82986b" stroke-width="1.2"><path d="M55 35h210v145H55zM65 45h190v125H65zM65 92h77m24 0h89M65 133h77m24 0h89M142 45v125m24-125v125M93 45v47m132-47v47M103 133v37m108-37v37"/><path d="M40 35v145m-5-145h10m-10 145h10M55 197h210m-210-5v10m210-10v10" stroke-width=".6"/><path d="M143 103h23v19h-23M270 35h20v70h-20M83 32h27v6H83m96-6h27v6h-27M83 177h27v6H83m96-6h27v6h-27" fill="#dbe4cc"/></g><g fill="#819573" font-family="monospace" font-size="7"><text x="144" y="212">21.2 m</text><text transform="translate(27,124) rotate(-90)">14.1 m</text><text x="81" y="72">CLASSROOM</text><text x="189" y="72">CLASSROOM</text><text x="81" y="115">CLASSROOM</text><text x="189" y="115">SERVICES</text><text x="119" y="20">PROPOSED FLOOR PLAN</text></g></svg>`;

async function showProjects() {
  await refreshProjects();
  const p = state.projects, completed = p.filter(x => ['draft','reviewed'].includes(x.status)).length;
  main.innerHTML = intro('FROM BRIEF TO BILL OF QUANTITIES', 'Build with a clearer picture.', 'Turn project requirements into concept drawings, measured quantities, and estimates you can trace.', `<a class="btn primary" href="#new"><span class="plus">+</span> New estimate</a>`) +
    `<section class="hero-card"><div class="hero-text"><span class="eyebrow">A CONSIDERED START TO EVERY PROJECT</span><h2>Your next project,<br>grounded in evidence.</h2><p>Define the brief. Review the assumptions. See what it takes to build — and where every cost comes from.</p><button class="btn" data-action="sample">Explore a sample estimate <span>↗</span></button><a class="btn" href="#new?cpwd=1">CPWD official-rate demo ↗</a></div><div class="hero-drawing">${blueprint}</div></section>` +
    `<div class="stat-grid"><div class="stat-card"><div class="stat-label">Projects <span>▦</span></div><div class="stat-value">${p.length.toString().padStart(2,'0')}</div><div class="stat-foot">In your workspace</div></div><div class="stat-card"><div class="stat-label">Drafts prepared <span>✓</span></div><div class="stat-value">${completed.toString().padStart(2,'0')}</div><div class="stat-foot">Ready for engineering review</div></div><div class="stat-card"><div class="stat-label">Needs attention <span>◎</span></div><div class="stat-value">${p.filter(x => ['incomplete','needs_input','awaiting_review','failed'].includes(x.status)).length.toString().padStart(2,'0')}</div><div class="stat-foot">Inputs, evidence or review</div></div><div class="stat-card"><div class="stat-label">Verification checkpoints <span>◇</span></div><div class="stat-value">03</div><div class="stat-foot">Scope · Cost · Evidence</div></div></div>` +
    `<div class="section-head"><h2>Your projects <span class="count-label">${p.length} estimates</span></h2><span class="section-kicker">LATEST ACTIVITY</span></div><div class="card table-scroll">${p.length ? `<table class="project-table"><thead><tr><th>Project</th><th>Authority</th><th>Status</th><th>Estimate</th><th></th></tr></thead><tbody>${p.map(x => `<tr data-action="open-project" data-id="${x.revision_id}" tabindex="0"><td><div class="project-name"><span class="project-icon">⌑</span><div><span class="project-title">${esc(x.title)}</span><div class="project-meta">${esc(x.location || 'Location pending')} · Revision ${x.revision}${x.demo ? ' · Demo' : ''}</div></div></div></td><td>${esc(x.authority.toUpperCase())}</td><td>${badge(x.status)}</td><td>${x.total != null ? money(x.total) : '—'}</td><td>↗</td></tr>`).join('')}</tbody></table>` : empty('A new project starts here.', 'Describe what you need to build. We’ll help organize the scope, assumptions, quantities and pricing.', '<a href="#new" class="btn">Create your first estimate</a>')}</div>`;
  bind('sample', () => { location.hash = '#new?sample=1'; });
  bind('open-project', el => { location.hash = `#estimate/${el.dataset.id}`; });
  $$('[data-action="open-project"]').forEach(el => el.addEventListener('keydown', e => { if(e.key === 'Enter') el.click(); }));
}

const cpwdBrief = {"title": "CPWD office preliminary demo", "description": "Prepare a CPWD preliminary estimate for a 300 m2 single-storey office in New Delhi. RCC frame, 3.60 m height, downcomer and manual alarm scenario, internal water and electrical services only. Exclude external works, land, lifts, HVAC, consultancy, TPQA and escalation.", "authority": "cpwd", "state": "Delhi", "location": "New Delhi", "work_category": "preliminary_cpwd", "building_type": "office", "floor_area": "300", "length": "20", "width": "15", "floors": 1, "height": "3.6", "capacity": 30, "duration_months": "12", "estimate_date": "2025-07-31", "execution_year": 2025, "correction_limit": 2, "allow_demo": true};
const sampleBrief = {title:'Government primary school', description:'Build a CPWD primary school in New Delhi for 180 students. The school should have a total floor area of 600 square metres across 2 floors, with standard finishes, classrooms, toilets and necessary electrical and fire safety provisions. Construction duration is 12 months.', authority:'cpwd', location:'New Delhi', state:'Delhi', building_type:'school', floor_area:'600', floors:2, capacity:180, duration_months:12};
function input(label, name, value = '', type = 'text', placeholder = '', extra = '') {
  return `<div><label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" placeholder="${placeholder}" ${extra}></div>`;
}
function select(label, name, options, value) {
  return `<div><label for="f-${name}">${label}</label><select id="f-${name}" name="${name}">${options.map(([key,label]) => `<option value="${key}" ${key===value?'selected':''}>${label}</option>`).join('')}</select></div>`;
}
async function showForm(params = '') {
  let original = null, brief = params.includes('cpwd') ? cpwdBrief : params.includes('sample') ? sampleBrief : {};
  if (params.startsWith('revise/')) { original = await api(`/revisions/${params.slice(7)}`); brief = original.brief; }
  const today = new Date().toLocaleDateString('en-CA');
  main.innerHTML = intro(original ? `PROJECT REVISION ${original.revision + 1}` : 'NEW PROJECT', original ? 'Refine the project brief.' : 'What are we building?', 'Start with what you know. Missing design details become visible assumptions, ready for your review.', '<a class="btn ghost" href="#projects">← Back to projects</a>') +
    `<div class="form-layout"><form id="estimate-form" class="card"><section class="form-section"><div class="form-section-head"><span class="step-number">01</span><h2>The project brief</h2></div><div class="form-grid"><div class="full">${input('Project name','title',brief.title || '', 'text','e.g. Government primary school','required maxlength="180"')}</div><div class="full"><label for="f-description">Describe the project</label><textarea id="f-description" name="description" required minlength="10" rows="5" placeholder="What is being built, where, for how many people, and with which specifications?">${esc(brief.description || '')}</textarea><p class="hint">Include the procuring authority and any essential facilities or constraints.</p></div>${select('Procuring authority','authority',[['unknown','Identify from the brief'],['cpwd','CPWD'],['railway','Indian Railways'],['state_pwd','State PWD']],brief.authority || 'unknown')}${select('Estimate scope','work_category',[['building','Building concept (demo package)'],['preliminary_cpwd','CPWD preliminary plinth-area estimate']],brief.work_category || 'building')}${select('Building type','building_type',[['','Identify from the brief'],['school','School'],['office','Office'],['community_hall','Community hall'],['hospital','Hospital — requires domain package']],brief.building_type || '')}${input('City / location','location',brief.location || '', 'text','e.g. New Delhi','required')}${input('State / union territory','state',brief.state || '', 'text','e.g. Delhi')}</div></section>` +
    `<section class="form-section"><div class="form-section-head"><span class="step-number">02</span><h2>Scale and dimensions</h2></div><div class="form-grid">${input('Total floor area, all floors (m²)','floor_area',brief.floor_area || '', 'number','Optional — concept default','min="1" step="0.001"')}${input('Number of floors','floors',brief.floors || '', 'number','Optional','min="1" max="20" step="1"')}${input('Footprint length (m)','length',brief.length || '', 'number','Optional','min="1" step="0.001"')}${input('Footprint width (m)','width',brief.width || '', 'number','Optional','min="1" step="0.001"')}${input('Storey height (m)','height',brief.height || '', 'number','Optional','min="1" step="0.001"')}${input('Capacity / occupants','capacity',brief.capacity || '', 'number','Optional','min="1" step="1"')}${input('Site area (m²)','site_area',brief.site_area || '', 'number','Optional','min="1" step="0.001"')}${input('Construction duration (months)','duration_months',brief.duration_months || '', 'number','Optional','min="1" step="0.1"')}</div><p class="hint">Concept quantities are conditional on the proposed geometry. Structural and service quantities may remain allowances.</p></section>` +
    `<section class="form-section"><div class="form-section-head"><span class="step-number">03</span><h2>Estimate basis</h2></div><div class="form-grid">${input('Valuation date','estimate_date',brief.estimate_date || today,'date','','required')}${input('Correction attempts per checkpoint (0 = skip retries)','correction_limit',brief.correction_limit ?? 2,'number','','min="0" max="5" step="1"')}${input('Year of execution','execution_year',brief.execution_year || new Date().getFullYear(),'number','','required min="2000" max="2100"')}<div class="full"><label>Optional additions</label><label class="check"><input type="checkbox" name="option" value="hvac" ${(brief.selected_options || []).includes('hvac')?'checked':''}> Include comfort air-conditioning</label><label class="check"><input type="checkbox" name="option" value="solar" ${(brief.selected_options || []).includes('solar')?'checked':''}> Include rooftop solar</label></div><div class="full"><label class="check"><input type="checkbox" name="review_design" ${brief.review_design?'checked':''}> Pause after concept drawings and quantities for design review</label><details><summary class="hint">Advanced specifications and supplied quantities</summary><label for="f-specifications">Specifications (JSON, e.g. {"rcc.grade":"M30"})</label><textarea id="f-specifications" name="specifications" rows="2">${esc(JSON.stringify(brief.specifications || {}))}</textarea><label for="f-supplied_quantities">Measured quantities (JSON, keyed by component)</label><textarea id="f-supplied_quantities" name="supplied_quantities" rows="2">${esc(JSON.stringify(brief.supplied_quantities || {}))}</textarea></details></div></div></section><div class="form-actions"><p class="hint">New source files are indexed before estimation begins.</p><button class="btn primary" type="submit">${original ? 'Create revised estimate' : 'Generate concept estimate'} <span>→</span></button></div></form>` +
    `<aside class="form-help"><span class="eyebrow">WHAT YOU’LL RECEIVE</span><h3>A transparent starting point.</h3><ol><li>Dimensioned concept drawings with explicit assumptions.</li><li>A component-by-component bill of quantities.</li><li>Sourced rates and a calculated cost breakdown.</li><li>Evidence, verification findings and editable exports.</li></ol><div class="help-line"></div><p><strong>Designed for review.</strong><br>This is a concept-based draft. Engineering and tender approval remain with your project team.</p>${state.config.mode==='demo'?'<div class="help-line"></div><p>Demo packages use synthetic prices and norms to demonstrate the workflow.</p>':''}</aside></div>`;
  $('#estimate-form').addEventListener('submit', async event => {
    event.preventDefault(); const button = $('button[type="submit"]',event.target); button.disabled = true; button.textContent = 'Creating project…';
    try {
      const data = new FormData(event.target); const body = Object.fromEntries(data);
      delete body.option; body.selected_options = data.getAll('option'); body.review_design = data.has('review_design');
      body.allow_demo = state.config.mode==='demo'; body.correction_limit = Number(data.get('correction_limit'));
      body.work_category = data.get('work_category') || 'building';
      for (const name of ['floor_area','length','width','height','capacity','floors','site_area','duration_months']) if (!body[name]) body[name]=null;
      for (const name of ['specifications','supplied_quantities']) body[name] = JSON.parse(body[name] || '{}');
      const result = await api(original ? `/projects/${original.project_id}/revisions` : '/projects', {method:'POST',body:JSON.stringify(body)});
      await api(`/revisions/${result.revision_id}/run`,{method:'POST'});
      location.hash = `#estimate/${result.revision_id}`;
    } catch(error) { toast(error.message,true); button.disabled=false; button.textContent='Generate concept estimate →'; }
  });
}

function checkpoints(result) {
  const finished = ['draft','incomplete','reviewed'].includes(result.status);
  return `<div class="workflow-strip">${[['Design & quantities','Components and concept geometry'],['Cost estimation','Rates, adjustments and arithmetic'],['Evidence & reporting','Sources and final documents']].map(([name,desc],i) => `<div class="checkpoint ${finished || result.checkpoint>i+1 ? 'done' : result.checkpoint===i+1 ? 'active' : ''}"><span class="checkpoint-num">${finished || result.checkpoint>i+1 ? '✓' : `0${i+1}`}</span><div><strong>${name}</strong><small>${desc}</small></div></div>`).join('')}</div>`;
}
async function showEstimate(id) {
  const routeVersion=state.routeVersion;
  const result=await api(`/revisions/${id}`);
  if(routeVersion!==state.routeVersion) return;
  state.result=result; renderEstimate();
  if (['queued','running'].includes(result.status)) {
    state.poll=setTimeout(() => showEstimate(id).catch(error => toast(error.message,true)),1800);
  }
}
function renderEstimate() {
  const r=state.result, running=['queued','running'].includes(r.status);
  const unavailable = r.status==='needs_input';
  main.innerHTML=intro(`ESTIMATE / REVISION ${r.revision}`,esc(r.brief.title),`${esc(r.brief.location || 'Location pending')} <span>·</span> ${esc(r.brief.authority.toUpperCase())} <span>·</span> ${esc(r.brief.estimate_date)} &nbsp; ${badge(r.status)}`,
    `${running ? '<button class="btn" data-action="skip-corrections">Skip remaining retries</button>' : ''}<button class="btn" data-action="history">Revision history</button><a class="btn primary" href="#revise/${r.revision_id}">Edit brief <span>↗</span></a>`) +
    (r.demo ? `<div class="info-banner"><span class="info-icon">ⓘ</span><p><strong>Demonstration estimate.</strong> Source registers distinguish official-rate demonstrations from synthetic fixtures. Quantities and applicability require review before procurement.</p></div>`:'') + checkpoints(r) +
    (running?`<div class="running-note"><span class="spinner"></span><span>Preparing your estimate… ${r.agent_trace.length ? `Last completed: ${esc(words(r.agent_trace.at(-1).role))}.` : 'Indexing new source documents.'}</span></div>`:'') +
    (r.status==='awaiting_review'?`<div class="info-banner green"><span class="info-icon">◎</span><div><p><strong>Concept ready for review.</strong> Check the drawing and assumptions before pricing.</p><button class="btn small" data-action="accept-design">Accept concept and continue →</button></div></div>`:'') +
    (r.status==='failed'?`<div class="info-banner error"><p>The workflow stopped. Completed checkpoints are preserved.</p><button class="btn small" data-action="resume">Resume run</button></div>`:'') +
    (unavailable ? `<div class="card card-pad"><h2>More information is needed.</h2>${r.findings.map(f=>`<div class="finding"><div>${badge(f.severity)}</div><p>${esc(f.message)}</p></div>`).join('')}<div class="intro-actions"><a class="btn primary" href="#revise/${r.revision_id}">Revise project inputs</a><a class="btn" href="#knowledge">Open knowledge library</a></div></div>` :
      `<div class="tabs" role="tablist" aria-label="Estimate views">${[['overview','Overview'],['boq','Bill of quantities'],['drawing','Concept drawings'],['evidence','Source evidence'],['checks','Verification']].map(([key,label])=>`<button class="tab ${state.tab===key?'active':''}" role="tab" aria-selected="${state.tab===key}" data-action="tab" data-tab="${key}">${label}</button>`).join('')}</div><section id="estimate-panel"></section>`);
  if(!unavailable) renderEstimateTab();
  bind('tab',el=>{state.tab=el.dataset.tab;renderEstimate();});
  bind('accept-design',()=>askText('Accept concept design','This accepts the proposed assumptions for draft pricing. It is not a construction approval.',async note=>{
    await api(`/revisions/${r.revision_id}/review`,{method:'POST',body:JSON.stringify({decision:'accept_design',note})});
    toast('Design review recorded. Pricing is continuing.'); clearTimeout(state.poll); await showEstimate(r.revision_id);
  }));
  bind('skip-corrections',async()=>{await api(`/revisions/${r.revision_id}/skip-corrections`,{method:'POST'});toast('Remaining retries skipped; current step will finish.');});
  bind('resume',async()=>{await api(`/revisions/${r.revision_id}/run`,{method:'POST'});await showEstimate(r.revision_id);});
  bind('history',async()=>{
    const revisions=await api(`/projects/${r.project_id}/revisions`);
    modal('Project revisions',revisions.map(v=>`<div class="assumption-row"><a href="#estimate/${v.id}" data-action="history-open">Revision ${v.number} — ${esc(v.created_at.slice(0,10))}</a>${badge(v.status)}<strong>${money(v.total)}</strong></div>`).join(''),'VERSION HISTORY');
    $$('[data-action="history-open"]', $('#dialog-body')).forEach(a=>a.addEventListener('click',()=>$('#detail-dialog').close()));
  });
}
function renderEstimateTab() {
  const r=state.result, panel=$('#estimate-panel'); if(!panel) return;
  if(state.tab==='overview') {
    const categories=Object.entries(r.category_totals), max=Math.max(1,...categories.map(([,v])=>Number(v)));
    panel.innerHTML=`<div class="overview-grid"><div><section class="card card-pad side-card"><div class="section-head"><h2>Cost by work package</h2><span class="section-kicker">SELECTED SCOPE</span></div>${categories.length?categories.map(([name,value])=>`<div class="cost-row"><span>${esc(name)}</span><div class="bar-track"><div class="bar-fill" style="width:${Number(value)/max*100}%"></div></div><strong>${money(value)}</strong></div>`).join(''):empty('Cost breakdown is on its way.','Amounts appear here after quantities and rates have been established.')}<div class="table-footer"><span>Selected item subtotal</span><strong>${money(r.known_subtotal)}</strong></div>${r.adjustments.map(a=>`<div class="assumption-row"><span>${esc(a.label)} · ${esc(a.scenario)}</span><strong>${money(a.amount)}</strong></div>`).join('')}</section><section class="card card-pad side-card"><h2>Project at a glance</h2><dl class="details-list"><div><dt>Building type</dt><dd>${esc(words(r.brief.building_type))}</dd></div><div><dt>Gross floor area</dt><dd>${num(r.design?.metrics.gross_floor_area)} m²</dd></div><div><dt>Concept footprint</dt><dd>${r.design ? `${num(r.design.length)} × ${num(r.design.width)} m` : 'Not established'}</dd></div><div><dt>Floors</dt><dd>${r.design?.floors ?? '—'}</dd></div><div><dt>Execution year</dt><dd>${r.brief.execution_year}</dd></div><div><dt>Evidence coverage of priced rows</dt><dd>${Math.round((r.metrics.evidence_coverage || 0)*100)}%</dd></div></dl></section><section class="card card-pad"><h2>Working assumptions <span class="count-label">${r.assumptions.length}</span></h2>${r.assumptions.length?r.assumptions.map(a=>`<div class="assumption-row"><span>${esc(words(a.field))}</span><strong>${esc(a.value)}</strong></div>`).join(''):'<p class="hint">Assumptions are recorded during concept generation.</p>'}</section></div><aside><div class="total-card"><span class="eyebrow">${r.base_total==null?'KNOWN SUBTOTAL':'ESTIMATED PROJECT COST'}</span><div class="big-total">${money(r.base_total ?? r.known_subtotal)}</div><p>${r.base_total==null?'Incomplete estimate. Unresolved items are not counted as zero.':'Concept-based draft · See source dates and exclusions.'}</p><div class="total-split"><span>Unselected options</span><strong>${money(r.optional_subtotal)}</strong></div></div><section class="card card-pad side-card"><h2>Your documents</h2><p class="hint">All exports share this revision’s evidence and calculations.</p><div class="export-list">${exportButtons(r)}</div></section><section class="card card-pad side-card"><h2>Engineering review</h2><p class="hint">Record corrections to improve this project and future estimates.</p><button class="btn small" data-action="feedback" style="margin-top:15px">Add feedback</button>${r.status==='draft'&&!r.demo?'<button class="btn small" data-action="mark-reviewed" style="margin-top:10px">Mark draft reviewed</button>':''}</section></aside></div>`;
  } else if(state.tab==='boq') {
    panel.innerHTML=`<div class="table-tools"><input id="boq-search" type="search" placeholder="Search components or item codes…" aria-label="Search BOQ"><span class="mini-label">${r.boq.length} components · click an item for its evidence</span><button class="btn small right" data-action="export" data-name="boq.xlsx" ${r.artifacts['boq.xlsx']?'':'disabled'}>↓ Export BOQ</button></div><div class="card table-scroll"><table class="boq-table"><thead><tr><th>Component</th><th>Unit</th><th>Quantity</th><th>Unit rate</th><th>Amount</th><th>Status</th></tr></thead><tbody id="boq-body">${r.boq.map(b=>`<tr class="${b.selected?'':'optional'}" data-search="${esc((b.description+' '+b.category+' '+(b.item_code || '')).toLowerCase())}"><td class="description-cell"><button class="row-button" data-action="item-detail" data-id="${esc(b.id)}">${esc(b.description)}</button><span class="basis">${esc(b.category)} ${b.selected?'':'· optional, not selected'}</span></td><td>${esc(b.unit)}</td><td>${num(b.quantity)}<span class="basis">${esc(words(b.quantity_basis))}</span></td><td class="amount">${b.unit_rate==null?'—':money(b.unit_rate)}<span class="basis">${esc(b.item_code || 'No matching source')}</span></td><td class="amount">${b.amount==null?'—':money(b.amount)}</td><td>${badge(b.status,b.status==='priced'?'approved':'warning')}</td></tr>`).join('')}</tbody></table><div class="table-footer"><span>${r.base_total==null?'Known line-item subtotal · incomplete':'Estimated total for selected scope'}</span><strong>${money(r.base_total ?? r.known_subtotal)}</strong></div></div>`;
    $('#boq-search').addEventListener('input',event=>$$('#boq-body tr').forEach(row=>row.hidden=!row.dataset.search.includes(event.target.value.toLowerCase())));
  } else if(state.tab==='drawing') {
    panel.innerHTML=r.design?`<div class="section-head"><div><h2>Proposed concept layout</h2><p class="hint">Drawing elements and quantity calculations use the same model.</p></div><button class="btn small" data-action="export" data-name="concept.dxf" ${r.artifacts['concept.dxf']?'':'disabled'}>↓ Editable DXF</button></div><div class="drawing-canvas" id="drawing-canvas"><div class="loading-inline">Loading concept drawing…</div></div><div class="drawing-meta"><span>Footprint<strong>${num(r.design.length)} × ${num(r.design.width)} m</strong></span><span>Floors<strong>${r.design.floors}</strong></span><span>Storey height<strong>${num(r.design.height)} m</strong></span></div><div class="card card-pad"><h2>Design basis and limitations</h2>${r.design.limitations.map(l=>`<p class="hint">${esc(l)}</p>`).join('')}</div>`:empty('No concept drawing available.','Check the verification findings for unsupported templates or missing dimensions.');
    if(r.artifacts['concept.svg']) loadDrawing(r.revision_id).catch(error=>{if($('#drawing-canvas'))$('#drawing-canvas').textContent=error.message;});
    else if(r.design) $('#drawing-canvas').innerHTML='<p class="hint">Drawing exports will be available at the review checkpoint or when the run finishes.</p>';
  } else if(state.tab==='evidence') {
    const docs=r.evidence.filter(e=>e.kind==='document'&&!e.parent_ids.length);
    panel.innerHTML=`<div class="section-head"><h2>Source register <span class="count-label">${docs.length} documents</span></h2><span class="section-kicker">VERSIONED EVIDENCE</span></div><div class="sources-grid">${docs.map(e=>`<article class="card source-card">${badge(e.trust)}<h3>${esc(e.title)}</h3><p>Version ${esc(e.version)} · ${esc(e.locator || 'See item-level references')}</p><div class="source-actions"><button class="btn small" data-action="evidence-detail" data-id="${esc(e.id)}">Inspect evidence ↗</button></div><p class="hint">SHA-256 ${esc(e.content_hash.slice(0,16))}…</p></article>`).join('')}</div>${!docs.length?empty('Evidence will appear here.','Every priced item retains source and calculation references.'):''}<div class="info-banner green" style="margin-top:22px"><span>↳</span><p>For a complete chain from amount to quantity, rate, drawing and source, select any item in the bill of quantities.</p></div>`;
  } else {
    panel.innerHTML=`<div class="section-head"><h2>Verification findings <span class="count-label">${r.findings.length}</span></h2><span class="section-kicker">${r.findings.filter(f=>f.severity==='blocking').length} BLOCKING</span></div>${r.findings.map(f=>`<div class="finding"><div>${badge(f.severity)}</div><div><p>${esc(f.message)}</p><small>Checkpoint ${f.checkpoint} ${f.item_id?'· '+esc(f.item_id):''}</small></div></div>`).join('')}<h2 style="margin-top:30px">Workflow activity</h2><div class="trace">${r.agent_trace.map(t=>`<div class="trace-step">${esc(words(t.role))}<small>${t.duration_ms} ms · ${esc(t.usage.provider || 'deterministic')}</small></div>`).join('')}</div>`;
  }
  bind('export',el=>download(r.revision_id,el.dataset.name),panel);
  bind('item-detail',el=>itemDetail(el.dataset.id),panel);
  bind('evidence-detail',el=>evidenceDetail(el.dataset.id),panel);
  bind('feedback',()=>feedbackDialog(r),panel);
  bind('mark-reviewed',()=>askText('Mark draft reviewed','Confirm that the evidence, scope and calculations have been reviewed. This does not issue a tender or grant technical sanction.',async note=>{
    await api(`/revisions/${r.revision_id}/review`,{method:'POST',body:JSON.stringify({decision:'mark_reviewed',note})});await showEstimate(r.revision_id);
  }),panel);
}
function exportButtons(r) {
  const names={'estimate-bundle.zip':'Complete document bundle','boq.xlsx':'Bill of quantities · XLSX','estimate.pdf':'Estimate report · PDF','concept.pdf':'Concept drawings · PDF','estimate.docx':'Editable report · DOCX','estimate.json':'Structured estimate · JSON'};
  return Object.entries(names).map(([name,label])=>`<button class="btn" data-action="export" data-name="${name}" ${r.artifacts[name]?'':'disabled'}>${label}<span>↓</span></button>`).join('');
}
async function download(id,name) {
  const blob=await api(`/revisions/${id}/artifacts/${name}`,{download:true});
  const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function loadDrawing(id) {
  const blob=await api(`/revisions/${id}/artifacts/concept.svg`,{download:true});
  if(state.result.revision_id!==id || !$('#drawing-canvas'))return;
  const url=URL.createObjectURL(blob);state.blobURLs.push(url);
  $('#drawing-canvas').innerHTML=`<img src="${url}" alt="Dimensioned concept floor plans for ${esc(state.result.brief.title)}">`;
}
function evidenceTree(ids, depth=0, visited=new Set()) {
  if(depth>5)return '';
  return ids.map(id=>{
    if(visited.has(id))return ''; visited.add(id);
    const e=state.result.evidence.find(e=>e.id===id);if(!e)return `<p class="error-text">Missing reference ${esc(id)}</p>`;
    const calc=state.result.calculations.find(c=>c.id===id);
    return `<div class="evidence-node"><strong>${esc(e.kind.toUpperCase())} · ${esc(e.kind==='document'?e.title:e.id)}</strong>${e.locator?`<p>${esc(e.locator)}</p>`:''}${calc?`<pre>${esc(calc.formula)}\n${esc(JSON.stringify(calc.inputs,null,2))}\n= ${esc(calc.result)} ${esc(calc.unit)}</pre>`: e.kind==='assumption'?`<p>${esc(e.value)}</p>`:''}${e.parent_ids.length?`<div class="evidence-chain">${evidenceTree(e.parent_ids,depth+1,visited)}</div>`:''}</div>`;
  }).join('');
}
function itemDetail(id) {
  const b=state.result.boq.find(x=>x.id===id);
  modal(b.description,`<p>${esc(b.use)}</p><div class="stat-grid" style="grid-template-columns:repeat(3,1fr)"><div><span class="mini-label">QUANTITY</span><h2>${num(b.quantity)} ${esc(b.unit)}</h2></div><div><span class="mini-label">UNIT RATE</span><h2>${money(b.unit_rate)}</h2></div><div><span class="mini-label">AMOUNT</span><h2>${money(b.amount)}</h2></div></div><p><strong>Specification:</strong> ${esc(JSON.stringify(b.specification))}<br><strong>Quantity basis:</strong> ${esc(words(b.quantity_basis))}<br><strong>Drawing elements:</strong> ${esc(b.element_ids.join(', ') || 'Not established')}<br><strong>Included in rate:</strong> ${esc(b.inclusions.join(', ') || 'Not established')}<br><strong>Excluded from rate:</strong> ${esc(b.exclusions.join(', ') || 'None stated')}</p><h3>Evidence chain</h3><div class="evidence-chain">${evidenceTree(b.amount_calculation_id?[b.amount_calculation_id]:b.evidence_ids)}</div><button class="btn small" id="item-feedback">Suggest a correction</button>`,b.item_code || 'UNRESOLVED RATE');
  $('#item-feedback').addEventListener('click',()=>feedbackDialog(state.result,b.id));
}
function evidenceDetail(id) {
  const e=state.result.evidence.find(x=>x.id===id);
  modal(e.title,`<p>Version ${esc(e.version)} · ${esc(e.trust)}</p><p>${esc(e.locator)}</p><pre class="code-block">${esc(e.value || e.id)}</pre><p>Snapshot: <code>${esc(e.snapshot_ref)}</code></p><p>SHA-256: <code>${esc(e.content_hash)}</code></p>${/^https?:\/\//i.test(e.url)?`<a class="btn small" href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">Open original source ↗</a>`:''}`,'SOURCE EVIDENCE');
}
function feedbackDialog(r,item_id=null) {
  modal('Suggest a correction',`<p>Feedback is reviewed before it influences future estimates. Official rates and rules remain unchanged.</p><form id="feedback-form">${select('Type of correction','category',[['scope','Scope'],['quantity','Quantity'],['specification','Specification'],['source','Source'],['price','Price'],['design','Design']],'quantity')}<label for="feedback-comment" style="margin-top:14px">What should change, and why?</label><textarea id="feedback-comment" required minlength="5"></textarea><label for="feedback-value" style="margin-top:14px">Proposed value (optional)</label><input id="feedback-value"><div class="dialog-actions"><button class="btn primary">Submit for review</button></div></form>`,'ENGINEERING FEEDBACK');
  $('#feedback-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('button',event.target);button.disabled=true;
    try {await api(`/revisions/${r.revision_id}/feedback`,{method:'POST',body:JSON.stringify({category:$('#f-category').value,item_id,comment:$('#feedback-comment').value,proposed_value:$('#feedback-value').value || null})});$('#detail-dialog').close();toast('Feedback saved for review.');}
    catch(error){toast(error.message,true);}finally{button.disabled=false;}
  });
}

async function showKnowledge() {
  const data=await api('/knowledge');
  main.innerHTML=intro('THE FOUNDATION OF EVERY ESTIMATE','Your knowledge library.','Source documents, rate schedules, specifications and reviewed domain packages — with every version preserved.', '<button class="btn primary" data-action="scan">↻ Scan database folder</button>') +
    `<div class="info-banner green"><span class="info-icon">↳</span><p><strong>Add your files to database/.</strong> New and changed documents are indexed at startup and before each estimate. Unchanged files are skipped.</p></div><div class="upload-zone"><button class="btn" data-action="upload">↑ Upload source documents</button><input id="file-upload" type="file" accept=".pdf,.txt,.md,.docx,.csv,.xlsx,.json" multiple hidden><p>PDF, DOCX, TXT, Markdown, CSV, XLSX or JSON · 15 MB per file</p></div>` +
    `<div class="section-head"><h2>Domain packages <span class="count-label">${data.packages.length}</span></h2><span class="section-kicker">REVIEWED RULES + TEMPLATES + RATES</span></div><div class="package-list">${data.packages.map(p=>`<article class="card package-card">${badge(p.trust)}<h3>${esc(p.name)}</h3><p>Version ${esc(p.version)} · ${p.rates} rates</p><p>${esc(p.supported_buildings.map(words).join(', '))}</p><div class="intro-actions"><button class="btn small" data-action="inspect-package" data-id="${p.id}">Inspect</button>${p.trust==='candidate'&&state.config.identity.role==='admin'?`<button class="btn small" data-action="approve-package" data-id="${p.id}">Approve</button>`:''}</div></article>`).join('') || '<p class="hint">No packages yet. Import a reviewed structured package to enable design and pricing.</p>'}</div>`+
    `<div class="section-head"><h2>Search source knowledge</h2><span class="section-kicker">${data.retrieval==='hybrid'?'KEYWORD + SEMANTIC':'KEYWORD RETRIEVAL'}</span></div><form id="knowledge-search" class="table-tools"><input name="query" type="search" required minlength="2" placeholder="Search rates, clauses or specifications…" aria-label="Search source knowledge"><button class="btn">Search</button></form><div id="search-results"></div>`+
    `<div class="card"><div class="knowledge-header"><div><h2>Source documents</h2><p>${data.documents.length} versions · candidates require validation before use as official rates</p></div></div><div class="table-scroll">${data.documents.length?`<table class="source-table"><thead><tr><th>Document</th><th>Authority</th><th>Version</th><th>Status</th><th></th></tr></thead><tbody>${data.documents.map(d=>`<tr><td><strong class="project-title">${esc(d.title)}</strong><div class="project-meta">${esc(d.locator || d.hash?.slice(0,20) || '')}${d.active?'':' · superseded'}</div></td><td>${esc(d.authority.toUpperCase())}</td><td>${esc(d.version)}</td><td>${badge(d.trust)}</td><td><button class="btn small" data-action="source-download" data-id="${d.id}">↓</button></td></tr>`).join('')}</tbody></table>`:empty('Your source library is empty.','Place your data in database/ or upload a source document to begin indexing.')}</div></div>`+
    `<div class="section-head" style="margin-top:28px"><h2>Folder ingestion history</h2></div><div class="card">${data.imports.length?data.imports.map(f=>`<div class="file-status"><strong>${esc(f.path)}</strong> &nbsp; ${badge(f.status,f.status==='indexed'?'approved':'failed')}<p class="hint">${esc(f.error || 'Content fingerprint: '+f.digest.slice(0,24)+'…')}</p></div>`).join(''):empty('No inbox files indexed yet.','Add your own documents to the database folder. The bundled demonstration packages are stored separately.')}</div>`;
  bind('scan',async el=>{el.disabled=true;try{const report=await api('/knowledge/scan',{method:'POST'});await showKnowledge();toast(`${report.added} new, ${report.updated} updated, ${report.skipped} unchanged, ${report.failed} failed.`);}finally{el.disabled=false;}});
  bind('upload',()=>$('#file-upload').click());
  $('#file-upload').addEventListener('change',async event=>{
    const files=[...event.target.files];let errors=0;
    for(const file of files){const form=new FormData();form.append('file',file);try{const r=await api('/knowledge/upload',{method:'POST',body:form});if(r.status==='failed'){errors++;toast(`${file.name}: ${r.error}`,true);}}catch(error){errors++;toast(error.message,true);}}
    await showKnowledge();if(!errors)toast(`${files.length} source files indexed.`);
  });
  bind('approve-package',el=>askText('Approve domain package','Confirm the source rows, applicability, measurement recipes, rates and inclusions have been checked by your team.',async reason=>{await api(`/knowledge/packages/${el.dataset.id}/approve`,{method:'POST',body:JSON.stringify({reason})});await showKnowledge();toast('Package approved for applicable estimates.');}));
  bind('inspect-package',async el=>{const pack=await api(`/knowledge/packages/${el.dataset.id}`);modal(pack.name,`<p>Inspect the full versioned package before approving it.</p><pre class="code-block" style="max-height:55vh">${esc(JSON.stringify(pack,null,2))}</pre>`,'DOMAIN PACKAGE');});
  bind('source-download',async el=>{const blob=await api(`/knowledge/documents/${el.dataset.id}/source`,{download:true});const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download='source-snapshot';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $('#knowledge-search').addEventListener('submit',async event=>{
    event.preventDefault();$('#search-results').innerHTML='<p class="loading-inline">Searching indexed sources…</p>';
    try{const result=await api('/knowledge/search',{method:'POST',body:JSON.stringify({query:new FormData(event.target).get('query')})});$('#search-results').innerHTML=result.results.length?result.results.map(r=>`<article class="search-result">${badge(r.trust)}<h3 style="margin-top:10px">${esc(r.title)}</h3><p class="hint">${esc(r.locator)} · ${esc(result.mode)}</p><pre>${esc(r.content)}</pre></article>`).join(''):empty('No matching sources.','Try a different term or add the relevant source documents.');}catch(error){$('#search-results').textContent=error.message;}
  });
}
async function showFeedback() {
  const data=await api('/feedback');
  main.innerHTML=intro('REVIEW & FEEDBACK','Learn from every revision.','Review corrections before they inform future templates or estimation policies. Accepted feedback never silently overwrites source rates.')+
    (data.length?data.map(f=>`<article class="card feedback-card"><div class="section-head">${badge(f.status)}<span class="meta">${esc(f.author)} · ${esc(f.created_at.slice(0,10))}</span></div><h3>${esc(words(f.payload.category))} ${f.payload.item_id?'· '+esc(f.payload.item_id):''}</h3><p>${esc(f.payload.comment)}</p>${f.payload.proposed_value?`<p>Proposed value: <strong>${esc(f.payload.proposed_value)}</strong></p>`:''}${f.decision?`<p class="hint">${esc(f.decision.reviewer)}: ${esc(f.decision.reason)}</p>`:''}<div class="intro-actions"><a class="btn small" href="#estimate/${f.revision_id}">Open estimate ↗</a>${f.status==='pending'&&['admin','reviewer'].includes(state.config.identity.role)?`<button class="btn small" data-action="feedback-review" data-id="${f.id}" data-decision="accepted">Accept for evaluation</button><button class="btn small" data-action="feedback-review" data-id="${f.id}" data-decision="rejected">Reject</button>`:''}</div></article>`).join(''):`<div class="card">${empty('No feedback waiting for review.','Open an estimate or a BOQ item to suggest a correction.')}</div>`);
  bind('feedback-review',el=>askText('Review correction','Record why this correction should be accepted for offline evaluation or rejected.',async reason=>{await api(`/feedback/${el.dataset.id}/review`,{method:'POST',body:JSON.stringify({decision:el.dataset.decision,reason})});await showFeedback();toast('Feedback review saved.');}));
}
async function showSystem() {
  const c=state.config;
  main.innerHTML=intro('WORKSPACE SETTINGS','A workspace you can inspect.','Configuration, source onboarding and deployment details for your project team.')+
    `<div class="settings-grid"><section class="card card-pad"><h2>Current configuration</h2><div class="assumption-row"><span>Workspace mode</span><strong>${esc(c.mode)}</strong></div><div class="assumption-row"><span>Specialist reasoning</span><strong>${c.model_provider==='offline'?'Local templates and rules':esc(c.model_provider+' / '+c.model_name)}</strong></div><div class="assumption-row"><span>Source retrieval</span><strong>${esc(c.retrieval)}</strong></div><div class="assumption-row"><span>Web research</span><strong>${c.web_enabled?'Enabled':'Disabled'}</strong></div><div class="assumption-row"><span>Organization</span><strong>${esc(c.identity.tenant)}</strong></div><div class="assumption-row"><span>Your role</span><strong>${esc(c.identity.role)}</strong></div></section><section class="card card-pad"><h2>Add your source data</h2><ol><li>Place source documents in <code>database/</code>.</li><li>Add optional metadata sidecars for authority, version and effective date.</li><li>Scan the folder. Unchanged versions are skipped.</li><li>Import and review structured domain packages to enable exact pricing.</li></ol><p>See the included README and ingestion guide for formats and examples.</p></section><section class="card card-pad"><h2>Live models and semantic retrieval</h2><p>The local application works without model credentials. Configure an approved model provider for specialist reasoning, and an embedding service to enable semantic retrieval alongside keyword search.</p><p>Model credentials stay on the server. The application identifies local, live and unavailable reasoning in the workflow trace.</p></section><section class="card card-pad"><h2>Access and review</h2><p>Production mode requires a server-configured API key with an organization and role. The local demo is for one trusted user.</p><button class="btn" data-action="token">Set session API key</button><a class="btn" href="/docs" target="_blank" rel="noopener">API reference ↗</a></section></div>`;
  bind('token',()=>login(true));
}
function login(inDialog=false) {
  const html=`<form id="login-form"><label for="api-key">Workspace API key</label><input id="api-key" type="password" required autocomplete="off" placeholder="Enter your server-configured API key"><p class="hint">Stored only for this browser session.</p><button class="btn primary" type="submit">Connect to workspace →</button></form>`;
  if(inDialog)modal('Connect your workspace',html,'ACCESS');
  else main.innerHTML=`<section class="card login-card"><span class="eyebrow">WELCOME TO TENDERWORKS</span><h1>Your workspace awaits.</h1><p>Sign in with the API key provided by your workspace administrator.</p>${html}</section>`;
  $('#login-form').addEventListener('submit',async event=>{event.preventDefault();sessionStorage.setItem('tender-token',$('#api-key').value);try{state.config=await api('/config');$('#detail-dialog').close();configure();await route();}catch(error){sessionStorage.removeItem('tender-token');toast(error.message,true);}});
}
function configure() {
  $('#mode-label').textContent=state.config.mode==='demo'?'Demonstration workspace':'Department workspace';
  $('#profile-name').textContent=state.config.identity.user;
  $('#profile-mode').textContent=state.config.model_provider==='offline'?'Local templates & rules':'Live specialist reasoning';
}
async function route() {
  state.routeVersion++;clearTimeout(state.poll);state.blobURLs.forEach(URL.revokeObjectURL);state.blobURLs=[];
  const hash=location.hash.slice(1)||'projects';
  const nav=hash.startsWith('knowledge')?'knowledge':hash.startsWith('feedback')?'feedback':hash.startsWith('system')?'system':'projects';
  state.view=nav;$$('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===nav));
  $('#page-name').textContent=nav==='knowledge'?'Knowledge library':nav==='feedback'?'Review & feedback':nav==='system'?'Workspace settings':'Projects';
  main.innerHTML='<div class="initial-loading"><div class="spinner"></div><p>Loading workspace…</p></div>';
  try {
    if(!state.config){state.config=await api('/config');configure();}
    if(hash.startsWith('new'))await showForm(hash);
    else if(hash.startsWith('revise/'))await showForm(hash);
    else if(hash.startsWith('estimate/'))await showEstimate(hash.slice(9));
    else if(nav==='knowledge')await showKnowledge();
    else if(nav==='feedback')await showFeedback();
    else if(nav==='system')await showSystem();
    else await showProjects();
  } catch(error) {
    if(error.status===401){login();return;}
    main.innerHTML=`<div class="card">${empty('We couldn’t open this view.',esc(error.message),'<a class="btn" href="#projects">Back to projects</a>')}</div>`;
  }
}
window.addEventListener('hashchange',route);
route();
