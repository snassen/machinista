'use strict';
const $=id=>document.getElementById(id);
let hardwareProfile={lv2:true,synth:true,stems:true};
let source='sd',path='',token='',sources=[],uploading=false,listing=0,fileBusy=false,libraryWritable=false;
const bytes=n=>n>=1024**3?(n/1024**3).toFixed(1)+' GiB':n>=1024**2?(n/1024**2).toFixed(1)+' MiB':n>=1024?(n/1024).toFixed(1)+' KiB':n+' B';
const query=extra=>new URLSearchParams({source,path,...extra});
let messageTimer;
function message(text,error=false,temporary=false){clearTimeout(messageTimer);$('message').textContent=text;$('message').className=error?'error':'';if(temporary)messageTimer=setTimeout(()=>{$('message').textContent=''},5000)}
async function api(url,options={}){const response=await fetch(url,options);const value=await response.json();if(!response.ok)throw new Error(value.error||'Connection failed.');return value}
function element(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e}
function breadcrumbs(){const nav=$('breadcrumbs');nav.replaceChildren();const parts=path?path.split('/'):[];[sources.find(s=>s.id===source)?.name||'SD CARD',...parts].forEach((name,i)=>{if(i)nav.append(element('span','/','muted'));const b=element('button',name);b.type='button';b.disabled=uploading;b.onclick=()=>navigate(parts.slice(0,i).join('/'));nav.append(b)})}
function writable(value){libraryWritable=value;$('files').disabled=!value||uploading;$('new-folder').disabled=!value||uploading;$('dropzone').classList.toggle('disabled',!value||uploading)}
async function load(){const version=++listing;breadcrumbs();$('up').disabled=!path||uploading;try{const data=await api('/api/list?'+query());if(version!==listing)return;$('entries').replaceChildren();writable(data.writable);
 for(const item of data.entries){const row=element('tr'),name=element('td'),size=element('td',item.folder?'—':bytes(item.size)),actions=element('td');if(item.folder){const b=element('button','▸  '+item.name,'folder');b.type='button';b.disabled=uploading;b.onclick=()=>navigate(path?path+'/'+item.name:item.name);name.append(b)}else{name.append(element('span','♪','file-icon'),document.createTextNode(item.name));const bar=element('div',undefined,'actions'),preview=element('button','Preview');preview.type='button';preview.onclick=()=>{$('preview-name').textContent=item.name;$('preview').src='/api/file?'+query({name:item.name});$('preview').play().catch(()=>message('Please start playback using the audio player.'))};const dl=element('a','Download');dl.href='/api/file?'+query({name:item.name,download:'1'});dl.download=item.name;bar.append(preview,dl);const split=element('button','Separate stems');split.type='button';split.onclick=()=>window.openStemSeparation({source,path,name:item.name});if(hardwareProfile.stems)bar.append(split);actions.append(bar)}for(const action of ['Move','Delete']){const b=element('button',action);b.type='button';b.disabled=!data.writable||uploading||fileBusy;b.onclick=()=>chooseFile(action.toLowerCase(),item);actions.append(b)}actions.classList.add('file-actions');row.append(name,size,actions);$('entries').append(row)}
 if(!data.entries.length){const row=element('tr'),td=element('td','This folder is empty.');td.colSpan=3;row.append(td);$('entries').append(row)}const folders=data.entries.filter(x=>x.folder).length,samples=data.entries.filter(x=>!x.folder).length;$('count').textContent=folders+' folder'+(folders===1?'':'s')+' · '+samples+' sample'+(samples===1?'':'s')+(data.writable?'':' · read-only');$('connection').textContent='Connected';
 }catch(error){if(version!==listing)return;message(error.message,true);$('connection').textContent='Unreachable';writable(false)}}
