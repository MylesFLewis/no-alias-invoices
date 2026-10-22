"""Instrument only the disposable smoke container, never the published image."""
from pathlib import Path

# Synthetic accepted message in the disposable test database only; never send mail.
import json,time
import app
import mail_diagnostics
clock=time.time()
with app.connection() as c:
    c.execute("INSERT INTO invoices(number,token,body,settings,pdf,display_number,sequence_number,number_prefix) VALUES(999,'browser-diagnostics',?,? ,?,'DEMO0999',999,'DEMO')",
        (json.dumps({'customer':'Synthetic diagnostics','date':'2026-10-22','deposit':0,'lines':[{'fee':10000}]}),'{}',b'%PDF synthetic'))
    c.execute("INSERT INTO invoice_mail VALUES(999,'demo@example.com','sent',?,?,?,'<synthetic@example.com>')",(clock-20,clock,''))
    ref=mail_diagnostics.queued(c,999,clock-20)
    c.execute("UPDATE invoice_mail_attempts SET provider='microsoft_graph',state='sent',started_at=?,finished_at=?,protocol_code=202 WHERE ref=?",(clock-10,clock,ref))

harness = r'''
<script>
(async () => {
  const el = id => document.getElementById(id);
  const wait = async predicate => {
    for (let i=0;i<200;i++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw Error('Timed out waiting for editor');
  };
  const check = (value, message) => { if (!value) throw Error(message); };
  try {
    await wait(() => el('email-template-status').textContent.includes('Saved template loaded'));
    document.querySelector('[data-tab="create"]').click();
    const customer=document.getElementById('customer');customer.value='Numbering Test';customer.dispatchEvent(new Event('change'));
    const venue=document.querySelector('.service .venue');
    check(venue.options[0].textContent==='Add new venue details...', 'New venue option is not first');
    venue.value='__new__';venue.dispatchEvent(new Event('change'));
    const service=venue.closest('.service'), fields=service.querySelector('.new-venue-fields');
    check(!fields.hidden && service.querySelector('.new-venue-name').required, 'New venue fields missing');
    service.querySelector('.new-venue-name').value='Browser New Hall';service.querySelector('.new-venue-address').value='1 Browser Road';
    service.querySelector('.description').value='Synthetic service';service.querySelector('.fee').value='100';
    const draft=payload();
    check(draft.lines[0].new_venue.name==='Browser New Hall' && !('venue_id' in draft.lines[0]), 'Inline venue payload invalid');
    const preview=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});
    check(preview.ok,'Inline venue PDF preview failed');await preview.arrayBuffer();
    const before=await (await fetch('/api/state')).json();
    check(!before.contacts.some(c=>c.name==='Browser New Hall'),'Preview saved venue unexpectedly');
    const saved=await fetch('/api/invoices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});
    check(saved.ok,'Inline venue invoice save failed');await saved.json();await load();
    const after=await (await fetch('/api/state')).json();
    const created=after.contacts.find(c=>c.kind==='venue'&&c.name==='Browser New Hall');
    check(created && created.assigned_contact_id===after.contacts.find(c=>c.kind==='customer'&&c.name==='Numbering Test').id, 'New venue not assigned');
    check([...document.querySelector('.service .venue').options].some(o=>o.value===String(created.id)), 'Saved venue absent from dropdown');
    customer.value='';customer.dispatchEvent(new Event('change'));
    check(fields.hidden && service.querySelector('.new-venue-name').disabled, 'Contact change did not hide fields');
    document.querySelector('[data-tab="history"]').click();
    const mail = document.querySelector('[data-mail-invoice="999"]');
    check(mail.textContent.includes('Accepted by Microsoft — delivery not confirmed'), 'Acceptance label missing');
    check(mail.textContent.includes('phishing filters'), 'Delivery troubleshooting missing');
    mail.querySelector('summary').click();
    check(mail.querySelector('details').open, 'Email details did not expand');
    check(mail.textContent.includes('202') && mail.textContent.includes('Queued:') && mail.textContent.includes('Attempt '), 'Attempt timeline missing');
    check(!mail.querySelector('button'), 'Accepted message incorrectly offers retry');
    document.querySelector('[data-tab="settings"]').click();
    const body = el('email-template-body'), subject = el('email-template-subject');
    body.innerHTML = '<p>Browser check {{client_name}}</p>';
    body.dispatchEvent(new Event('input', {bubbles:true}));
    body.focus();
    const range = document.createRange(); range.selectNodeContents(body.firstChild);
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    document.dispatchEvent(new Event('selectionchange'));
    document.querySelector('[data-email-command="bold"]').click();
    check(/font-weight|<b>|<strong>/.test(body.innerHTML), 'Bold command did not format text');
    subject.value = 'Browser invoice '; subject.focus(); subject.setSelectionRange(subject.value.length,subject.value.length);
    el('email-field').value = 'invoice_number'; el('email-field').dispatchEvent(new Event('change'));
    check(subject.value.includes('{{invoice_number}}'), 'Subject field insertion failed');
    el('email-template-save').click();
    await wait(() => el('email-template-status').textContent.includes('Email template saved.'));
    const state = await (await fetch('/api/state')).json();
    check(state.email_template.subject === subject.value, 'Subject was not persisted');
    check(/font-weight|<b>|<strong>/.test(state.email_template.html), 'Formatting was not persisted');
    el('email-template-preview').click();
    await wait(() => !el('email-preview-panel').hidden);
    check(el('email-preview-subject').textContent.includes('DEMO0169'), 'Preview did not replace invoice field');
    check(el('email-preview-frame').srcdoc.includes('Alex Example'), 'Preview did not replace client field');
    check(el('email-preview-frame').getAttribute('sandbox') === '', 'Preview sandbox missing');
    await wait(() => !el('email-template-save').disabled);
    body.focus();
    const end = document.createRange(); end.selectNodeContents(body); end.collapse(false);
    selection.removeAllRanges(); selection.addRange(end); document.dispatchEvent(new Event('selectionchange'));
    const clipboard = new DataTransfer();
    clipboard.setData('text/html','<p>Safe pasted text</p><img src="javascript:alert(1)" onerror="window.unsafePaste=true"><scr'+'ipt>window.unsafePaste=true</scr'+'ipt>');
    body.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));
    await wait(() => body.textContent.includes('Safe pasted text'));
    check(!body.querySelector('script,[onerror]') && !body.innerHTML.includes('javascript:'), 'Unsafe paste survived');
    check(!window.unsafePaste, 'Unsafe paste executed');
    document.body.dataset.editorTest = 'passed';
  } catch(error) {
    document.body.dataset.editorTest = 'failed';
    const failure = document.createElement('pre'); failure.id='editor-test-error'; failure.textContent=error.stack;
    document.body.append(failure);
  }
})();
</script>
'''
path = Path('/app/static/index.html')
path.write_text(path.read_text().replace('</body>', harness + '</body>'))
