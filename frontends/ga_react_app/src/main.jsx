import React, {useEffect, useMemo, useRef, useState} from 'react';
import { createRoot } from 'react-dom/client';
import { Send, Paperclip, Image as ImageIcon, Square, Plus, Trash2, Settings2, Bot, User, ChevronDown } from 'lucide-react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import './styles.css';

const API = '';
const uid = () => crypto.randomUUID?.() || Math.random().toString(36).slice(2);
const defaultSettings = {llm_no: 0};
function cleanSettings(settings){
  const n = Number(settings?.llm_no ?? 0);
  return {llm_no: Number.isFinite(n) ? n : 0};
}

marked.setOptions({breaks: true, gfm: true});
function md(text){ return {__html: DOMPurify.sanitize(marked.parse(text || ''))}; }
function fmtTime(ts){ if(!ts) return ''; return new Date(ts*1000).toLocaleString(); }
async function jfetch(url, opts){ const r=await fetch(API+url, opts); if(!r.ok) throw new Error(await r.text()); return await r.json(); }
async function fileToDataUrl(file){ return await new Promise((res,rej)=>{const fr=new FileReader(); fr.onload=()=>res(fr.result); fr.onerror=rej; fr.readAsDataURL(file);}); }
const MAX_IMAGE_SIDE = 1600;
const IMAGE_JPEG_QUALITY = 0.84;
const MAX_JSON_BYTES = 8 * 1024 * 1024;
function bytesOfText(s){ return new TextEncoder().encode(s || '').length; }
function loadImageFromDataUrl(dataUrl){
  return new Promise((res,rej)=>{ const img=new Image(); img.onload=()=>res(img); img.onerror=()=>rej(new Error('图片解码失败')); img.src=dataUrl; });
}
async function imageFileToPayload(file){
  const raw = await fileToDataUrl(file);
  const img = await loadImageFromDataUrl(raw);
  const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(img.width || 1, img.height || 1));
  const w = Math.max(1, Math.round((img.width || 1) * scale));
  const h = Math.max(1, Math.round((img.height || 1) * scale));
  const canvas = document.createElement('canvas'); canvas.width=w; canvas.height=h;
  const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0, w, h);
  let dataUrl = canvas.toDataURL('image/jpeg', IMAGE_JPEG_QUALITY);
  if(dataUrl.length > raw.length && raw.length < MAX_JSON_BYTES * 0.6) dataUrl = raw;
  return {name:file.name, type:'image/jpeg', dataUrl, note:`compressed ${img.width}x${img.height} -> ${w}x${h}`};
}
async function fileToPayload(file){
  if((file.type || '').startsWith('image/')) return await imageFileToPayload(file);
  const dataUrl = await fileToDataUrl(file);
  return {name:file.name, type:file.type, dataUrl};
}

