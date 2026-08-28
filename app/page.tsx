'use client';

import { useMemo, useState } from 'react';

type Status = 'Approved' | 'Needs review' | 'Flagged';
type Requirement = {
  id: string; section: string; text: string; source: string; page: number;
  status: Status; confidence: number; category: string; criticality: string;
  quote: string; tags: string[];
};

const requirements: Requirement[] = [
  { id:'REQ-069-014', section:'TS.03.5', text:'Provide independent Primary A and Primary B protection schemes using permissive overreaching transfer trip (POTT).', source:'Protection & Control', page:79, status:'Approved', confidence:98, category:'Protection', criticality:'Mandatory', quote:'The line protection shall comprise two independent protection schemes designated Primary A and Primary B, both utilizing POTT logic.', tags:['POTT','Redundancy','Line protection'] },
  { id:'REQ-069-015', section:'TS.03.5.1', text:'Each scheme shall provide four-zone phase and ground distance protection.', source:'Protection & Control', page:79, status:'Needs review', confidence:96, category:'Protection', criticality:'Mandatory', quote:'Each main protection relay shall provide a minimum of four zones of phase and ground distance protection.', tags:['ANSI 21','ANSI 21N','Numerical relay'] },
  { id:'REQ-069-018', section:'TS.03.3', text:'Integrate panel IEDs with the station control system using DNP3 communications.', source:'SCADA & Comms', page:77, status:'Approved', confidence:99, category:'Communications', criticality:'Mandatory', quote:'All intelligent electronic devices shall communicate with the existing station control system using DNP3.', tags:['DNP3','SCADA','IED'] },
  { id:'REQ-069-022', section:'TS.02.9', text:'Equipment shall withstand salt-laden air, dust, 100% relative humidity and 40 °C ambient temperature.', source:'Environmental', page:72, status:'Flagged', confidence:83, category:'Environment', criticality:'Mandatory', quote:'The equipment shall be suitable for tropical marine conditions including salt laden atmosphere, dust, 100% humidity and ambient temperatures up to 40°C.', tags:['Environmental','Tropical','Enclosure'] },
  { id:'REQ-069-027', section:'TS.05.4', text:'Provide FT-1 or approved equivalent test switches for relay current and voltage circuits.', source:'Panel Construction', page:92, status:'Needs review', confidence:94, category:'Panel', criticality:'Mandatory', quote:'Test facilities shall be provided using FT-1 test switches or an approved equivalent.', tags:['Test switch','FT-1','Wiring'] },
];

const stages = ['Intake','Requirements','Compliance','Solution','Outputs'];

const stageContent = {
  0: { eyebrow:'Project intake', title:'Create the evidence workspace', body:'Upload the customer RFQ and product manuals. GridSpec preserves the originals, indexes technical evidence, and separates source facts from model interpretation.' },
  2: { eyebrow:'Engineer checkpoint 2 of 4', title:'Validate compliance decisions', body:'Review exact catalog evidence, matching logic, gaps, and proposed alternates before the solution is assembled.' },
  3: { eyebrow:'Engineer checkpoint 3 of 4', title:'Review the cohesive panel solution', body:'Resolve interface conflicts across relays, test facilities, communications, DC supply, panel construction, and engineering services.' },
  4: { eyebrow:'Final approval', title:'Approve bid-ready outputs', body:'Publish an auditable compliance matrix, bill of material, deviation schedule, evidence pack, and engineering assumptions.' },
} as const;

