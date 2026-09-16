const data=JSON.parse(document.getElementById('reportData').textContent);
const visibleRows=data.rows.filter(r=>r.raw!=='excluded');
const $=id=>document.getElementById(id);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={agree:'与标注一致',disagree:'与标注不一致',pending:'待核对',timeout:'超时',excluded:'测试前隔离',not_run:'未运行'};
const families={line_role:'线型与可见性',dimension_attachment:'标注读数',dimension_chain:'尺寸链计算',cross_view:'跨视图对应',section_reasoning:'剖视判断',clarification:'信息充分性'};
const bases={automatic:'原始自动判分',assistant_semantic:'助手事后文本核对',human:'用户人工复核'};
let mode='adjusted';
const states=['agree','disagree','pending','timeout'];
const pct=(n,d)=>d?`${(100*n/d).toFixed(1)}%`:'—';
const batchName=id=>data.batches.find(b=>b.id===id)?.label||id;
function stats(rows){const counts=Object.fromEntries(Object.keys(labels).map(k=>[k,0]));for(const r of rows)counts[r[mode]]++;return {counts,n:rows.filter(r=>r.attempted).length,submitted:rows.filter(r=>r.submitted).length};}
function scoped(){return visibleRows.filter(r=>$('batch').value==='all'||r.batch===$('batch').value);}
function plotRow(label,rows,detail){const s=stats(rows);if(!s.n)return '';return `<div class="plot-row"><div class="plot-label">${escape(label)}<small>${escape(detail)}</small></div><div><div class="plot-track" role="img" aria-label="${escape(label)}：${states.map(k=>`${labels[k]} ${s.counts[k]} 题`).join('，')}">${states.filter(k=>s.counts[k]).map(k=>`<span class="bar-segment ${k}" style="width:${100*s.counts[k]/s.n}%" title="${labels[k]}：${s.counts[k]} / ${s.n}（${pct(s.counts[k],s.n)}）">${s.counts[k]}</span>`).join('')}</div><div class="plot-counts"><span>${states.filter(k=>s.counts[k]).map(k=>`${s.counts[k]} ${labels[k].replace('与标注','')}`).join(' · ')}</span><strong>${s.counts.agree} / ${s.n} · ${pct(s.counts.agree,s.n)}</strong></div></div></div>`;}
function render(){
  const rows=scoped(),s=stats(rows),human=rows.filter(r=>r.basis==='human'),semantic=rows.filter(r=>r.basis==='assistant_semantic');
  $('population').textContent=`${s.n} 道测试 · ${s.submitted} 份正式答案`;
  $('methodNote').textContent=mode==='adjusted'?`候选标注口径，非专家 GT 准确率。包含 ${semantic.length} 道助手事后文本核对、${human.length} 道用户人工复核；原始判分不变。`:'冻结的原始自动判分。附加解释或未列入同义词的答案保持“待核对”，不等同于答错。';
  const metrics=[['一致率 · 全部测试',pct(s.counts.agree,s.n),`${s.counts.agree} / ${s.n} 题，包含超时与待核对`],['一致率 · 已提交',pct(s.counts.agree,s.submitted),`${s.counts.agree} / ${s.submitted} 份正式答案`],['超时率',pct(s.counts.timeout,s.n),`${s.counts.timeout} / ${s.n} 题 · 单题上限 600 秒`],['人工确认答错',human.filter(r=>r.adjusted==='disagree').length,`人工覆盖 ${human.length} / ${s.n} 题；其余未获人工确认`]];
  $('metrics').innerHTML=metrics.map(([name,value,detail])=>`<div class="metric"><span>${name}</span><strong>${value}</strong><small>${detail}</small></div>`).join('');
  $('humanFinding').hidden=!human.length;
  $('humanFinding').innerHTML=human.map(r=>`<div><strong>${escape(r.task)} · 用户确认答错</strong><br>人工确认：${escape(r.expected)}；KIMI 回答：${escape(r.answer)}。原始自动状态：${labels[r.raw]}。</div><a href="${escape(r.review_url)}">查看图纸与记录 <i data-lucide="arrow-up-right" aria-hidden="true"></i></a>`).join('');
  $('batchPlot').innerHTML=data.batches.map(b=>plotRow(b.label,visibleRows.filter(r=>r.batch===b.id),b.description)).join('');
  $('familyPlot').innerHTML=Object.entries(families).map(([id,name])=>plotRow(name,rows.filter(r=>r.family===id),'')).join('');
  $('familyScope').textContent=$('batch').value==='all'?'全部批次':batchName($('batch').value);
  const source=`来源：冻结 KIMI 作答与评审快照 · ${new Date(data.generated_at).toLocaleString('zh-CN',{hour12:false})}`;
  $('batchCaption').textContent=source+'。每条柱的分母为该批已测试题数，排除隔离题。';
  $('familyCaption').textContent=source+'。各题型以自身测试题数归一化；小样本仅作诊断。';
  renderTable();window.lucide?.createIcons();
}
function renderTable(){
  const query=$('search').value.toLowerCase(),outcome=$('outcome').value;
  const rows=scoped().filter(r=>($('family').value==='all'||r.family===$('family').value)&&(outcome==='all'?r.attempted:r[mode]===outcome)&&`${r.task} ${r.query}`.toLowerCase().includes(query));
  $('caseCount').textContent=`${rows.length} 题`;
  $('caseRows').innerHTML=rows.map(r=>{const value=r[mode],human=r.basis==='human'&&mode==='adjusted';return `<tr data-task="${escape(r.task)}" data-batch="${r.batch}" data-outcome="${value}"><td><a href="${escape(r.review_url)}"><strong>${escape(r.task)}</strong></a><small>${escape(batchName(r.batch))} · ${escape(families[r.family]||r.family)}</small><span class="query">${escape(r.query)}</span><details><summary>输入图纸</summary><a href="${escape(r.review_url)}"><img class="case-image" loading="lazy" src="${escape(r.image)}" alt="${escape(r.task)} 实际输入图纸"></a></details></td><td>${escape(r.expected)}</td><td>${escape(r.answer)||'<span class="muted">未提交答案</span>'}</td><td><span class="outcome ${value}">${human&&value==='disagree'?'人工确认答错':labels[value]}</span><small>${mode==='raw'?'原始自动判分':bases[r.basis]}</small><details><summary>核对依据</summary>${escape(r.note)}${r.excluded_reasons.length?`<p>${escape(r.excluded_reasons.join(' · '))}</p>`:''}<small>原始：${labels[r.raw]}<br>证据：${escape(r.bundle_sha256.slice(0,12))}</small></details></td><td class="numeric">${r.attempted?r.observations:'—'}</td><td class="numeric">${r.attempted?Math.round(r.elapsed_seconds):'—'}</td></tr>`;}).join('')||'<tr><td id="emptyRow" colspan="6">没有符合筛选条件的题目</td></tr>';
}
for(const b of data.batches)$('batch').add(new Option(b.label,b.id));
const initial=new URLSearchParams(location.search).get('batch');if(data.batches.some(b=>b.id===initial))$('batch').value=initial;
for(const [id,name] of Object.entries(families))if(visibleRows.some(r=>r.family===id))$('family').add(new Option(name,id));
$('legend').innerHTML=states.map(k=>`<span><i class="swatch ${k}"></i>${labels[k]}</span>`).join('');
$('snapshot').textContent=`Kimi Code + KIMI K3 · 3 批读图诊断 · ${data.timeout_seconds} 秒 / 题`;
const diagnostics=(data.diagnostics||[]).filter(item=>item.url.startsWith('/?batch='));
$('diagnostics').hidden=!diagnostics.length;
$('diagnosticLinks').innerHTML=diagnostics.map(item=>`<a href="${escape(item.url)}">${escape(item.label)} <i data-lucide="arrow-up-right" aria-hidden="true"></i></a>`).join('');
$('provenance').textContent=`快照：${data.generated_at} · 统计配置 SHA256：${data.config_sha256} · 原始答案、评审记录与每题证据哈希随结果 JSON 导出。`;
$('batch').onchange=()=>{const url=new URL(location.href);url.searchParams.set('batch',$('batch').value);history.replaceState(null,'',url);render();};
for(const el of document.querySelectorAll('[data-mode]'))el.onclick=()=>{mode=el.dataset.mode;document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===el)));render();};
$('family').onchange=renderTable;$('outcome').onchange=renderTable;$('search').oninput=renderTable;
$('download').onclick=()=>{const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='kimi-drawing-results.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
render();document.documentElement.dataset.appState='ready';
