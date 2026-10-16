"""Instrument only the disposable smoke container, never the published image."""
from pathlib import Path

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
