/* Local visual editor: no CDN, external editor account or runtime dependency. */
(()=>{
  const get=id=>document.getElementById(id);
  const editor=get('email-template-body'),subject=get('email-template-subject');
  let version=null,dirty=false,busy=false,defaults=null,range=null,lastFocus='body',revision=0;
  const status=text=>get('email-template-status').textContent=text;
  function mark(){revision++;dirty=true;status('Unsaved template changes.');}
  function remember(){
    const selection=window.getSelection();
    if(selection?.rangeCount&&editor.contains(selection.anchorNode)&&editor.contains(selection.focusNode))range=selection.getRangeAt(0).cloneRange();
  }
  document.addEventListener('selectionchange',remember);
  editor.addEventListener('focus',()=>{lastFocus='body'});
  subject.addEventListener('focus',()=>{lastFocus='subject'});
  editor.addEventListener('input',mark);subject.addEventListener('input',mark);
  function restore(){
    editor.focus();const selection=window.getSelection();
    if(!range||!editor.contains(range.commonAncestorContainer)){range=document.createRange();range.selectNodeContents(editor);range.collapse(false);}
    selection.removeAllRanges();selection.addRange(range);
  }
  function command(name,value=null){
    restore();document.execCommand('styleWithCSS',false,true);document.execCommand(name,false,value);remember();mark();
  }
  async function request(path,body){
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Template request failed.');return result;
  }
  async function work(action){
    if(busy)return;busy=true;
    get('email-template-save').disabled=get('email-template-preview').disabled=true;
    try{await action()}catch(error){status(error.message)}
    finally{busy=false;get('email-template-save').disabled=get('email-template-preview').disabled=false;}
  }
  function apply(template){
    subject.value=template.subject;editor.innerHTML=template.html;version=template.version;range=null;dirty=false;
    get('email-preview-panel').hidden=true;get('email-preview-frame').removeAttribute('srcdoc');status('Saved template loaded.');
  }
  function populateFields(fields){
    const menu=get('email-field');menu.replaceChildren(new Option('Choose a field',''));
    for(const [key,label] of Object.entries(fields))menu.append(new Option(label+' · {{'+key+'}}',key));
  }
  window.InvoiceEmailEditor={load(state){
    defaults=state.email_template_defaults;populateFields(state.email_fields||{});
    if(!dirty&&state.email_template)apply(state.email_template);
  }};
  document.querySelectorAll('[data-email-command]').forEach(button=>{
    button.addEventListener('mousedown',event=>event.preventDefault());
    button.addEventListener('click',()=>command(button.dataset.emailCommand));
  });
  get('email-block').addEventListener('change',event=>command('formatBlock',event.target.value));
  get('email-colour').addEventListener('input',event=>command('foreColor',event.target.value));
  get('email-field').addEventListener('change',event=>{
    if(!event.target.value)return;const value='{{'+event.target.value+'}}';
    if(lastFocus==='subject'){subject.focus();subject.setRangeText(value,subject.selectionStart??subject.value.length,subject.selectionEnd??subject.value.length,'end');mark();}
    else command('insertText',value);
    event.target.value='';
  });
  function url(value,image=false){
    try{
      const parsed=new URL(value);
      if(parsed.username||parsed.password||/\s/.test(value))throw Error();
      if(parsed.protocol==='https:'||(!image&&parsed.protocol==='http:'))return parsed.href;
      if(!image&&parsed.protocol==='mailto:'&&!parsed.search&&!parsed.hash)return parsed.href;
    }catch{}
    throw Error(image?'Use a complete HTTPS image URL.':'Use a complete HTTP(S) link or a mailto: email link.');
  }
  get('email-link').addEventListener('click',()=>{
    remember();const input=prompt('Link URL (https://example.com or mailto:hello@example.com)');if(input===null)return;
    try{
      const href=url(input.trim());const label=prompt('Link text',window.getSelection()?.toString()||'Visit website');if(label===null)return;
      const link=document.createElement('a');link.href=href;link.textContent=label;link.rel='noopener noreferrer';command('insertHTML',link.outerHTML);
    }catch(error){status(error.message)}
  });
  get('email-image').addEventListener('click',()=>{
    remember();const input=prompt('Public HTTPS image URL (the email client loads this image)');if(input===null)return;
    try{
      const src=url(input.trim(),true);const alt=prompt('Image description','Company logo');if(alt===null)return;
      const image=document.createElement('img');image.src=src;image.alt=alt.slice(0,300);image.width=200;command('insertHTML',image.outerHTML);
    }catch(error){status(error.message)}
  });
  editor.addEventListener('paste',event=>{
    event.preventDefault();remember();
    let html=event.clipboardData?.getData('text/html');
    if(!html){const div=document.createElement('div');div.textContent=event.clipboardData?.getData('text/plain')||'';html=div.innerHTML.replace(/\n/g,'<br>');}
    work(async()=>{const result=await request('/api/email-template/clean',{html});command('insertHTML',result.html);});
  });
  editor.addEventListener('drop',event=>{event.preventDefault();status('Use Image for a public image URL, or paste formatted text.');});
  get('email-template-form').addEventListener('submit',event=>{
    event.preventDefault();work(async()=>{
      const savedRevision=revision;const result=await request('/api/email-template',{subject:subject.value,html:editor.innerHTML,version});
      if(revision===savedRevision){apply(result);status('Email template saved. New queued invoices will use it.');}
      else{version=result.version;status('Template saved. Your newer edits are still unsaved.');}
    });
  });
  get('email-template-preview').addEventListener('click',()=>work(async()=>{
    const result=await request('/api/email-template/preview',{subject:subject.value,html:editor.innerHTML});
    get('email-preview-subject').textContent=result.subject;get('email-preview-frame').srcdoc=result.html;
    get('email-preview-plain').textContent=result.plain;get('email-preview-panel').hidden=false;status('Sample preview generated from your current draft. No email was sent.');
  }));
  get('email-template-reload').addEventListener('click',()=>{
    if(dirty&&!confirm('Discard unsaved email template changes and reload the saved template?'))return;
    work(async()=>{const response=await fetch('/api/state');if(!response.ok)throw Error('Could not load the saved template.');const state=await response.json();apply(state.email_template);});
  });
  get('email-template-reset').addEventListener('click',()=>{
    if(!defaults||!confirm('Replace this draft with the default email? Save afterwards to apply it.'))return;
    subject.value=defaults.subject;editor.innerHTML=defaults.html;range=null;mark();
  });
})();
