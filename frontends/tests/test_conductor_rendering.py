"""Offline browser regression tests; install Playwright + Chromium to run."""
from pathlib import Path
import re

import pytest

playwright = pytest.importorskip("playwright.sync_api")
HTML = Path(__file__).resolve().parents[1] / "conductor.html"


@pytest.fixture
def page():
    with playwright.sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is not installed")
        browser = pw.chromium.launch(headless=True)
        tab = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        tab.on("pageerror", lambda error: errors.append(str(error)))
        tab.route("**/*", lambda route: route.abort())
        html = re.sub(r'<script src="[^"]+"></script>', '', HTML.read_text(encoding="utf-8"))
        tab.set_content(html.replace('    connect();', '    /* offline */'))
        tab.evaluate("""() => {
          window.marked = {parse: text => '<p>'+text+'</p>'};
          chatFeed.snapshot(Array.from({length: 200}, (_,i) =>
            ({id: 'm'+i, role:'user', msg:'message '+i+'<br>'.repeat(8)})));
          flushRender();
        }""")
        yield tab
        browser.close()
        assert not errors


def test_paged_history_follow_read_and_reconnect(page):
    assert page.locator('#messages > .msg').count() == 50
    result = page.evaluate("""() => {
      messagesEl.previousElementSibling.querySelector('button').click(); flushRender();
      messagesEl.scrollTop=100;
      const first=messagesEl.firstElementChild, top=messagesEl.scrollTop;
      for(let i=0;i<1000;i++) addMsg({id:'new'+i,role:'user',msg:'new '+i});
      flushRender();
      const stable=first===messagesEl.firstElementChild && top===messagesEl.scrollTop;
      markAllRead();
      messagesEl.previousElementSibling.querySelectorAll('button')[2].click(); flushRender();
      const latest=messagesEl.lastElementChild.dataset.id;
      chatFeed.snapshot([{id:'new999',role:'user',msg:'new 999',read:true}]); flushRender();
      return {stable,latest,count:messagesEl.children.length,
        unread:messagesEl.querySelectorAll('.unread').length,
        total:messagesEl.previousElementSibling.querySelector('span').textContent};
    }""")
    assert result == dict(stable=True, latest='new999', count=50, unread=0, total='1151–1200 / 1200')
    assert page.evaluate("""() => {
      messagesEl.scrollTop=0;const node=messagesEl.firstElementChild;
      addMsg({id:'later',msg:'later'});flushRender();
      return messagesEl.scrollTop===0 && messagesEl.firstElementChild===node;
    }""")


def test_card_identity_and_lazy_logs(page):
    result=page.evaluate("""() => {
      const cards=[{id:'a',status:'running',reply:'one'},{id:'b',status:'idle',reply:'two'}];
      renderCards(cards);flushRender();const first=cardsEl.firstElementChild;first.classList.add('expanded');
      const observer=new MutationObserver(()=>{});observer.observe(cardsEl,{subtree:true,childList:true,attributes:true});
      for(let i=0;i<100;i++){renderCards(cards);flushRender()}
      const mutations=observer.takeRecords().length;observer.disconnect();
      renderCards([...cards].reverse());flushRender();
      const identity=cardsEl.lastElementChild===first && first.classList.contains('expanded');
      for(let i=0;i<500;i++)appendLog({ts:i,turn:i,event:'test',text:'entry '+i});flushRender();
      const closed=consoleBody.children.length;consoleBar.click();flushRender();
      return {mutations,identity,closed,opened:consoleBody.children.length};
    }""")
    assert result == dict(mutations=0, identity=True, closed=0, opened=50)


def test_logs_keep_panel_without_pagination(page):
    result = page.evaluate("""() => {
      for(let i=0;i<51;i++) appendLog({ts:i,turn:i,event:'test',text:'entry '+i});
      flushRender(); consoleBar.click(); flushRender();
      const first = consoleBody.firstElementChild.textContent;
      consoleBody.scrollTop=0;
      appendLog({ts:51,turn:51,event:'test',text:'entry 51'}); flushRender();
      consoleBar.click(); flushRender(); consoleBar.click(); flushRender();
      return {panel:!!document.getElementById('console'),
        logNav:consoleEl.querySelectorAll('.history-nav').length,
        chatNav:messagesEl.previousElementSibling.classList.contains('history-nav'),
        totalNav:document.querySelectorAll('.history-nav').length,
        count:consoleBody.children.length, first,
        last:consoleBody.lastElementChild.textContent, retained:logCount.textContent};
    }""")
    assert result['panel'] and result['chatNav']
    assert result['logNav'] == 0 and result['totalNav'] == 1
    assert result['count'] == 50 and result['retained'] == '· 50 条'
    assert result['first'].endswith('entry 1')
    assert result['last'].endswith('entry 51')
