'use strict';
let setRows=[],setFolders=[],setStorage='sd',setStorageReadOnly=false,setCatalogLoad=0,setDraft=null,setBank=0,setPad=0,setDirty=false,setBusy=false,setMessageTimer=null,setPickSource='sd',setPickPath='',setStage=null,setPlaying=null,setPendingKit=null;
const setAudioExtensions=/\.(wav|aif|aiff|flac|mp3|ogg)$/i;
const setImportExtensions=/\.(wav|aif|aiff|flac|mp3|ogg|xml|xpm|mxgrp|mxsnd|mxinst|nksf|nksn|nki|ncw|nkx|json|txt|png|jpg|jpeg|sxq|mid|midi)$/i;
const setEmptyBank=(name='Bank A')=>({name,pads:Array(16).fill(null)});
function setMessage(text,error=false,temporary=false){clearTimeout(setMessageTimer);$('set-message').textContent=text;$('set-message').className=error?'error':'';if(temporary)setMessageTimer=setTimeout(()=>{$('set-message').textContent=''},5000)}
function setChanged(){setDirty=true;$('set-save').textContent='Save kit •';}
function setCanLeave(){return !setDirty||confirm('Discard the unsaved changes to this sample kit?');}
function setEdit(value=null){setStop();setDraft=value||{name:'',banks:[setEmptyBank()],notes:[]};setBank=0;setPad=0;setDirty=false;$('set-name').value=setDraft.name;setRender();}
function setRender(){
 if(!setDraft)return;const bank=setDraft.banks[setBank];$('set-banks').replaceChildren();
 setDraft.banks.forEach((row,i)=>{const b=element('button',row.name);b.type='button';b.setAttribute('aria-pressed',String(i===setBank));b.disabled=setBusy;b.onclick=()=>{setStop();setBank=i;setPad=0;setRender()};$('set-banks').append(b)});
 $('set-grid').replaceChildren();for(const slot of [12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3]){
  const pad=bank.pads[slot],b=element('button',undefined,'set-pad'+(pad?' loaded':'')+(slot===setPad?' selected':''));b.type='button';b.disabled=setBusy;b.dataset.pad=slot;b.setAttribute('aria-pressed',String(slot===setPad));b.setAttribute('aria-label','Pad '+(slot+1)+(pad?': '+pad.name:' empty'));
  b.append(element('span',String(slot+1).padStart(2,'0'),'set-pad-number'),element('span',pad?.name||'Drop sample','set-pad-title'),element('span',pad?'▶'+(pad.layers>1?' · '+pad.layers+' layers':''):'+','set-pad-play'));
  b.draggable=Boolean(pad);b.ondragstart=e=>{e.dataTransfer.setData('application/x-machinista-pad',JSON.stringify({bank:setBank,pad:slot}));e.dataTransfer.effectAllowed='move'};
  b.onclick=()=>{setPad=slot;setRender();if(pad)setPreview(pad,slot)};
  b.ondragover=e=>{e.preventDefault();e.stopPropagation();b.classList.add('over')};b.ondragleave=()=>b.classList.remove('over');
  b.ondrop=e=>{e.preventDefault();e.stopPropagation();b.classList.remove('over');if(setBusy)return;const transfer=e.dataTransfer;if(transfer.files.length===1&&/\.mxgrp$/i.test(transfer.files[0].name)){setImport(setDropEntries(transfer));return}const moved=transfer.getData('application/x-machinista-pad'),sample=transfer.getData('application/x-machinista-sample');if(moved){try{const from=JSON.parse(moved),source=setDraft.banks[from.bank];if(!source||!Number.isInteger(from.pad)||from.pad<0||from.pad>15)return;[source.pads[from.pad],bank.pads[slot]]=[bank.pads[slot],source.pads[from.pad]];setPad=slot;setChanged();setRender()}catch{}return}if(sample){try{const ref=JSON.parse(sample);bank.pads[slot]={name:ref.name.replace(/\.[^.]+$/,''),asset:ref};setPad=slot;setChanged();setRender()}catch{}return}const entries=setDropEntries(transfer);setPlaceFiles(entries,slot)};
  if(setPlaying===slot)b.classList.add('playing');$('set-grid').append(b)
 }
 const pad=bank.pads[setPad];$('set-pad-label').textContent='PAD '+(setPad+1)+' · '+bank.name;$('set-pad-name').value=pad?.name||'';$('set-pad-name').disabled=!pad||setBusy;$('set-pad-clear').disabled=!pad||setBusy;
 $('set-bank-remove').disabled=setBusy||setDraft.banks.length===1;$('set-bank-add').disabled=setBusy||setDraft.banks.length>=128;
 for(const id of ['set-save','set-save-as','set-name','set-bank-rename','set-pad-pick','set-new','set-delete','set-refresh','set-file','set-folder','set-kit-folder','set-folder-new','set-preview-file'])$(id).disabled=setBusy;
 const destination=$('set-destination'),folder=setDraft.expansion||'';
 destination.replaceChildren(new Option('Sample Kits', ''),...setFolders.map(name=>new Option(name,name)));
 if(folder&&!setFolders.includes(folder))destination.add(new Option(folder,folder));
 destination.value=folder;
 destination.disabled=setBusy||Boolean(setDraft.id);
 $('set-storage').disabled=setBusy;
 for(const id of ['set-save','set-save-as','set-delete','set-folder-new','set-file','set-folder'])$(id).disabled=setBusy||setStorageReadOnly;
 $('set-kit-preview').hidden=!setDraft.preview;
 $('set-kit-preview').disabled=setBusy;
 $('set-kit-folder-label').hidden=!setPendingKit;
 $('set-save').textContent=setDirty?'Save kit •':'Save kit';$('set-save-as').hidden=!setDraft.id;$('set-delete').hidden=!setDraft.id;$('set-download').hidden=!setDraft.id;
 if(setDraft.id){$('set-download').href='/api/sets/file?'+new URLSearchParams({id:setDraft.id});$('set-download').download=(setDraft.name||'Sample Kit')+'.zip'}
 $('set-notes').replaceChildren(...(setDraft.notes||[]).map(note=>element('li',note)));setCatalog();
}
function setCatalog(){
 const list=$('set-list'),query=$('set-search').value.toLowerCase(),folders=new Map();
 // Re-rendering after a pad edit must not close an opened folder.
 const expanded=new Set(Array.from(list.querySelectorAll('details[open]'),node=>node.dataset.expansion));
 list.replaceChildren();
 const matches=setRows.filter(row=>row.name.toLowerCase().includes(query)||(row.expansion||'').toLowerCase().includes(query));
 const names=new Set([...setFolders,...matches.map(row=>row.expansion).filter(Boolean)]);
 for(const folder of [...names].sort((a,b)=>a.localeCompare(b))){
  const contents=matches.filter(row=>row.expansion===folder);
  if(!folder.toLowerCase().includes(query)&&!contents.length)continue;
  const details=element('details'),heading=element('summary',folder);
  details.dataset.expansion=folder;
  details.open=Boolean(query)||expanded.has(folder)||setDraft?.expansion===folder;
  const remove=element('button','Delete folder');
  remove.type='button';remove.disabled=setBusy||setStorageReadOnly;
  remove.setAttribute('aria-label','Delete folder '+folder);
  remove.onclick=()=>setFolderDelete(folder);
  details.append(heading,remove);list.append(details);folders.set(folder,details);
  if(!contents.length)details.append(element('p','No kits in this folder.','muted small'));
 }
 for(const row of matches){
  const parent=folders.get(row.expansion)||list;
  const button=element('button',undefined,'set-card');
  button.type='button';button.disabled=setBusy;
  button.setAttribute('aria-pressed',String(row.id===setDraft?.id));
  button.append(element('strong',row.name),element('span',(row.banks||1)+' bank'+((row.banks||1)===1?'':'s')+' · '+row.pads+' pads','muted small'));
  button.onclick=async()=>{
   if(!setCanLeave())return;
   setPendingKit=null;
   try{setEdit(await api('/api/sets/item?'+new URLSearchParams({id:row.id})))}
   catch(e){setMessage(e.message,true)}
  };
  const entry=element('div',undefined,'set-catalog-entry');
  entry.append(button);
  if(row.preview){
   const preview=element('button','▶','set-preview-icon');
   preview.type='button';preview.disabled=setBusy;
   preview.setAttribute('aria-label','Play preview of '+row.name);
   preview.title='Play preview';
   preview.onclick=()=>setPlayKitPreview(row.preview,row.name);
   entry.append(preview);
  }
  parent.append(entry);
 }
 if(!list.children.length)list.append(element('p',setRows.length||setFolders.length?'No matching kits.':'No kits on this storage. Drop a folder or build your first kit.','muted small'));
}
async function sampleSetsLoad(){
 const load=++setCatalogLoad;
 try{
  const sources=await api('/api/sources');
  if(load!==setCatalogLoad)return;
  if(!sources.some(source=>source.id===setStorage)){
   setStorage='sd';setPendingKit=null;setStage=null;setEdit();
   setMessage('USB storage disconnected. Showing SD CARD.',true);
  }
  const select=$('set-storage');
  select.replaceChildren(...sources.map(source=>new Option(source.name,source.id)));
  select.value=setStorage;
  setStorageReadOnly=Boolean(sources.find(source=>source.id===setStorage)?.readOnly);
  const query=new URLSearchParams({storage:setStorage});
  const [rows,folders]=await Promise.all([api('/api/sets?'+query),api('/api/sets/folders?'+query)]);
  if(load!==setCatalogLoad)return;
  setRows=rows;setFolders=folders;
  if(!setDraft)setEdit();else setRender();
 }catch(e){if(load===setCatalogLoad)setMessage(e.message,true)}
}
$('set-storage').onchange=async()=>{
 const select=$('set-storage'),storage=select.value;
 if(!setCanLeave()){select.value=setStorage;return}
 setStorage=storage;setPendingKit=null;setStage=null;setRows=[];setFolders=[];setBusy=true;setEdit();
 try{await sampleSetsLoad()}finally{setBusy=false;setRender()}
};
async function setPost(url,value){return api(url,{method:'POST',headers:{'Content-Type':'application/json','X-Machinista-Token':token},body:JSON.stringify(value)})}
function setStop(){const audio=$('set-preview');audio.pause();audio.removeAttribute('src');setPlaying=null;for(const b of $('set-grid').children)b.classList.remove('playing')}
function setPreview(pad,slot){setStop();if(!pad.asset){setMessage('This pad has no sample to preview.');return}const audio=$('set-preview');audio.src=pad.preview||'/api/sets/audio?'+new URLSearchParams({ref:JSON.stringify(pad.asset)});$('set-preview-name').textContent='Pad '+(slot+1)+' · '+pad.name;setPlaying=slot;const button=$('set-grid').querySelector('[data-pad="'+slot+'"]');button?.classList.add('playing');audio.play().catch(()=>setMessage('Preview could not start. Save the kit to convert imported audio, or use the player controls.',true))}
function setPlayKitPreview(ref,name){
 if(!ref)return;
 setStop();
 const audio=$('set-preview');
 audio.src='/api/sets/audio?'+new URLSearchParams({ref:JSON.stringify(ref)});
 $('set-preview-name').textContent=name+' · Kit preview';
 audio.play().catch(()=>setMessage('Kit preview could not start.',true));
}
$('set-kit-preview').onclick=()=>setPlayKitPreview(setDraft.preview,setDraft.name);
$('set-preview').onended=()=>{setPlaying=null;for(const b of $('set-grid').children)b.classList.remove('playing')};$('set-preview-stop').onclick=setStop;
$('tab-sets').onclick=()=>workspace('sets');$('set-refresh').onclick=sampleSetsLoad;$('set-search').oninput=setCatalog;
$('set-new').onclick=()=>{if(setCanLeave()){setPendingKit=null;setEdit()}};$('set-name').oninput=()=>{setDraft.name=$('set-name').value;setChanged()};
$('set-destination').onchange=()=>{setDraft.expansion=$('set-destination').value;setChanged()};
$('set-folder-new').onclick=async()=>{
 if(setBusy)return;
 const name=prompt('New sample kit folder name')?.trim();
 if(!name)return;
 setBusy=true;setRender();
 try{
  const result=await setPost('/api/sets/folders/create',{name,storage:setStorage});
  if(!setDraft.id)setDraft.expansion=result.name;
  await sampleSetsLoad();
  setMessage('Created '+result.name+'.',false,true);
 }catch(e){setMessage(e.message,true)}
 finally{setBusy=false;setRender()}
};
async function setFolderDelete(name){
 if(setBusy||!confirm('Permanently delete "'+name+'" and all kits inside it?'))return;
 if(setDraft.expansion===name&&!setCanLeave())return;
 setBusy=true;setRender();
 try{
  const result=await setPost('/api/sets/folders/delete',{name,confirmed:true,storage:setStorage});
  if(setDraft.expansion===name)setEdit();
  await sampleSetsLoad();
  setMessage(result.message,false,true);
 }catch(e){setMessage(e.message,true)}
 finally{setBusy=false;setRender()}
}
$('set-pad-name').oninput=()=>{const pad=setDraft.banks[setBank].pads[setPad];if(pad){pad.name=$('set-pad-name').value;setChanged();const node=$('set-grid').querySelector('[data-pad="'+setPad+'"] .set-pad-title');if(node)node.textContent=pad.name}};
$('set-pad-clear').onclick=()=>{if(!confirm('Clear Pad '+(setPad+1)+' from this bank?'))return;setStop();setDraft.banks[setBank].pads[setPad]=null;setChanged();setRender()};
$('set-bank-add').onclick=()=>{setDraft.banks.push(setEmptyBank('Bank '+(setDraft.banks.length<26?String.fromCharCode(65+setDraft.banks.length):setDraft.banks.length+1)));setBank=setDraft.banks.length-1;setPad=0;setStop();setChanged();setRender()};
$('set-bank-rename').onclick=()=>{const name=prompt('Bank name',setDraft.banks[setBank].name);if(name?.trim()){setDraft.banks[setBank].name=name.trim().slice(0,80);setChanged();setRender()}};
$('set-bank-remove').onclick=()=>{if(!confirm('Remove '+setDraft.banks[setBank].name+' and all its pad assignments?'))return;setDraft.banks.splice(setBank,1);setBank=Math.max(0,setBank-1);setStop();setChanged();setRender()};
async function setSave(copy=false){if(setBusy)return;setDraft.name=$('set-name').value.trim();if(!setDraft.name){setMessage('Enter a sample kit name.',true);$('set-name').focus();return}if(setDraft.id&&!copy&&!confirm('Save changes to "'+setDraft.name+'"?'))return;setBusy=true;setRender();setMessage('Saving and collecting samples…');try{const value={...JSON.parse(JSON.stringify(setDraft)),storage:setStorage};if(copy){delete value.id;delete value.revision}const result=await setPost('/api/sets/save',value);setPendingKit=null;setEdit(await api('/api/sets/item?'+new URLSearchParams({id:result.id})));await sampleSetsLoad();setMessage('Saved '+result.name+'. Available on the controller under BROWSE → SAMPLE KITS.',false,true)}catch(e){setMessage(e.message,true)}finally{setBusy=false;setRender()}}
$('set-save').onclick=()=>setSave();$('set-save-as').onclick=()=>setSave(true);
$('set-delete').onclick=async()=>{if(setBusy||!setDraft.id||!confirm('Permanently delete "'+setDraft.name+'" and its banks?'))return;setBusy=true;setRender();try{const result=await setPost('/api/sets/delete',{id:setDraft.id,revision:setDraft.revision,confirmed:true});setEdit();await sampleSetsLoad();setMessage(result.message,false,true)}catch(e){setMessage(e.message,true)}finally{setBusy=false;setRender()}};
async function setStageStart(){if(!setStage)setStage=(await setPost('/api/sets/stage/start',{storage:setStorage})).id;return setStage}
function setRawUpload(url,file,progress){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',url);xhr.setRequestHeader('X-Machinista-Token',token);xhr.timeout=20*60*1000;xhr.upload.onprogress=e=>{if(e.lengthComputable&&progress)progress(e.loaded/e.total)};xhr.onload=()=>{let value;try{value=JSON.parse(xhr.responseText)}catch{reject(new Error('Transfer interrupted.'));return}if(xhr.status>=200&&xhr.status<300)resolve(value);else reject(new Error(value.error||'Transfer failed.'))};xhr.onerror=()=>reject(new Error('Network error.'));xhr.ontimeout=()=>reject(new Error('Transfer timed out.'));xhr.send(file)})}
function setDropEntries(transfer){const items=Array.from(transfer.items||[]);const entries=items.map(item=>item.webkitGetAsEntry?.()).filter(Boolean);return {entries,files:Array.from(transfer.files||[])}}
async function setCollect(drop){const rows=[];async function walk(entry,prefix=''){if(rows.length>=8192)throw new Error('Use at most 8,192 files.');if((entry.name.startsWith('.')&&entry.name!=='.previews')||entry.name==='__MACOSX')return;if(entry.isFile){const file=await new Promise((ok,no)=>entry.file(ok,no));rows.push({file,path:prefix+file.name});return}if(entry.isDirectory){const reader=entry.createReader();for(;;){const entries=await new Promise((ok,no)=>reader.readEntries(ok,no));if(!entries.length)break;for(const child of entries)await walk(child,prefix+entry.name+'/')}}}
 if(drop.entries.length)for(const entry of drop.entries)await walk(entry);else for(const file of drop.files)rows.push({file,path:file.webkitRelativePath||file.name});return rows}
async function setPlaceFiles(drop,slot){if(setBusy)return;setBusy=true;setRender();$('set-progress').hidden=false;try{const rows=(await setCollect(drop)).filter(row=>setAudioExtensions.test(row.file.name)).sort((a,b)=>a.path.localeCompare(b.path,undefined,{numeric:true}));if(!rows.length)throw new Error('Drop WAV, AIFF, FLAC, MP3 or OGG samples on a pad.');if(Math.ceil((setBank*16+slot+rows.length)/16)>128)throw new Error('Maximum 128 banks.');if(rows.reduce((sum,r)=>sum+r.file.size,0)>1024**3)throw new Error('Maximum 1 GiB per import.');if(rows.some((_,i)=>setDraft.banks[Math.floor((setBank*16+slot+i)/16)]?.pads[(slot+i)%16])&&!confirm('Replace the occupied pads in this range?'))return;
 const upload=await setStageStart();let position=setBank*16+slot;for(let i=0;i<rows.length;i++){const row=rows[i];setMessage('Uploading '+(i+1)+' / '+rows.length+' · '+row.file.name);const relative=crypto.randomUUID()+'/'+row.file.name;const result=await setRawUpload('/api/sets/stage/file?'+new URLSearchParams({upload,path:relative}),row.file,f=>{$('set-progress').value=100*(i+f)/rows.length});while(setDraft.banks.length<=Math.floor(position/16))setDraft.banks.push(setEmptyBank('Bank '+(setDraft.banks.length+1)));setDraft.banks[Math.floor(position/16)].pads[position%16]={name:row.file.name.replace(/\.[^.]+$/,''),asset:result.asset,preview:URL.createObjectURL(row.file)};position++;setChanged()}
 if(!setDraft.name&&rows[0].path.includes('/')){setDraft.name=rows[0].path.split('/')[0];$('set-name').value=setDraft.name}setMessage(rows.length+' sample(s) placed. Save the kit to keep it.',false,true)
 }catch(e){setMessage(e.message,true)}finally{setBusy=false;$('set-progress').hidden=true;setRender()}}
async function setKitMedia(rows, kitFile, upload, notes, kitPath=''){
 const location=kitPath.toLowerCase().split('/').slice(0,-1);
 const expected=[...location,'.previews',kitFile.toLowerCase()+'.ogg'].join('/');
 const matches=rows.filter(row=>kitPath?row.path.toLowerCase()===expected:
  row.path.toLowerCase().endsWith('/.previews/'+kitFile.toLowerCase()+'.ogg'));
 const result={artwork:{}};
 const put=async(file,path,limit)=>{
  if(file.size>limit)throw new Error('File exceeds import limit.');
  return (await setRawUpload('/api/sets/stage/file?'+new URLSearchParams({upload,path}),file)).asset;
 };
 if(matches.length===1){
  try{result.preview=await put(matches[0].file,'kit-preview.ogg',8*1024**2)}
  catch{notes.push('The kit preview could not be uploaded.')}
 }
 const images=rows.filter(row=>row.path.toLowerCase().includes('/paresources/image/'));
 for(const [kind,choices] of Object.entries({artwork:['mst_artwork.png','vb_artwork.png'],logo:['oso_logo.png','vb_logo.png','mst_logo.png']})){
  const row=choices.map(name=>images.find(row=>row.file.name.toLowerCase()===name)).find(Boolean);
  if(!row)continue;
  try{result.artwork[kind]=await put(row.file,'kit-'+kind+'.png',2*1024**2)}
  catch{notes.push('The kit '+kind+' could not be uploaded.')}
 }
 return result;
}
$('set-preview-file').onchange=async()=>{
 const input=$('set-preview-file'),file=input.files[0];
 if(!file||setBusy)return;
 setBusy=true;setRender();
 try{
  if(file.size>8*1024**2||!/\.(ogg|wav)$/i.test(file.name))throw new Error('Choose OGG or WAV up to 8 MiB.');
  const upload=await setStageStart();
  const path='preview-'+Date.now()+file.name.slice(-4).toLowerCase();
  setDraft.preview=(await setRawUpload('/api/sets/stage/file?'+new URLSearchParams({upload,path}),file)).asset;
  setChanged();setMessage('Preview attached. Save kit to keep it.',false,true);
 }catch(error){setMessage(error.message,true)}
 finally{input.value='';setBusy=false;setRender()}
};
function setOpenKit(kit,keepFolderPicker=false){
 const bank=setEmptyBank(kit.name);
 kit.pads.forEach((pad,index)=>{bank.pads[index]={name:pad.name,asset:pad.asset}});
 if(!keepFolderPicker)setPendingKit=null;
 setEdit({name:kit.name,banks:[bank],notes:kit.notes,preview:kit.preview,artwork:kit.artwork,expansion:kit.expansion});setChanged();
 setMessage('Kit ready. Preview or rearrange its pads, then choose Save kit.');
}
async function setImportKit(file){
 if(file.size>8*1024**2)throw new Error('Maximum 8 MiB per Maschine Group.');
 const kit=await setRawUpload('/api/sets/inspect-mxgrp?'+new URLSearchParams({name:file.name}),file);
 const missing=kit.pads.filter(pad=>!pad.asset);
 kit.filename=file.name;
 setPendingKit=kit;
 if(!missing.length){setOpenKit(kit,true);kit.draft=setDraft;setMessage('Kit ready. Locate the expansion folder to include artwork and preview.');return}
 setMessage('Locate the expansion folder containing Samples. '+missing.length+' pad(s) need audio files.');
}
$('set-kit-folder').onchange=async()=>{
 const input=$('set-kit-folder'),kit=setPendingKit;
 if(!kit||setBusy||!input.files.length)return;
 setBusy=true;setRender();$('set-progress').hidden=false;
 try{
  const rows=Array.from(input.files,file=>({file,path:file.webkitRelativePath}));
  const files=new Map();
  for(const {file} of rows){
   const path=file.webkitRelativePath.toLowerCase().split('/');
   const index=path.lastIndexOf('samples');
   if(index<0||!/\.wav$/i.test(file.name))continue;
   const key=path.slice(index).join('/');
   files.set(key,files.has(key)?null:file);
  }
  const missing=kit.pads.filter(pad=>!pad.asset);
  const unresolved=missing.find(pad=>!files.get(pad.path.toLowerCase()));
  if(unresolved)throw new Error('Missing or ambiguous sample: '+unresolved.path+'. Select the matching expansion folder.');
  const selected=[...new Set(missing.map(pad=>pad.path.toLowerCase()))];
  if(selected.reduce((sum,key)=>sum+files.get(key).size,0)>1024**3)throw new Error('Maximum 1 GiB of kit samples.');
  const upload=(await setPost('/api/sets/stage/start',{storage:setStorage})).id,assets=new Map();
  for(let i=0;i<selected.length;i++){
   const key=selected[i],file=files.get(key);
   setMessage('Uploading kit sample '+(i+1)+' / '+selected.length+' · '+file.name);
   const result=await setRawUpload('/api/sets/stage/file?'+new URLSearchParams({upload,path:i+'/'+file.name}),file,f=>{$('set-progress').value=100*(i+f)/selected.length});
   assets.set(key,result.asset);
  }
  const kitRows=rows.filter(row=>row.file.name.toLowerCase()===kit.filename.toLowerCase());
  const kitPath=kitRows.length===1?kitRows[0].path:'';
  const media=await setKitMedia(rows,kit.filename,upload,kit.notes,kitPath);
  const expansion=rows[0].path.split('/')[0];
  if(kit.draft===setDraft&&!missing.length){
   Object.assign(setDraft,media,{expansion});setPendingKit=null;setChanged();
   setMessage('Expansion media attached. Save kit to keep it.');
  }else{
   for(const pad of missing)pad.asset=assets.get(pad.path.toLowerCase());
   setOpenKit({...kit,...media,expansion});
  }
 }catch(e){setMessage(e.message,true)}
 finally{input.value='';setBusy=false;$('set-progress').hidden=true;setRender()}
};
async function setImportExpansionKits(rows, kits){
 const waves=new Map();
 for(const row of rows){
  const key=row.path.toLowerCase();
  if(/\.wav$/.test(key))waves.set(key,waves.has(key)?null:row.file);
 }
 const failures=[];
 let saved=0,first=null,previewCount=0;
 for(const [index,row] of kits.entries()){
  $('set-progress').value=100*index/kits.length;
  setMessage('Importing kit '+(index+1)+' / '+kits.length+' · '+row.file.name);
  let upload;
  try{
   if(row.file.size>8*1024**2)throw new Error('Maximum 8 MiB per Maschine Group.');
   const query=new URLSearchParams({name:row.file.name,local:'1'});
   const kit=await setRawUpload('/api/sets/inspect-mxgrp?'+query,row.file);
   // Locate the expansion root above Groups. Match full relative
   // paths within one expansion so another kit's same-named WAV can't win.
   const directory=row.path.toLowerCase().split('/').slice(0,-1);
   const groupFolder=directory.lastIndexOf('groups');
   if(groupFolder>=0)directory.length=groupFolder;
   const expansion=row.path.split('/')[directory.length-1]||'Expansion';
   const sources=kit.pads.map(pad=>{
    const file=waves.get([...directory,pad.path.toLowerCase()].join('/'));
    if(!file)throw new Error('Missing or ambiguous sample: '+pad.path);
    return file;
   });
   const files=[...new Set(sources)];
   if(files.reduce((sum,file)=>sum+file.size,0)>1024**3)throw new Error('Maximum 1 GiB of audio per kit.');
   upload=(await setPost('/api/sets/stage/start',{storage:setStorage})).id;
   const assets=new Map();
   for(const [position,file] of files.entries()){
    const query=new URLSearchParams({upload,path:position+'/'+file.name});
    const result=await setRawUpload('/api/sets/stage/file?'+query,file,
     fraction=>{$('set-progress').value=100*(index+(position+fraction)/files.length)/kits.length});
    assets.set(file,result.asset);
   }
   const bank=setEmptyBank(kit.name);
   kit.pads.forEach((pad,slot)=>{bank.pads[slot]={name:pad.name,asset:assets.get(sources[slot])}});
   const prefix=directory.length?directory.join('/')+'/':'';
   const media=await setKitMedia(rows.filter(row=>row.path.toLowerCase().startsWith(prefix)),row.file.name,upload,kit.notes,row.path);
   const result=await setPost('/api/sets/save',{name:kit.name,banks:[bank],notes:kit.notes,expansion,...media,storage:setStorage});
   first??=result.id;
   previewCount+=Number(Boolean(media.preview));
   saved++;
  }catch(error){
   failures.push(row.path+' · '+error.message);
  }finally{
   if(upload)await setPost('/api/sets/stage/discard',{upload}).catch(()=>{});
  }
 }
 if(first)setEdit(await api('/api/sets/item?'+new URLSearchParams({id:first})));
 await sampleSetsLoad();
 $('set-import-errors').replaceChildren(...failures.map(error=>element('li',error)));
 setMessage('Saved '+saved+' of '+kits.length+' kits · '+previewCount+' previews supplied.'+(previewCount<saved?' Use a ZIP to include hidden previews.':'')+(failures.length?' See skipped kits below.':''),Boolean(failures.length));
}
async function setImport(drop){if(setBusy||!setCanLeave())return;if(setStorageReadOnly){setMessage('This storage is read-only.',true);return}setBusy=true;setRender();$('set-progress').hidden=false;setMessage('Reading expansion…');$('set-import-errors').replaceChildren();try{const rows=await setCollect(drop);if(!rows.length)throw new Error('No files found.');setPendingKit=null;let result;
 if(rows.length===1&&/\.mxgrp$/i.test(rows[0].file.name)){await setImportKit(rows[0].file);return}
 const kits=rows.filter(row=>/\.mxgrp$/i.test(row.file.name));
 if(kits.length){kits.sort((a,b)=>a.path.localeCompare(b.path));await setImportExpansionKits(rows,kits);return}
 if(rows.length===1&&/\.(zip|xpn)$/i.test(rows[0].file.name)){const file=rows[0].file;if(file.size>1024**3)throw new Error('Maximum 1 GiB per archive.');result=await setRawUpload('/api/sets/import?'+new URLSearchParams({name:file.name,storage:setStorage}),file,f=>{$('set-progress').value=100*f;if(f===1)setMessage('Converting samples and building pad banks…')})}
 else{const filtered=rows.filter(row=>setImportExtensions.test(row.file.name));if(!filtered.some(row=>setAudioExtensions.test(row.file.name)))throw new Error('No readable audio found. Choose an installed expansion folder; installers and protected content cannot be converted.');if(filtered.reduce((sum,r)=>sum+r.file.size,0)>1024**3)throw new Error('Maximum 1 GiB per folder.');const upload=(await setPost('/api/sets/stage/start',{storage:setStorage})).id;for(let i=0;i<filtered.length;i++){const row=filtered[i];setMessage('Uploading '+(i+1)+' / '+filtered.length+' · '+row.file.name);await setRawUpload('/api/sets/stage/file?'+new URLSearchParams({upload,path:row.path}),row.file,f=>{$('set-progress').value=100*(i+f)/filtered.length})}setMessage('Converting samples and building pad banks…');const name=rows[0].path.includes('/')?rows[0].path.split('/')[0]:'Sample Kit';result=await setPost('/api/sets/import-folder',{upload,name,storage:setStorage})}
 if(result.previews!==undefined){
  if(result.id)setEdit(await api('/api/sets/item?'+new URLSearchParams({id:result.id})));
  else if(setDraft.id)setEdit(await api('/api/sets/item?'+new URLSearchParams({id:setDraft.id})));
  await sampleSetsLoad();
  $('set-import-errors').replaceChildren(...result.failures.map(error=>element('li',error)));
  setMessage(result.total!==undefined?
   'Saved '+result.kits+' of '+result.total+' kits · '+result.previews+' previews.':
   'Added '+result.updated+' previews to '+result.name+' · '+result.previews+' available.',Boolean(result.failures.length));
  return;
 }
 setEdit(await api('/api/sets/item?'+new URLSearchParams({id:result.id})));await sampleSetsLoad();setMessage('Imported '+result.name+' · '+setDraft.banks.length+' bank(s).'+(result.notes?.length?' See import details below.':''),false,true)
 }catch(e){setMessage(e.message,true)}finally{setBusy=false;$('set-progress').hidden=true;setRender();$('set-file').value='';$('set-folder').value=''}}
$('set-file').onchange=()=>setImport({entries:[],files:Array.from($('set-file').files)});$('set-folder').onchange=()=>setImport({entries:[],files:Array.from($('set-folder').files)});
const setDrop=$('set-dropzone');setDrop.ondragover=e=>{e.preventDefault();setDrop.classList.add('over')};setDrop.ondragleave=()=>setDrop.classList.remove('over');setDrop.ondrop=e=>{e.preventDefault();setDrop.classList.remove('over');setImport(setDropEntries(e.dataTransfer))};
async function setPicker(){try{const data=await api('/api/list?'+new URLSearchParams({source:setPickSource,path:setPickPath}));$('set-picker-path').textContent=setPickPath||'Root folder';$('set-picker-list').replaceChildren();$('set-picker-error').textContent='';for(const row of data.entries){const b=element('button',row.name,'set-pick-row');b.type='button';b.draggable=!row.folder;if(row.folder){b.textContent='Folder · '+row.name;b.onclick=()=>{setPickPath=[setPickPath,row.name].filter(Boolean).join('/');setPicker()}}else{const ref={source:setPickSource,path:setPickPath,name:row.name};b.ondragstart=e=>{e.dataTransfer.setData('application/x-machinista-sample',JSON.stringify(ref));$('set-picker').close()};b.onclick=()=>{if(setDraft.banks[setBank].pads[setPad]&&!confirm('Replace Pad '+(setPad+1)+'?'))return;setDraft.banks[setBank].pads[setPad]={name:row.name.replace(/\.[^.]+$/,''),asset:ref};setChanged();setRender();$('set-picker').close()}}$('set-picker-list').append(b)}}catch(e){$('set-picker-error').textContent=e.message}}
$('set-pad-pick').onclick=async()=>{try{const rows=await api('/api/sources');$('set-picker-source').replaceChildren(...rows.map(r=>new Option(r.name,r.id)));if(!rows.some(r=>r.id===setPickSource))setPickSource=rows[0]?.id||'sd';$('set-picker-source').value=setPickSource;await setPicker();$('set-picker').showModal()}catch(e){setMessage(e.message,true)}};
$('set-picker-source').onchange=()=>{setPickSource=$('set-picker-source').value;setPickPath='';setPicker()};$('set-picker-up').onclick=()=>{setPickPath=setPickPath.split('/').slice(0,-1).join('/');setPicker()};$('set-picker-close').onclick=()=>$('set-picker').close();
window.addEventListener('beforeunload',event=>{if(setDirty||setBusy){event.preventDefault();event.returnValue=''}});