function stripFence(raw){
  let s=(raw||'').trim();
  s=s.replace(/^`{3,5}\s*(?:text|json)?\s*/i,'').replace(/`{3,5}\s*$/,'').trim();
  return s;
}
function tryToolJson(raw){
  const s=stripFence(raw); const a=s.indexOf('{'); const b=s.lastIndexOf('}');
  if(a>=0 && b>a){ try{return JSON.parse(s.slice(a,b+1));}catch{return null;} }
  return null;
}
function splitAssistant(text){
  const s=text||''; const tokenRe=/\*\*\s*LLM Running \(Turn\s+(\d+)\)\s*\.\.\.\s*\*\*|<summary>([\s\S]*?)<\/summary>|🛠️\s*(?:Tool:\s*)?`?([\w.:-]+)`?(?:\s*📥\s*args:)?\s*/g; let out=[], pos=0, m;
  while((m=tokenRe.exec(s))){
    if(m.index>pos) out.push({type:'md', text:s.slice(pos,m.index)});
    if(m[1]){ out.push({type:'run', turn:m[1]}); pos=tokenRe.lastIndex; continue; }
    if(m[2]!==undefined){ out.push({type:'summary', text:m[2].trim()}); pos=tokenRe.lastIndex; continue; }
    let start=tokenRe.lastIndex; let next=s.slice(start).search(/\n(?:\*\*\s*LLM Running \(Turn\s+\d+\)\s*\.\.\.\s*\*\*|<summary>|🛠️\s*(?:Tool:\s*)?`?[\w.:-]+`?)/); let end=next<0?s.length:start+next;
    const wait=s.slice(start,end).search(/\n\s*`{0,5}\s*Waiting for your answer\s*\.\.\.\s*`{0,5}/i);
    let toolEnd=end;
    if(wait>=0) toolEnd=start+wait;
    out.push({type:'tool', name:m[3], raw:s.slice(start,toolEnd).trim()});
    if(wait>=0) out.push({type:'wait', text:'Waiting for your answer ...'});
    pos=end; tokenRe.lastIndex=end;
  }
  if(pos<s.length) out.push({type:'md', text:s.slice(pos)}); return out.length?out:[{type:'md', text:s}];
}
function normalizeParts(parts){
  const seen=new Set(); const out=[];
  for(const p of parts){
    if(p.type==='run' || p.type==='summary' || p.type==='wait' || p.type==='tool'){
      const sig=p.type+'|'+(p.turn||'')+'|'+(p.name||'')+'|'+((p.text||p.raw||'').trim().replace(/\s+/g,' ').slice(0,500));
      if(seen.has(sig)) continue;
      seen.add(sig);
    }
    out.push(p);
  }
  return out;
}
function groupRounds(parts){
  const groups=[]; let cur=null;
  for(const p of parts){
    if(p.type==='run'){
      cur={turn:p.turn, items:[]}; groups.push({type:'round', group:cur});
    }else if(cur){
      cur.items.push(p);
    }else{
      groups.push(p);
    }
  }
  return groups;
}
function RoundCard({group, open=false, running=false}){
  const summary=group.items.find(x=>x.type==='summary')?.text || '本轮过程';
  return <details className={'round-card '+(running?'is-running':'is-complete')} open={open}>
    <summary><span className="run-dot"/><b>第 {group.turn} 轮</b><em>{summary}</em></summary>
    <div className="round-body">{group.items.map((p,i)=>p.type==='tool'? <ToolCard key={i} part={p}/> : p.type==='wait'? <div key={i} className="waiting-card"><span className="pulse-dot"/>等待你的回答…</div> : p.type==='md' && (p.text||'').trim()? <div key={i} className="md" dangerouslySetInnerHTML={md(p.text)} /> : null)}</div>
  </details>;
}
function RoundInline({group}){
  return <div className="round-inline">{group.items.map((p,i)=>p.type==='tool'? <ToolCard key={i} part={p}/> : p.type==='wait'? <div key={i} className="waiting-card"><span className="pulse-dot"/>等待你的回答…</div> : p.type==='md' && (p.text||'').trim()? <div key={i} className="md" dangerouslySetInnerHTML={md(p.text)} /> : null)}</div>;
}
function ToolCard({part}){
  const data=tryToolJson(part.raw); const isAsk=part.name==='ask_user'; const title=isAsk?'需要你选择 / 回答':part.name;
  return <details className={'tool-card '+(isAsk?'ask-card':'')} open={isAsk}>
    <summary><span>🛠️</span><b>{title}</b>{isAsk?<em>已展开</em>:null}</summary>
    {isAsk && data ? <div className="ask-body">
      <div className="ask-question">{data.question || '请选择一个选项：'}</div>
      {Array.isArray(data.candidates) && data.candidates.length ? <div className="ask-options">{data.candidates.map((c,i)=><span key={i}>{c}</span>)}</div> : null}
    </div> : <pre>{stripFence(part.raw)}</pre>}
  </details>
}
function AssistantBody({text, live=false}){
  const parts=groupRounds(normalizeParts(splitAssistant(text)));
  const lastRound=[...parts].map((p,i)=>p.type==='round'?i:-1).filter(i=>i>=0).pop();
  return <>{parts.map((p,i)=> p.type==='round'? (i===lastRound ? <RoundInline key={i} group={p.group}/> : <RoundCard key={i} group={p.group} running={false}/>) : p.type==='tool'? <ToolCard key={i} part={p}/> : p.type==='wait'? <div key={i} className="waiting-card"><span className="pulse-dot"/>等待你的回答…</div> : p.type==='summary'? <div key={i} className="summary-card"><span>摘要</span>{p.text}</div> : <div key={i} className="md" dangerouslySetInnerHTML={md(p.text)} />)}</>;
}