export default function Home() {
  const [selectedId, setSelectedId] = useState(requirements[1].id);
  const [filter, setFilter] = useState<'All' | Status>('All');
  const [query, setQuery] = useState('');
  const [note, setNote] = useState('Confirm whether four independent distance zones are required in both relay schemes.');
  const [toast, setToast] = useState('');
  const [activeStage, setActiveStage] = useState(1);
  const selected = requirements.find((r) => r.id === selectedId)!;
  const visible = useMemo(() => requirements.filter((r) => (filter === 'All' || r.status === filter) && `${r.id} ${r.text} ${r.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase())), [filter, query]);

  const act = (message: string) => {
    setToast(message);
    const event = { entityType: stages[activeStage].toLowerCase(), entityId: selectedId, decision: message, note, reviewer: 'Alex Morgan', at: new Date().toISOString() };
    const audit = JSON.parse(window.localStorage.getItem('gridspec-audit') || '[]') as unknown[];
    window.localStorage.setItem('gridspec-audit', JSON.stringify([...audit, event]));
    void fetch('/api/reviews',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(event)}).catch(()=>undefined);
    window.setTimeout(() => setToast(''), 2400);
  };

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">G</span><div><strong>GridSpec</strong><small>Bid intelligence</small></div></div>
        <nav aria-label="Main navigation">
          <p>Workspace</p>
          {['▦  Projects','▣  Product catalog','▤  Evidence library','◇  Rule sets'].map((item, i) => <button key={item} className={i===0?'active':''}>{item}</button>)}
          <p>Governance</p>
          {['◫  Audit trail','⚙  Settings'].map((item) => <button key={item}>{item}</button>)}
        </nav>
        <div className="profile"><span>AM</span><div><strong>Alex Morgan</strong><small>Protection engineer</small></div><b>⋯</b></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><small>Projects / JPS 1025947</small><h1>69 kV line protection panel</h1></div>
          <div className="top-actions"><button className="secondary" onClick={()=>act('Review snapshot prepared')}>Export review</button><button className="primary" onClick={()=>setActiveStage(Math.min(4,activeStage+1))}>{activeStage===4?'Publish outputs':`Continue to ${stages[Math.min(4,activeStage+1)].toLowerCase()}`} <span>→</span></button></div>
        </header>

        <div className="stagebar">
          {stages.map((stage, i) => <button key={stage} onClick={()=>setActiveStage(i)} className={`stage ${i===activeStage?'current':''} ${i<activeStage?'done':''}`}><span>{i<activeStage?'✓':i+1}</span><div><small>{i===activeStage?(i===0?'Active':'Engineer checkpoint'):i<activeStage?'Complete':'Pending'}</small><b>{stage}</b></div></button>)}
        </div>

        {activeStage !== 1 ? <StageWorkspace stage={activeStage as 0|2|3|4} onAction={act} /> :
        <div className="content">
          <section className="main-panel">
            <div className="checkpoint">
              <div><span className="eyebrow">Engineer checkpoint 1 of 4</span><h2>Review extracted requirements</h2><p>Validate what the system found before product matching begins. Every edit is recorded in the audit trail.</p></div>
              <div className="progress-ring"><strong>72%</strong><small>reviewed</small></div>
            </div>

            <div className="metrics">
              <div><small>Requirements</small><strong>64</strong><span>across 9 sections</span></div>
              <div><small>Approved</small><strong className="green">46</strong><span>ready for matching</span></div>
              <div><small>Needs review</small><strong className="amber">13</strong><span>engineer decision</span></div>
              <div><small>Flagged</small><strong className="red">5</strong><span>possible ambiguity</span></div>
            </div>

            <div className="table-tools">
              <label className="search">⌕ <input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Search requirements, tags, IDs…" /></label>
              <div className="filters">{(['All','Needs review','Flagged'] as const).map((f)=><button key={f} className={filter===f?'active':''} onClick={()=>setFilter(f)}>{f}</button>)}</div>
              <button className="icon-button" aria-label="More filters">≡</button>
            </div>

            <div className="requirement-list">
              <div className="table-head"><span>Requirement</span><span>Source</span><span>Status</span><span>Confidence</span></div>
              {visible.map((r)=><button key={r.id} className={`requirement-row ${selectedId===r.id?'selected':''}`} onClick={()=>setSelectedId(r.id)}>
                <span className="req-copy"><b>{r.id}</b><em>{r.section}</em><strong>{r.text}</strong><small>{r.tags.map(t=><i key={t}>{t}</i>)}</small></span>
                <span className="source">{r.source}<small>Page {r.page}</small></span>
                <span><i className={`status ${r.status.toLowerCase().replace(' ','-')}`}>{r.status}</i></span>
                <span className="confidence"><b>{r.confidence}%</b><i><u style={{width:`${r.confidence}%`}} /></i></span>
              </button>)}
            </div>
          </section>

          <aside className="inspector">
            <div className="inspector-head"><div><span className="eyebrow">Selected requirement</span><h3>{selected.id}</h3></div><button aria-label="Close inspector">×</button></div>
            <div className="source-card"><div className="pdf-icon">PDF</div><div><strong>JPS RFP 1025947</strong><small>{selected.source} · p. {selected.page}</small></div><button>↗</button></div>
            <label>Source passage</label><blockquote>“{selected.quote}”</blockquote>
            <label htmlFor="normalized">Normalized requirement</label><textarea id="normalized" defaultValue={selected.text} rows={5}/>
            <div className="two-col"><div><label>Criticality</label><button className="selectlike">{selected.criticality}⌄</button></div><div><label>Category</label><button className="selectlike">{selected.category}⌄</button></div></div>
            <label>Technical attributes</label><div className="tag-editor">{selected.tags.map(t=><span key={t}>{t} ×</span>)}<button>+ Add</button></div>
            <div className="ai-note"><span>✦</span><div><strong>Extraction note</strong><p>The phrase “minimum of” was preserved because it changes how product capability is evaluated.</p></div></div>
            <label htmlFor="feedback">Engineer feedback</label><textarea id="feedback" value={note} onChange={(e)=>setNote(e.target.value)} rows={3} placeholder="Add reasoning, corrections, or a review note…"/>
            <div className="review-actions"><button className="flag" onClick={()=>act('Requirement flagged for clarification')}>⚑ Flag</button><button className="secondary" onClick={()=>act('Draft saved to the audit trail')}>Save edit</button><button className="approve" onClick={()=>act('Requirement approved for product matching')}>✓ Approve</button></div>
          </aside>
        </div>}
      </section>
      {toast && <div className="toast">✓ {toast}</div>}
    </main>
  );
}

function StageWorkspace({stage,onAction}:{stage:0|2|3|4;onAction:(message:string)=>void}) {
  const copy = stageContent[stage];
  const [fileName,setFileName] = useState('');
  if(stage===0) return <div className="stage-page"><div className="wide-head"><span className="eyebrow">{copy.eyebrow}</span><h2>{copy.title}</h2><p>{copy.body}</p></div><div className="intake-grid"><section className="drop-card"><span className="upload-glyph">⇧</span><h3>Customer RFQ or specification</h3><p>PDF or DOCX, up to 100 MB. Scanned documents are supported.</p><label className="primary upload-button">Choose RFQ<input type="file" accept=".pdf,.doc,.docx" onChange={async(e)=>{const f=e.target.files?.[0];if(!f)return;setFileName(f.name);const body=new FormData();body.append('file',f);try{const response=await fetch('/api/files',{method:'POST',body});if(!response.ok)throw new Error();onAction(`${f.name} uploaded and queued for extraction`)}catch{onAction(`${f.name} added locally; cloud storage will connect on publish`)}}}/></label>{fileName&&<strong className="file-ready">✓ {fileName}</strong>}</section><section className="source-stack"><h3>Evidence sources</h3><div className="evidence-row"><span>PDF</span><div><strong>JPS RFP 1025947</strong><small>118 pages · Customer source</small></div><i>Ready</i></div><div className="evidence-row"><span>GE</span><div><strong>Multilin 850 feeder relay manual</strong><small>Product evidence · Public manual</small></div><i>Indexed</i></div><div className="evidence-row"><span>GE</span><div><strong>Multilin L90 line differential manual</strong><small>Product evidence · Public manual</small></div><i>Indexed</i></div><button className="secondary full" onClick={()=>onAction('Product manual source added')}>+ Add product manual or catalog URL</button></section></div><div className="control-note"><strong>Controlled automation</strong><p>Extraction is deterministic where possible: document parsing, tables, units, clause numbering, and deduplication run as code. A model is used only to normalize technical meaning and must cite its source span. Nothing advances without an engineer checkpoint.</p></div></div>;
  if(stage===2) return <div className="stage-page"><div className="wide-head"><span className="eyebrow">{copy.eyebrow}</span><h2>{copy.title}</h2><p>{copy.body}</p></div><div className="summary-strip"><div><b>64</b><span>requirements</span></div><div><b className="green">51</b><span>compliant</span></div><div><b className="amber">8</b><span>conditional</span></div><div><b className="red">5</b><span>non-compliant</span></div></div><div className="decision-grid"><ComplianceCard id="REQ-069-015" status="Compliant" product="GE Multilin D60" detail="Five zones of phase and ground distance; POTT logic supported." evidence="D60 Instruction Manual, Ch. 5, pp. 5-142–5-166" onAction={onAction}/><ComplianceCard id="REQ-069-018" status="Compliant" product="GE Multilin D60" detail="DNP3 serial and Ethernet are available; point mapping requires engineering." evidence="D60 Communications Guide, pp. 3-21–3-38" onAction={onAction}/><ComplianceCard id="REQ-069-022" status="Conditional" product="Panel assembly" detail="Relay rating is adequate; salt-laden atmosphere requires a sealed, climate-controlled enclosure." evidence="D60 Technical Specifications + panel design rule ENV-04" onAction={onAction}/><ComplianceCard id="REQ-069-027" status="Alternate" product="ABB FT-1 switches" detail="Catalog panel package defaults to test blocks. FT-1 switches are offered as a compliant substitution." evidence="FT-1 catalog sheet, table 2" onAction={onAction}/></div></div>;
  if(stage===3) return <div className="stage-page"><div className="wide-head"><span className="eyebrow">{copy.eyebrow}</span><h2>{copy.title}</h2><p>{copy.body}</p></div><div className="solution-grid"><section className="bom"><h3>Recommended protection panel</h3>{[['Primary A relay','GE Multilin D60','1'],['Primary B relay','GE Multilin D60','1'],['Test switches','ABB FT-1','12'],['Managed Ethernet switch','GE ML3000','1'],['Panel enclosure','NEMA 12, climate controlled','1'],['Engineering & FAT','Configured service package','1']].map(([type,item,qty])=><div className="bom-row" key={type}><span>✓</span><div><small>{type}</small><strong>{item}</strong></div><b>× {qty}</b></div>)}</section><section className="cohesion"><h3>System cohesion checks</h3>{[['DC burden','Pass','6.2 A peak vs 20 A supply'],['CT secondary circuits','Pass','1 A inputs; shorting test switches included'],['Time synchronization','Pass','IRIG-B and SNTP architecture aligned'],['Protocol mapping','Review','DNP3 point list requires customer confirmation'],['Panel environment','Resolved','Thermostat, heater and filtered cooling added']].map(([name,status,detail])=><div className="check-row" key={name}><i className={status==='Review'?'warn':''}>{status==='Review'?'!':'✓'}</i><div><strong>{name}</strong><small>{detail}</small></div><b>{status}</b></div>)}<label>Engineer decision note</label><textarea rows={4} defaultValue="Confirm customer preference for copper versus fiber communications between panel and station LAN."/><button className="approve full" onClick={()=>onAction('Cohesive solution approved for output generation')}>✓ Approve cohesive solution</button></section></div></div>;
  return <div className="stage-page"><div className="wide-head"><span className="eyebrow">{copy.eyebrow}</span><h2>{copy.title}</h2><p>{copy.body}</p></div><div className="outputs-grid">{[['Compliance matrix','XLSX','64 requirements with evidence and decisions'],['Technical proposal','DOCX','Solution narrative, scope and assumptions'],['Bill of material','XLSX','Configured equipment and quantities'],['Deviation schedule','DOCX','5 exceptions and proposed resolutions'],['Evidence package','ZIP','Cited manual pages and audit trail'],['Executive summary','PDF','Bid status and commercial handoff']].map(([title,type,description],i)=><article key={title}><span>{type}</span><h3>{title}</h3><p>{description}</p><small>{i<4?'Ready':'Pending final approval'}</small><button onClick={()=>onAction(`${title} export prepared`)}>Download ↓</button></article>)}</div><div className="approval-bar"><div><strong>Final gate</strong><p>4 checkpoints completed · 2 outputs awaiting final engineer approval</p></div><button className="approve" onClick={()=>onAction('Bid package approved and audit snapshot sealed')}>Approve & seal bid package</button></div></div>;
}

function ComplianceCard({id,status,product,detail,evidence,onAction}:{id:string;status:string;product:string;detail:string;evidence:string;onAction:(m:string)=>void}) { return <article className="compliance-card"><div className="card-top"><b>{id}</b><i className={status==='Compliant'?'pass':status==='Conditional'?'condition':'alternate'}>{status}</i></div><small>Recommended offering</small><h3>{product}</h3><p>{detail}</p><div className="evidence"><span>↳</span><div><small>Evidence</small><strong>{evidence}</strong></div></div><label>Engineer feedback</label><textarea rows={2} placeholder="Record rationale or request more evidence…"/><div className="card-actions"><button onClick={()=>onAction(`${id}: more evidence requested`)}>Request evidence</button><button className="approve" onClick={()=>onAction(`${id}: decision approved`)}>Approve</button></div></article> }