function navigate(next){if(uploading||fileBusy)return;path=next;message('');load()}
async function refreshSources(){const fresh=await api('/api/sources');sources=fresh;$('source').replaceChildren();for(const s of sources){const o=element('option',s.name+(s.readOnly?' (read only)':''));o.value=s.id;$('source').append(o)}if(!sources.some(s=>s.id===source)){source='sd';path=''}$('source').value=source}
$('source').onchange=()=>{source=$('source').value;navigate('')};$('up').onclick=()=>navigate(path.split('/').slice(0,-1).join('/'));$('refresh').onclick=async()=>{try{await refreshSources();await load();await system()}catch(error){message(error.message,true)}};
$('new-folder').onclick=()=>{$('folder-error').textContent='';$('folder-name').value='';$('folder-dialog').showModal();$('folder-name').focus()};
$('folder-cancel').onclick=()=>$('folder-dialog').close();
$('folder-form').onsubmit=async e=>{if(e.submitter?.value!=='create')return;e.preventDefault();$('folder-create').disabled=true;try{await api('/api/folder?'+query({name:$('folder-name').value.trim()}),{method:'POST',headers:{'X-Machinista-Token':token}});$('folder-dialog').close();await load()}catch(error){$('folder-error').textContent=error.message}finally{$('folder-create').disabled=false}};
function transfer(file,row,progress){return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload?'+query({name:file.name}));xhr.setRequestHeader('X-Machinista-Token',token);xhr.setRequestHeader('Content-Type','audio/wav');xhr.timeout=30*60*1000;xhr.upload.onprogress=e=>{if(e.lengthComputable)progress.value=Math.round(e.loaded/e.total*100)};xhr.onload=()=>{let response;try{response=JSON.parse(xhr.responseText)}catch{response={error:'Connection interrupted.'}}if(xhr.status>=200&&xhr.status<300)resolve(response);else reject(new Error(response.error||'Upload failed.'))};xhr.onerror=()=>reject(new Error('Network error.'));xhr.ontimeout=()=>reject(new Error('Request timed out.'));xhr.send(file)})}
async function upload(files){if(uploading||fileBusy||$('files').disabled)return;uploading=true;$('source').disabled=true;$('refresh').disabled=true;writable(false);breadcrumbs();$('up').disabled=true;rootFolders(true);$('uploads').replaceChildren();message('Uploading …');let okay=0,failed=0;
 try{for(const file of files){const row=element('div',undefined,'upload-row'),label=element('span',file.name+' · '+bytes(file.size)),progress=element('progress');progress.max=100;progress.value=0;row.append(label,progress);$('uploads').append(row);try{if(!/\.(wav|mp3)$/i.test(file.name))throw new Error('WAV or MP3 files only.');if(file.size>1024**3)throw new Error('Maximum 1 GiB per sample.');const result=await transfer(file,row,progress);progress.value=100;label.textContent=(result.saved_name||file.name)+' · saved'+(result.converted?' · converted to '+result.converted+(result.gain_db<-.01?' · level '+result.gain_db.toFixed(1)+' dB to prevent clipping':''):'');okay++;setTimeout(()=>row.remove(),5000)}catch(error){label.textContent=file.name+' · '+error.message;row.style.color='var(--danger)';failed++}}message(okay+' sample'+(okay===1?'':'s')+' uploaded'+(failed?' · '+failed+' failed':''),failed>0,failed===0)}finally{uploading=false;$('source').disabled=false;$('refresh').disabled=false;$('files').value='';await load();system()}}
function rootFolders(disabled){for(const b of document.querySelectorAll('.folder'))b.disabled=disabled}
$('files').onchange=()=>upload(Array.from($('files').files));
for(const type of ['dragenter','dragover'])$('dropzone').addEventListener(type,e=>{e.preventDefault();if(!$('files').disabled)$('dropzone').classList.add('drag')});
for(const type of ['dragleave','drop'])$('dropzone').addEventListener(type,e=>{e.preventDefault();$('dropzone').classList.remove('drag');if(type==='drop')upload(Array.from(e.dataTransfer.files))});
let systemBusy=false;
function meter(label,percent,detail=''){const box=element('div',undefined,'meter'),head=element('div',undefined,'meter-head');head.append(element('span',label),element('span',percent==null?'—':percent.toFixed(0)+' %'));const track=element('div',undefined,'track'),fill=element('div',undefined,'fill');track.setAttribute('role','progressbar');track.setAttribute('aria-label',label);track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');if(percent!=null)track.setAttribute('aria-valuenow',String(Math.round(percent)));fill.style.width=Math.max(0,Math.min(100,percent||0))+'%';track.append(fill);box.append(head,track);if(detail)box.append(element('small',detail));return box}
async function system(){if(systemBusy||document.hidden)return;systemBusy=true;try{const s=await api('/api/system');$('host').textContent=s.hostname+(s.hardware_profile?.id!=='standard'&&s.hardware_profile?.name?' · '+s.hardware_profile.name:'');$('resources').replaceChildren(meter('CPU / All cores',s.cpu));const cores=element('div',undefined,'cpu-cores');for(const c of s.cpu_cores||[])cores.append(meter('Core '+(c.id+1),c.percent));if(cores.children.length)$('resources').append(cores);$('resources').append(meter('RAM',s.ram?.percent,s.ram?bytes(s.ram.used)+' / '+bytes(s.ram.total):''));for(const disk of s.storage)$('resources').append(meter(disk.name,disk.percent,bytes(disk.used)+' / '+bytes(disk.total)));$('temperature').textContent=s.temperature==null?'—':s.temperature.toFixed(1)+' °C';const m=Math.floor((s.uptime||0)/60);$('uptime').textContent=Math.floor(m/1440)+' d '+Math.floor(m%1440/60)+' h '+m%60+' min'}catch{$('host').textContent='System information unavailable'}finally{systemBusy=false}}
(async()=>{try{const session=await api('/api/session');token=session.token;hardwareProfile=session.hardware_profile||hardwareProfile;for(const id of ['tab-lv2','tab-banks','sound-banks'])if(!hardwareProfile.lv2)$(id).hidden=true;for(const id of ['tab-synth','tab-oscillators'])if(!hardwareProfile.synth)$(id).hidden=true;for(const o of document.querySelectorAll('#auto-source option[value=LV2],#sound-type-filter option[value=LV2],#sound-type-filter option[value=SYNTH]'))if(!hardwareProfile.lv2)o.remove();if(!hardwareProfile.lv2)$('auto-source').value='EXTERNAL';if(!hardwareProfile.lv2){document.querySelector('header .badge').textContent='LIBRARY / SOUNDS / PROJECTS / SYSTEM';document.querySelector('#sounds-panel > p.muted').textContent='Sampler instruments with keyboard zones and internal effects.';$('sound-capture').textContent='Save current Sound';document.querySelector('#autosampler-form > p.muted').textContent='Connect MIDI OUT to the external instrument and its audio outputs to your interface. Stop transport and recording before starting.';}await refreshSources();await load();await system()}catch(error){message(error.message,true);$('connection').textContent='Unreachable';writable(false)}})();setInterval(system,5000);

let networkBusy=false;
async function networkStatus(){if(networkBusy||document.hidden)return;try{const s=await api('/api/network');$('wifi-status').textContent=(s.mode==='hotspot'?'Hotspot':s.mode==='wifi'?'Wi-Fi':'Offline')+(s.ssid?' · '+s.ssid:'')+(s.address?' · '+s.address:'');if(s.message)$('wifi-message').textContent=s.message;}catch{$('wifi-status').textContent='Wi-Fi status unavailable';}}
$('wifi-scan').onclick=async()=>{if(networkBusy)return;networkBusy=true;$('wifi-scan').disabled=true;$('wifi-message').textContent='Scanning for Wi-Fi …';try{const s=await api('/api/network/scan');$('wifi-ssid').replaceChildren(element('option','Select Wi-Fi network'));$('wifi-ssid').firstChild.value='';for(const n of s.networks){const o=element('option',n.ssid+' · '+n.signal+' %'+(n.security?' · '+n.security:' · open'));o.value=n.ssid;$('wifi-ssid').append(o)}$('wifi-message').textContent=s.networks.length?'':'No Wi-Fi networks found. Please scan again.';}catch(e){$('wifi-message').textContent=e.message;}finally{networkBusy=false;$('wifi-scan').disabled=false;}};
$('wifi-form').onsubmit=async e=>{e.preventDefault();if(networkBusy||uploading){$('wifi-message').textContent='Please wait for the current operation to finish.';return}networkBusy=true;$('wifi-connect').disabled=true;try{await api('/api/network/connect',{method:'POST',headers:{'Content-Type':'application/json','X-Machinista-Token':token},body:JSON.stringify({ssid:$('wifi-ssid').value,password:$('wifi-password').value})});$('wifi-password').value='';$('wifi-message').textContent='Connecting. Join your home Wi-Fi on this device and open machinista.local:8080. If the connection fails, the Machinista hotspot will return automatically.';}catch(e){$('wifi-message').textContent=e.message;}finally{networkBusy=false;$('wifi-connect').disabled=false;}};
networkStatus();setInterval(networkStatus,5000);


let lv2Visible=false,lv2Uploading=false,lv2Busy=false,lv2Data=null,lv2Job=null,lv2JobState=null,lv2MessageTimer=null;
const lv2Expanded=new Set();
function lv2Message(text,error=false,temporary=false){clearTimeout(lv2MessageTimer);$('lv2-message').textContent=text;$('lv2-message').className=error?'error':'';if(temporary)lv2MessageTimer=setTimeout(()=>{$('lv2-message').textContent=''},5000)}
function workspace(name){if(name!=='sets'&&typeof setStop==='function')setStop();lv2Visible=name==='lv2';for(const key of ['samples','sets','projects','lv2','chords','sounds','oscillators','synth','banks']){$('tab-'+key).setAttribute('aria-pressed',String(key===name));$(key==='samples'?'sample-panel':key==='sets'?'sets-panel':key==='projects'?'project-panel':key==='chords'?'chords-panel':key==='sounds'?'sounds-panel':key==='oscillators'?'oscillator-panel':key==='synth'?'synth-panel':key==='banks'?'banks-panel':'lv2-panel').hidden=key!==name}if(name==='sets')sampleSetsLoad();if(lv2Visible){lv2Status()}if(name==='banks')pluginBanksLoad();synthVisible=name==='synth';if(synthVisible)synthLoad();if(name==='oscillators')oscillatorLoad();if(name==='projects')projectList();if(name==='chords')chordsList();soundVisible=name==='sounds';if(soundVisible)soundsLoad()}
$('tab-samples').onclick=()=>workspace('samples');$('tab-projects').onclick=()=>workspace('projects');$('tab-lv2').onclick=()=>workspace('lv2');
function lv2Render(){if(!lv2Data)return;const q=$('lv2-search').value.toLowerCase();$('lv2-bundles').replaceChildren();
 const rows=lv2Data.bundles.filter(b=>(b.name+' '+b.plugins.map(p=>p.name+' '+p.uri).join(' ')).toLowerCase().includes(q));
 for(const b of rows){const card=element('article',undefined,'lv2-bundle'),head=element('div',undefined,'lv2-bundle-head'),info=element('div'),state=element('span',b.status,'lv2-status '+(b.status==='OK'?'ok':'bad'));info.append(element('h3',b.name),element('p',(b.architecture||'Unknown architecture')+' · '+(b.managed?'Uploaded':'Existing')+' · '+b.plugins.length+' plugin'+(b.plugins.length===1?'':'s'),'muted small'));head.append(info,state);card.append(head);
 if(b.reason)card.append(element('p',b.reason,'error small'));
 const details=element('details'),summary=element('summary','Show plugins');details.open=lv2Expanded.has(b.id);details.ontoggle=()=>{if(details.open)lv2Expanded.add(b.id);else lv2Expanded.delete(b.id)};details.append(summary);for(const p of b.plugins){const line=element('div',undefined,'lv2-plugin');line.append(element('strong',p.name),element('span',p.kind==='INSTRUMENT'?'Instrument':'Effect','muted small'),element('code',p.uri));details.append(line)}card.append(details);
 const bottom=element('div',undefined,'lv2-bundle-footer'),remove=element('button','Remove bundle');remove.type='button';remove.disabled=lv2Uploading||lv2Data.busy||!b.canDelete;remove.onclick=async()=>{if(!confirm('Remove '+b.name+' and all '+b.plugins.length+' plugins inside it? Saved projects keep their references; a recovery copy will be retained.'))return;try{const result=await api('/api/lv2/delete?'+new URLSearchParams({id:b.id}),{method:'POST',headers:{'X-Machinista-Token':token}});lv2Job=result.job;lv2JobState=null;lv2Message('Removing bundle…');await lv2Status()}catch(e){lv2Message(e.message,true)}};
 bottom.append(element('span',b.inUse?'In use by current project':b.status!=='OK'?'Not supported by this host':!lv2Data.applicationAvailable?'Waiting for application status':lv2Data.transportBusy?'Stop playback and recording to remove':lv2Data.browserReady?'Available in the plug-in browser':'Plug-in browser refresh pending','muted small'),remove);card.append(bottom);$('lv2-bundles').append(card)}
 if(!rows.length)$('lv2-bundles').append(element('p',q?'No matching plugins.':'No plugin bundles installed.','muted'));
}
async function lv2Status(){if(lv2Busy||!lv2Visible||document.hidden)return;lv2Busy=true;try{const next=await api('/api/lv2');const changed=JSON.stringify(next)!==JSON.stringify(lv2Data);lv2Data=next;document.dispatchEvent(new CustomEvent('lv2-status',{detail:next}));if(!changed)return;$('lv2-target').textContent='This device: '+lv2Data.target;$('lv2-file').disabled=lv2Uploading||lv2Data.busy;$('lv2-refresh').disabled=lv2Uploading||lv2Data.busy;if(lv2Job){const job=lv2Data.jobs.find(j=>j.id===lv2Job);if(job&&job.state!==lv2JobState){lv2JobState=job.state;const done=['ACTIVE','REMOVED','DONE','NOT OK'].includes(job.state);lv2Message(job.message,job.ok===false,done);if(done)lv2Job=null}}if(lv2Data.error)lv2Message(lv2Data.error,true);lv2Render()}catch(e){lv2Message('LV2 manager unavailable: '+e.message,true)}finally{lv2Busy=false}}
$('lv2-search').oninput=lv2Render;
$('lv2-refresh').onclick=async()=>{try{const result=await api('/api/lv2/refresh',{method:'POST',headers:{'X-Machinista-Token':token}});lv2Job=result.job;lv2JobState=null;lv2Message('Scanning installed plugins…');await lv2Status()}catch(e){lv2Message(e.message,true)}};
$('lv2-file').onchange=async()=>{const file=$('lv2-file').files[0];if(!file||lv2Uploading)return;lv2Uploading=true;$('lv2-file').disabled=true;$('lv2-progress').hidden=false;$('lv2-progress').value=0;lv2Message('Uploading '+file.name+'…');try{if(file.size>128*1024**2)throw new Error('Maximum 128 MiB per plugin archive.');const result=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/lv2/upload?'+new URLSearchParams({name:file.name}));xhr.setRequestHeader('X-Machinista-Token',token);xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.timeout=10*60*1000;xhr.upload.onprogress=e=>{if(e.lengthComputable)$('lv2-progress').value=Math.round(e.loaded/e.total*100)};xhr.onload=()=>{let value;try{value=JSON.parse(xhr.responseText)}catch{value={error:'Upload interrupted.'}}if(xhr.status>=200&&xhr.status<300)resolve(value);else reject(new Error(value.error||'Upload failed.'))};xhr.onerror=()=>reject(new Error('Network error.'));xhr.ontimeout=()=>reject(new Error('Upload timed out.'));xhr.send(file)});lv2Job=result.job;lv2JobState=null;lv2Message('Upload complete. Checking package…')}catch(e){lv2Message(e.message,true)}finally{lv2Uploading=false;$('lv2-file').value='';$('lv2-progress').hidden=true;await lv2Status()}};
setInterval(lv2Status,2000);

let projectBusy=false;
function projectMessage(text,error=false){$('project-message').textContent=text;$('project-message').className=error?'error':''}
async function projectDelete(row,button){
 if(!confirm('Are you sure you want to delete project "'+row.name+'"? If it is loaded, the controller will open an empty project. A recovery copy is kept; samples are not deleted.'))return;
 button.disabled=true;
 try{const result=await api('/api/projects/delete',{method:'POST',headers:{'X-Machinista-Token':token,'Content-Type':'application/json'},body:JSON.stringify({id:row.id,name:row.name,version:row.version,confirmed:true})});projectMessage(result.message);await projectList();system()}
 catch(e){projectMessage(e.message,true);button.disabled=false}
}
async function projectList(){try{const rows=await api('/api/projects');$('project-entries').replaceChildren();for(const row of rows){const tr=element('tr'),name=element('td'),saved=element('td',new Date(row.modified*1000).toLocaleString()),actions=element('td');name.append(element('strong',row.name),element('p',row.current?'Current · last saved copy':row.id,'muted small'));const links=element('div',undefined,'actions');for(const [format,label] of [['zip','Project ZIP'],['json','JSON only']]){const link=element('a',label);link.href='/api/projects/file?'+new URLSearchParams({id:row.id,format});link.download=row.name+'.'+format;links.append(link)}const remove=element('button','Delete');remove.type='button';remove.disabled=projectBusy;remove.onclick=()=>projectDelete(row,remove);links.append(remove);actions.append(links);tr.append(name,saved,actions);$('project-entries').append(tr)}if(!rows.length){const tr=element('tr'),td=element('td','No saved projects.');td.colSpan=3;tr.append(td);$('project-entries').append(tr)}$('project-count').textContent=rows.length+' saved project'+(rows.length===1?'':'s')}catch(e){projectMessage(e.message,true)}}
$('project-refresh').onclick=()=>{projectMessage('');projectList()};
$('project-file').onchange=async()=>{const file=$('project-file').files[0];if(!file||projectBusy)return;projectBusy=true;$('project-file').disabled=true;$('project-refresh').disabled=true;$('project-progress').hidden=false;$('project-progress').value=0;projectMessage('Uploading '+file.name+'…');try{const json=/\.json$/i.test(file.name);if(!/\.(zip|json)$/i.test(file.name))throw new Error('Choose a project ZIP or JSON.');if(file.size>(json?8*1024**2:1024**3))throw new Error(json?'Maximum 8 MiB for JSON.':'Maximum 1 GiB for project ZIP.');const result=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','/api/projects/upload?'+new URLSearchParams({name:file.name}));xhr.setRequestHeader('X-Machinista-Token',token);xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.timeout=30*60*1000;xhr.upload.onprogress=e=>{if(e.lengthComputable)$('project-progress').value=Math.round(e.loaded/e.total*100)};xhr.onload=()=>{let value;try{value=JSON.parse(xhr.responseText)}catch{value={error:'Upload interrupted.'}}if(xhr.status>=200&&xhr.status<300)resolve(value);else reject(new Error(value.error||'Project upload failed.'))};xhr.onerror=()=>reject(new Error('Network error.'));xhr.ontimeout=()=>reject(new Error('Upload timed out.'));xhr.send(file)});projectMessage(result.name+' · '+result.message);await projectList();system()}catch(e){projectMessage(e.message,true)}finally{projectBusy=false;$('project-file').disabled=false;$('project-refresh').disabled=false;$('project-file').value='';$('project-progress').hidden=true}};

let powerAction=null,powerPending=false;
function choosePower(action){
 if(uploading||projectBusy||lv2Uploading||fileBusy||chordBusy){$('power-message').textContent='Wait for the upload to finish first.';return}
 powerAction=action;const restart=action==='reboot';
 $('power-dialog-title').textContent=restart?'Restart Machinista?':'Shut down Machinista?';
 $('power-dialog-description').textContent='The current project and plug-in states will be saved. Playback will stop.';
 $('power-confirm').textContent=restart?'Save & restart':'Save & shut down';
 $('power-dialog').showModal();$('power-cancel').focus();
}
$('power-reboot').onclick=()=>choosePower('reboot');
$('power-shutdown').onclick=()=>choosePower('shutdown');
$('power-cancel').onclick=()=>{$('power-dialog').close();powerAction=null};
$('power-confirm').onclick=async()=>{
 const action=powerAction;if(!action||powerPending)return;powerPending=true;
 $('power-confirm').disabled=true;$('power-message').textContent='Saving and stopping…';
 try{
  await api('/api/power?'+new URLSearchParams({action}),{method:'POST',headers:{'X-Machinista-Token':token}});
  $('power-dialog').close();$('power-reboot').disabled=$('power-shutdown').disabled=true;
  $('power-message').textContent=action==='reboot'?'Restarting… Reopen this page once Machinista is online.':'Shutting down… Wait until the Pi has fully stopped before disconnecting power.';
  $('connection').textContent=action==='reboot'?'Restarting':'Shutting down';
 }catch(e){$('power-dialog').close();$('power-message').textContent=e.message;powerPending=false}
 finally{$('power-confirm').disabled=false;powerAction=null}
};

let sshBusy=false;
function showSSH(s){$('ssh-toggle').checked=Boolean(s.active);$('ssh-status').textContent=s.active?'SSH is on · Port 22':s.enabled?'SSH is enabled but not running':'SSH is off';$('ssh-login').textContent=s.user?'Login: '+s.user+'@'+location.hostname:'';}
async function sshStatus(){if(sshBusy||document.hidden)return;sshBusy=true;try{showSSH(await api('/api/ssh'));$('ssh-toggle').disabled=false}catch{$('ssh-status').textContent='SSH status unavailable';$('ssh-toggle').disabled=true}finally{sshBusy=false}}
$('ssh-toggle').onchange=async()=>{if(sshBusy)return;sshBusy=true;const enable=$('ssh-toggle').checked;$('ssh-toggle').disabled=true;$('ssh-status').textContent=enable?'Starting SSH…':'Stopping SSH…';try{showSSH(await api('/api/ssh?'+new URLSearchParams({action:enable?'enable':'disable'}),{method:'POST',headers:{'X-Machinista-Token':token}}))}catch(e){$('ssh-status').textContent=e.message;$('ssh-toggle').checked=!enable}finally{sshBusy=false;$('ssh-toggle').disabled=false}};
sshStatus();setInterval(sshStatus,5000);

let fileChoice=null,moveSource='sd',movePath='',destinationVersion=0;
function filePost(action,params){return api('/api/files/'+action+'?'+new URLSearchParams(params),{method:'POST',headers:{'X-Machinista-Token':token}})}
async function chooseFile(action,item){
 if(fileBusy||uploading||!libraryWritable)return;
 fileChoice={action,name:item.name,source,path,folder:item.folder};
 $('file-title').textContent=action==='move'?'Move '+(item.folder?'folder':'sample'):'Delete '+(item.folder?'folder':'sample')+'?';
 $('file-name').textContent=item.name;$('file-error').textContent='';$('move-controls').hidden=action!=='move';
 $('file-description').textContent=action==='delete'?'This item'+(item.folder?' and all its contents':'')+' will be deleted permanently.':'Project references to the old location are not changed.';
 $('file-confirm').textContent=action==='move'?'Move here':'Delete permanently';$('file-confirm').disabled=false;
 $('file-dialog').showModal();$('file-cancel').focus();
 if(action==='move'){
  moveSource=source;movePath=path;$('move-source').replaceChildren();
  for(const row of sources.filter(s=>!s.readOnly)){const o=element('option',row.name);o.value=row.id;$('move-source').append(o)}
  $('move-source').value=moveSource;await loadDestination();
 }
}
async function loadDestination(){
 const version=++destinationVersion;$('file-confirm').disabled=true;$('move-folders').replaceChildren();$('file-error').textContent='';
 const parts=movePath?movePath.split('/'):[];const nav=$('move-path');nav.replaceChildren();
 [sources.find(s=>s.id===moveSource)?.name||'Storage',...parts].forEach((name,i)=>{if(i)nav.append(element('span',' / '));const b=element('button',name);b.type='button';b.onclick=()=>{if(fileBusy)return;movePath=parts.slice(0,i).join('/');loadDestination()};nav.append(b)});
 $('move-up').disabled=!movePath;
 try{
  const data=await api('/api/list?'+new URLSearchParams({source:moveSource,path:movePath}));if(version!==destinationVersion)return;
  for(const row of data.entries.filter(r=>r.folder)){
   const b=element('button','▸ '+row.name,'folder');b.type='button';
   const child=movePath?movePath+'/'+row.name:row.name;
   b.disabled=fileChoice?.folder&&moveSource===fileChoice.source&&(child===[fileChoice.path,fileChoice.name].filter(Boolean).join('/'));
   b.onclick=()=>{if(fileBusy)return;movePath=child;loadDestination()};$('move-folders').append(b);
  }
  if(!$('move-folders').children.length)$('move-folders').append(element('p','No subfolders.','muted small'));
  $('file-confirm').disabled=!data.writable||(fileChoice?.source===moveSource&&fileChoice.path===movePath);
 }catch(e){if(version===destinationVersion)$('file-error').textContent=e.message}
}
$('move-source').onchange=()=>{if(fileBusy)return;moveSource=$('move-source').value;movePath='';loadDestination()};
$('move-up').onclick=()=>{if(fileBusy)return;movePath=movePath.split('/').slice(0,-1).join('/');loadDestination()};
$('file-cancel').onclick=()=>{if(!fileBusy){$('file-dialog').close();fileChoice=null;destinationVersion++}};
$('file-dialog').addEventListener('cancel',e=>{if(fileBusy)e.preventDefault()});
$('file-confirm').onclick=async()=>{
 if(!fileChoice||fileBusy||uploading)return;fileBusy=true;const choice={...fileChoice};$('file-confirm').disabled=true;$('file-cancel').disabled=true;$('move-source').disabled=true;
 $('file-error').textContent=choice.action==='move'?'Moving… Keep the storage connected until this finishes.':'Deleting…';
 try{
  const result=await filePost(choice.action,{source:choice.source,path:choice.path,name:choice.name,target_source:moveSource,target_path:movePath,confirmed:true});
  $('preview').pause();$('preview').removeAttribute('src');$('preview-name').textContent='No sample selected';
  $('file-dialog').close();fileChoice=null;message(result.message);await load();system();
 }catch(e){$('file-error').textContent=e.message}
 finally{fileBusy=false;$('file-confirm').disabled=false;$('file-cancel').disabled=false;$('move-source').disabled=false;await load()}
};

let chordRows=[],chordEditId=null,chordBusy=false;
$('tab-chords').onclick=()=>workspace('chords');
function chordsMessage(text,error=false){$('chords-message').textContent=text;$('chords-message').className=error?'error':''}
async function chordsList(){try{chordRows=await api('/api/chords');$('chords-list').replaceChildren();for(const row of chordRows){const card=element('article',undefined,'lv2-bundle'),bar=element('div',undefined,'actions');card.append(element('h3',row.preset.name),element('p',row.preset.chords.length+' chords','muted'));const edit=element('button','Edit'),download=element('button','Download'),remove=element('button','Delete');edit.onclick=()=>chordsEdit(row);download.onclick=()=>{const a=element('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(row.preset,null,2)],{type:'application/json'}));a.download=row.preset.name+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};remove.onclick=async()=>{if(!confirm('Delete '+row.preset.name+' from the chord library? Saved projects keep their chord copy.'))return;try{await api('/api/chords/delete?'+new URLSearchParams({id:row.id}),{method:'POST',headers:{'X-Machinista-Token':token}});await chordsList()}catch(e){chordsMessage(e.message,true)}};bar.append(edit,download,remove);card.append(bar);$('chords-list').append(card)}if(!chordRows.length)$('chords-list').append(element('p','No chord presets yet. Import a preset or create your own.','muted'))}catch(e){chordsMessage(e.message,true)}}
function chordRow(row){const tr=element('tr');for(const [key,value] of [['input',row.input],['name',row.name],['notes',row.notes.join(', ')]]){const td=element('td'),input=element('input');input.dataset.key=key;input.value=value;input.required=key!=='name';if(key==='input'){input.type='number';input.min='0';input.max='127'}input.setAttribute('aria-label',key==='input'?'Input MIDI key':key==='name'?'Chord name':'Chord MIDI notes');td.append(input);tr.append(td)}const td=element('td'),b=element('button','Remove');b.type='button';b.onclick=()=>tr.remove();td.append(b);tr.append(td);$('chords-rows').append(tr)}
function chordsEdit(row){chordEditId=row?.id||null;$('chords-editor').hidden=false;$('chords-name').value=row?.preset.name||'';$('chords-root').value=row?.preset.root??60;$('chords-rows').replaceChildren();$('chords-error').textContent='';for(const chord of row?.preset.chords||[{input:60,name:'',notes:[60,64,67]}])chordRow(chord);$('chords-name').focus()}
$('chords-new').onclick=()=>chordsEdit(null);$('chords-refresh').onclick=chordsList;$('chords-cancel').onclick=()=>{$('chords-editor').hidden=true};$('chords-add').onclick=()=>{const used=new Set([...$('chords-rows').querySelectorAll('[data-key="input"]')].map(n=>Number(n.value)));let input=60;while(used.has(input)&&input<127)input++;chordRow({input,name:'',notes:[60,64,67]})};
$('chords-editor').onsubmit=async event=>{event.preventDefault();if(chordBusy)return;chordBusy=true;try{const chords=[...$('chords-rows').children].map(row=>{const get=key=>row.querySelector('[data-key="'+key+'"]').value;const text=get('notes').trim();if(!/^\d+(?:[ ,;]+\d+)*$/.test(text))throw new Error('Use MIDI note numbers separated by commas or spaces.');return {input:Number(get('input')),name:get('name'),notes:text.split(/[ ,;]+/).map(Number)}});await api('/api/chords/save?'+new URLSearchParams(chordEditId?{id:chordEditId}:{}),{method:'POST',headers:{'X-Machinista-Token':token,'Content-Type':'application/json'},body:JSON.stringify({name:$('chords-name').value,root:Number($('chords-root').value),chords})});$('chords-editor').hidden=true;chordsMessage('Preset saved. Select it on the controller to load this version.');await chordsList()}catch(e){$('chords-error').textContent=e.message}finally{chordBusy=false}};
$('chords-file').onchange=async()=>{if(chordBusy)return;chordBusy=true;$('chords-file').disabled=true;try{let count=0;for(const file of $('chords-file').files){if(file.size>1024**2)throw new Error('Maximum 1 MiB per chord preset.');await api('/api/chords/upload?'+new URLSearchParams({name:file.name}),{method:'POST',headers:{'X-Machinista-Token':token},body:file});count++}chordsMessage(count+' preset(s) imported. Choose CUSTOM in Keyboard mode, then select a preset.');await chordsList()}catch(e){chordsMessage(e.message,true)}finally{chordBusy=false;$('chords-file').disabled=false;$('chords-file').value=''}};

let pluginBankTimer,pluginBankData=[];
function pluginBankMessage(text,error=false){clearTimeout(pluginBankTimer);const node=$('plugin-bank-message');node.textContent=text;node.classList.toggle('error',error);if(text)pluginBankTimer=setTimeout(()=>node.textContent='',5000)}
function pluginBanksRender(){
 const selected=pluginBankData.find(p=>p.id===$('plugin-bank-profile').value),list=$('plugin-bank-list');list.replaceChildren();
 if(!selected){list.append(element('p','No preset-bank profiles available.','muted'));return}
 for(const bank of selected.banks){
  const row=element('div',undefined,'lv2-bundle-footer');row.append(element('span',selected.name+' · '+bank.name+' · '+bank.patches+' patches'));
  if(bank.canDelete){const remove=element('button','Remove bank');remove.type='button';remove.onclick=async()=>{
   if(!confirm('Remove '+bank.name+' from the bank list? Saved project patches will remain playable.'))return;
   try{await api('/api/plugin-banks/delete?'+new URLSearchParams({profile:selected.id,id:bank.id}),{method:'POST',headers:{'X-Machinista-Token':token}});pluginBankMessage('Bank and its Sounds entries removed.');await pluginBanksLoad();if(soundVisible)await soundsLoad()}catch(e){pluginBankMessage(e.message,true)}
  };row.append(remove)}list.append(row)
 }
 if(!selected.banks.length)list.append(element('p','No preset banks for '+selected.name+'.','muted'));
}
async function pluginBanksLoad(){
 try{
  const data=await api('/api/plugin-banks'),selector=$('plugin-bank-profile'),selected=selector.value;pluginBankData=data;
  selector.replaceChildren(...data.map(p=>new Option(p.name,p.id)));
  if(data.some(p=>p.id===selected))selector.value=selected;
  pluginBanksRender();
 }catch(e){pluginBankMessage(e.message,true)}
}
$('plugin-bank-profile').onchange=pluginBanksRender;
$('plugin-bank-file').onchange=async()=>{const input=$('plugin-bank-file'),file=input.files[0];if(!file)return;input.disabled=true;try{if(file.size>8*1024**2)throw new Error('Maximum 8 MiB per preset bank.');const result=await api('/api/plugin-banks/upload?'+new URLSearchParams({profile:$('plugin-bank-profile').value,name:file.name}),{method:'POST',headers:{'X-Machinista-Token':token,'Content-Type':'application/octet-stream'},body:file});pluginBankMessage(result.name+' · '+result.patches+' patches imported.');await pluginBanksLoad()}catch(e){pluginBankMessage(e.message,true)}finally{input.disabled=false;input.value=''}};

$('tab-oscillators').onclick=()=>workspace('oscillators');

$('tab-banks').onclick=()=>workspace('banks');
$('sound-banks').onclick=()=>workspace('banks');

$('lv2-banks').onclick=()=>workspace('banks');