function fileMeta(f){
  if(!f) return null;
  if(typeof f==='string'){
    const name=f.split(/[\\/]/).pop();
    const ext=(name.split('.').pop()||'').toLowerCase();
    const isImage=['png','jpg','jpeg','gif','webp','bmp','svg'].includes(ext);
    return {name, url:'/api/file/'+encodeURIComponent(name), isImage, mime:isImage?'image/'+(ext==='jpg'?'jpeg':ext):''};
  }
  const name=f.name || String(f.path||f.url||'attachment').split(/[\\/]/).pop();
  const mime=f.mime || f.type || '';
  return {name, url:f.url || f.preview || '', isImage:Boolean(f.isImage || (mime||'').startsWith('image/') || f.preview), mime};
}
function AttachmentList({files}){
  const metas=(files||[]).map(fileMeta).filter(Boolean);
  if(!metas.length) return null;
  return <div className="files">{metas.map((f,i)=> f.isImage && f.url ? <a className="file-thumb" key={i} href={f.url} target="_blank" rel="noreferrer" title="点击查看原图"><img src={f.url}/><span>{f.name}</span></a> : <a className="file-chip" key={i} href={f.url||undefined} target={f.url?'_blank':undefined} rel="noreferrer">📎 {f.name}</a>)}</div>;
}

function Message({m}){
  const user=m.role==='user';
  return <div className={'msg '+(user?'user':'assistant') }>
    <div className="avatar">{user?<User size={16}/>:<Bot size={17}/>}</div>
    <div className="bubble">
      <AttachmentList files={m.files}/>
      {user ? <div className="md" dangerouslySetInnerHTML={md(m.content)} /> : <AssistantBody text={m.content} live={m.id==='live'}/>}
    </div>
  </div>
}
function SettingsPanel({state}){
  return <section className="panel compact-status"><div className="backend">{state.backend?.name || state.backend?.class || 'backend'} · LLM {state.llm_no ?? 0}</div></section>
}
function Composer({onSend,busy,onAbort,state,settings,updateSetting}){
  const [text,setText]=useState(''); const [files,setFiles]=useState([]); const [sending,setSending]=useState(false); const ta=useRef(null);
  const addFiles=fs=>setFiles(x=>[...x,...Array.from(fs||[]).map(f=>({id:uid(), file:f, name:f.name, type:f.type, preview:f.type.startsWith('image/')?URL.createObjectURL(f):''}))]);
  async function send(){
    if(busy || sending || (!text.trim() && !files.length)) return;
    const prompt=text;
    const picked=files;
    setText('');
    setFiles([]);
    setSending(true);
    try{
      await onSend(prompt,picked.map(f=>({name:f.name,type:f.type,preview:f.preview,file:f.file})));
    }catch(e){
      console.error(e);
    }finally{
      setSending(false);
    }
  }
  return <div className="composer" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault(); addFiles(e.dataTransfer.files)}}>
    {files.length?<div className="chips">{files.map(f=><button key={f.id} onClick={()=>setFiles(x=>x.filter(y=>y.id!==f.id))}>{f.preview?<img src={f.preview}/>:<Paperclip size={14}/>} {f.name} ×</button>)}</div>:null}
    <div className="inputbar"><label className="iconbtn"><Paperclip size={19}/><input type="file" multiple hidden onChange={e=>addFiles(e.target.files)}/></label><textarea ref={ta} value={text} onChange={e=>setText(e.target.value)} onPaste={e=>{const fs=[...e.clipboardData.files]; if(fs.length) addFiles(fs)}} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}} placeholder="输入消息，支持粘贴图片/拖拽文件。Enter 发送，Shift+Enter 换行。" />{busy||sending?<button className="stop" onClick={onAbort}><Square size={16}/></button>:<button className="send" onClick={send}><Send size={17}/></button>}</div>
    <div className="composer-settings bottom-settings">
      <div className="settings-head"><span className="status-dot"/>模型</div>
      <label className="setting-pill wide"><span>切换模型</span><select value={settings.llm_no} onChange={e=>updateSetting({llm_no:Number(e.target.value)})}>{(state.llms||[{id:0,name:'default'}]).map(x=><option key={x.id} value={x.id}>{x.id}: {x.name||'default'}</option>)}</select></label>
    </div>
  </div>
}
function App(){
  const [sid,setSid]=useState(localStorage.gaReactSid||''); const [sessions,setSessions]=useState([]); const [messages,setMessages]=useState([]); const [busy,setBusy]=useState(false); const [state,setState]=useState({}); const [settings,setSettings]=useState(defaultSettings); const [follow,setFollow]=useState(true); const bottom=useRef(null); const chatRef=useRef(null);
  const refreshSessions=()=>jfetch('/api/sessions').then(d=>setSessions(d.sessions||[])).catch(console.error);
  function hydrateRun(baseMessages, run){
    let next=[...(baseMessages||[])].filter(x=>x.id!=='live');
    if(run?.user && !next.some(x=>x.id===run.user.id)) next.push(run.user);
    if(run?.running || run?.text){
      next=next.filter(x=>x.id!=='live');
      next.push({id:'live',role:'assistant',content:run.text||'正在执行…',created_at:run.started_at||Date.now()/1000,error:!!run.error});
    }
    return next;
  }
  async function pollRun(id){
    try{
      const d=await jfetch('/api/run/'+id);
      const run=d.run;
      if(!run){ setBusy(false); await load(id, false); refreshSessions(); return false; }
      setBusy(!!run.running);
      setMessages(m=>hydrateRun(m, run));
      return !!run.running;
    }catch(e){ console.error(e); return false; }
  }
  async function ensure(){ let id=sid; if(!id){ const d=await jfetch('/api/session/new',{method:'POST'}); id=d.id; localStorage.gaReactSid=id; setSid(id);} return id; }
  async function load(id, startPoll=true){ localStorage.gaReactSid=id; setSid(id); const d=await jfetch('/api/session/'+id); const sessionSettings=cleanSettings(d.settings||{}); setSettings(sessionSettings); setMessages(hydrateRun(d.messages||[], d.run)); setBusy(!!d.run?.running); if(startPoll && d.run?.running) pollRun(id); jfetch('/api/state/'+id).then(s=>{setState(s); if(s.settings) setSettings(cleanSettings(s.settings));}); }
  useEffect(()=>{ensure().then(load); refreshSessions();},[]);
  useEffect(()=>{
    if(!sid || !busy) return;
    const t=setInterval(()=>pollRun(sid), 1000);
    return ()=>clearInterval(t);
  },[sid,busy]);
  function isNearBottom(el){ return !el || (el.scrollHeight - el.scrollTop - el.clientHeight) < 96; }
  function scrollToBottom(behavior='smooth'){
    bottom.current?.scrollIntoView({behavior});
  }
  function onChatScroll(e){
    setFollow(isNearBottom(e.currentTarget));
  }
  useEffect(()=>{ if(follow) scrollToBottom('smooth'); },[messages,busy,follow]);
  async function newChat(){ const d=await jfetch('/api/session/new',{method:'POST'}); await load(d.id); refreshSessions(); }
  async function del(id){ await fetch('/api/session/'+id,{method:'DELETE'}); if(id===sid) await newChat(); refreshSessions(); }
  async function updateSetting(patch){
    const next=cleanSettings({...settings,...patch});
    setSettings(next);
    const id=await ensure();
    const d=await jfetch('/api/settings/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)});
    setState(s=>({...s,...d}));
  }
  async function send(prompt,files){
    const id=await ensure();
    const payloadSettings=cleanSettings(settings);
    const userMsg={id:uid(),role:'user',content:prompt,files:(files||[]).map(f=>({name:f.name,type:f.type,mime:f.type,isImage:(f.type||'').startsWith('image/'),url:f.preview||''})),created_at:Date.now()/1000};
    setSettings(payloadSettings);
    setFollow(true);
    setBusy(true);
    setMessages(m=>[...m,userMsg,{id:'live',role:'assistant',content:'正在处理附件…',created_at:Date.now()/1000}]);
    try{
      const payloadFiles=[];
      for(const f of files||[]){
        setMessages(m=>m.map(x=>x.id==='live'?{...x,content:`正在处理附件：${f.name} …`}:x));
        payloadFiles.push(await fileToPayload(f.file));
      }
      const body = JSON.stringify({prompt,files:payloadFiles,settings:payloadSettings,client_user_id:userMsg.id});
      const bodyBytes = bytesOfText(body);
      if(bodyBytes > MAX_JSON_BYTES){
        throw new Error(`附件仍然过大：${(bodyBytes/1024/1024).toFixed(1)}MB，已超过 ${(MAX_JSON_BYTES/1024/1024).toFixed(0)}MB。请裁剪图片或减少文件数量。`);
      }
      setMessages(m=>m.map(x=>x.id==='live'?{...x,content:`已压缩并上传请求（${(bodyBytes/1024/1024).toFixed(2)}MB），等待模型响应…`}:x));
      const r=await fetch('/api/chat/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body});
      if(!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      if(!r.body) throw new Error('浏览器没有返回可读取的响应流');
      const reader=r.body.getReader(); const dec=new TextDecoder(); let buf='';
      while(true){
        const {value,done}=await reader.read(); if(done) break;
        buf+=dec.decode(value,{stream:true}); let lines=buf.split('\n'); buf=lines.pop();
        for(const line of lines){
          if(!line.trim()) continue;
          let ev; try{ ev=JSON.parse(line); }catch(e){ console.warn('bad stream line', line); continue; }
          if(ev.type==='delta') setMessages(m=>m.map(x=>x.id==='live'?{...x,content:ev.text}:x));
          if(ev.type==='done'||ev.type==='error') setMessages(m=>m.filter(x=>x.id!=='live').concat(ev.message));
        }
      }
    }catch(e){
      const msg={id:uid(),role:'assistant',content:`发送失败：${e?.message||e}\n\n如果是大图，请先压缩后重试；如果当前模型不支持视觉，请切换到支持图片的模型。`,created_at:Date.now()/1000};
      setMessages(m=>m.filter(x=>x.id!=='live').concat(msg));
    }finally{
      setBusy(false);
      refreshSessions();
    }
  }
  async function abort(){ if(sid) await jfetch('/api/abort/'+sid,{method:'POST'}); setBusy(false); }
  return <div className="app"><aside><div className="brand"><Bot/> <b>GeneraticAgent</b></div><button className="new" onClick={newChat}><Plus size={16}/> 新会话</button><div className="session-list">{sessions.map(s=><div className={'session '+(s.id===sid?'active':'')} key={s.id}><button onClick={()=>load(s.id)}><b>{s.title}</b><span>{fmtTime(s.updated_at)} · {s.count}条</span></button><button className="trash" onClick={()=>del(s.id)}><Trash2 size={14}/></button></div>)}</div><SettingsPanel state={state}/></aside><main><header><h1>GA Chat</h1><p>独立 React 前端 · 会话持久化 · 图片/文件 · 模型切换</p></header><div className="chat-wrap"><div className="chat" ref={chatRef} onScroll={onChatScroll}>{messages.length?messages.map(m=><Message key={m.id} m={m}/>):<div className="empty"><ImageIcon/>开始一个新对话，可直接粘贴图片。</div>}<div ref={bottom}/></div>{!follow?<button className="follow-btn" onClick={()=>{setFollow(true); scrollToBottom('smooth')}}>↓ 返回跟随</button>:null}</div><Composer onSend={send} busy={busy} onAbort={abort} state={state} settings={settings} updateSetting={updateSetting}/></main></div>
}

createRoot(document.getElementById('root')).render(<App/>);
