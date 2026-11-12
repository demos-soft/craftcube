"""Selenium parity regression suite against the live staging instance.

These tests guard the behavioural details that unit tests cannot reach:
reference row-selection semantics, the nested folder tree, the refresh
info box, the import dialog and the spellcheck RPC. They run against
the staged CraftCube on k8s3 and skip cleanly when selenium, the
browser or the server is unavailable.

Run:  .venv/bin/python -m pytest tests/test_selenium_staging.py
"""

import os
import socket
import time

import pytest

pytest.importorskip("selenium")
from selenium import webdriver  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

CC = os.environ.get("CRAFTCUBE_STAGING_URL", "http://k8s3.lan:30090")
CHROME_BIN = os.environ.get(
    "CHROME_BIN", "/home/ubuntu/.hermes/tools/chromium-1208/chrome-linux64/chrome")
USER = os.environ.get("CRAFTCUBE_STAGING_USER", "test@example.org")
PASSWORD = os.environ.get("CRAFTCUBE_STAGING_PASS", "secret")


def _reachable():
    try:
        hostport = CC.split("//", 1)[1].split("/", 1)[0]
        host, _, port = hostport.partition(":")
        with socket.create_connection((host, int(port or 80)), 2.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.staging


@pytest.fixture(scope="module")
def driver():
    if not _reachable():
        pytest.skip("staging instance not reachable at " + CC)
    opts = webdriver.ChromeOptions()
    if os.path.isfile(CHROME_BIN):
        opts.binary_location = CHROME_BIN
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,900")
    try:
        drv = webdriver.Chrome(options=opts)
    except Exception as exc:  # chromedriver missing etc.
        pytest.skip("chromedriver unavailable: %s" % exc)
    try:
        _login(drv)
    except Exception as exc:
        drv.quit()
        pytest.skip("staging login failed: %s" % exc)
    yield drv
    drv.quit()


def _login(drv):
    drv.get(CC + "/mail")
    time.sleep(1.2)
    if "login" in drv.current_url:
        drv.find_element(By.ID, "rcmloginuser").send_keys(USER)
        drv.find_element(By.ID, "rcmloginpwd").send_keys(PASSWORD)
        drv.find_element(By.ID, "rcmloginsubmit").click()
        _wait_until(drv, lambda d: "/mail" in d.current_url)


def _wait_until(drv, fn, timeout=12.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            if fn(drv):
                return True
        except Exception as exc:
            last = exc
        time.sleep(0.25)
    raise AssertionError("condition not met" + (" last=" + str(last) if last else ""))


def _open_list(drv):
    if not drv.current_url.endswith("/mail") and "/mail?" not in drv.current_url:
        drv.get(CC + "/mail")
        time.sleep(0.8)
        if "login" in drv.current_url:
            _login(drv)


def _rows(drv):
    _wait_until(drv, lambda d: len(d.find_elements(
        By.CSS_SELECTOR, "#messagelist tbody tr.message")) > 1)
    return drv.find_elements(By.CSS_SELECTOR, "#messagelist tbody tr.message")


def _click(drv, el, ctrl=False, shift=False):
    # mouse-activation on the subject cell (keyboard_only links): a real
    # click sequence with detail=1 like a browser would deliver
    drv.execute_script(
        "var el=arguments[0];var c=arguments[1];var s=arguments[2];"
        "['mousedown','mouseup','click'].forEach(function(t){"
        "el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,"
        "detail:1,view:window,ctrlKey:c,shiftKey:s}));});",
        el, ctrl, shift)


def _selected_flags(drv):
    return drv.execute_script(
        "return [...document.querySelectorAll('#messagelist tbody tr.message')]"
        ".map(function(r){return r.classList.contains('selected')?'1':'0';}).join('');")


def test_single_click_selects_without_navigating(driver):
    _open_list(driver)
    rows = _rows(driver)
    _click(driver, rows[0].find_element(By.CSS_SELECTOR, "td.subject"))
    time.sleep(0.3)
    assert _selected_flags(driver)[0] == "1"
    assert _selected_flags(driver).count("1") == 1
    assert "_uid=" not in driver.current_url, "single click must not open the message"
    # toolbar follows the selection (reference selection_changed)
    disabled = driver.execute_script(
        "return document.querySelector('#tb-delete').classList.contains('disabled');")
    assert disabled is False


def test_ctrl_click_toggles_and_shift_extends(driver):
    _open_list(driver)
    rows = _rows(driver)
    _click(driver, rows[0].find_element(By.CSS_SELECTOR, "td.subject"))
    time.sleep(0.2)
    _click(driver, rows[2].find_element(By.CSS_SELECTOR, "td.subject"), ctrl=True)
    time.sleep(0.2)
    flags = _selected_flags(driver)
    assert flags[0] == "1" and flags[2] == "1"
    assert flags.count("1") == 2
    _click(driver, rows[4].find_element(By.CSS_SELECTOR, "td.subject"), shift=True)
    time.sleep(0.2)
    flags = _selected_flags(driver)
    # plain shift-click replaces the set with the contiguous anchor..target range
    assert flags[2:5] == "111"
    assert flags.count("1") == 3


def test_dblclick_opens_message_view(driver):
    _open_list(driver)
    rows = _rows(driver)
    uid = rows[1].get_attribute("data-uid")
    driver.execute_script(
        "arguments[0].dispatchEvent(new MouseEvent('dblclick',"
        "{bubbles:true,cancelable:true,detail:2,view:window}));", rows[1])
    _wait_until(driver, lambda d: "_uid=" in d.current_url)
    assert uid and ("_uid=" + uid) in driver.current_url
    _open_list(driver)


def test_folder_tree_is_nested_and_folds_persist(driver):
    _open_list(driver)
    nested = driver.execute_script(
        "var li=document.querySelector('#mailboxlist li[data-name=\"INBOX\"]');"
        "if (!li) return -1;"
        "var ul=li.querySelector('ul');"
        "return ul ? ul.querySelectorAll('li').length : 0;")
    assert nested >= 1, "subtree of INBOX missing from the mail sidebar tree"
    caret_shown = driver.execute_script(
        "var li=document.querySelector('#mailboxlist li[data-name=\"INBOX\"]');"
        "var t=li.querySelector('.treetoggle');"
        "return !!t && getComputedStyle(t).display !== 'none';")
    assert caret_shown, "treetoggle caret not visible on a parent folder"
    # collapse the INBOX subtree and verify persistence across a reload
    driver.execute_script(
        "document.querySelector("
        "'#mailboxlist li[data-name=\"INBOX\"] .treetoggle')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,view:window}));")
    time.sleep(0.3)
    collapsed = driver.execute_script(
        "var li=document.querySelector('#mailboxlist li[data-name=\"INBOX\"]');"
        "var ul=li.querySelector('ul');"
        "return li.getAttribute('aria-expanded') === 'false' "
        "&& getComputedStyle(ul).display === 'none';")
    assert collapsed
    driver.refresh()
    time.sleep(1.0)
    still = driver.execute_script(
        "var li=document.querySelector('#mailboxlist li[data-name=\"INBOX\"]');"
        "var ul=li && li.querySelector('ul');"
        "return ul ? getComputedStyle(ul).display === 'none' : null;")
    assert still is True
    # restore expanded state for the following tests
    driver.execute_script(
        "document.querySelector("
        "'#mailboxlist li[data-name=\"INBOX\"] .treetoggle')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,view:window}));")
    time.sleep(0.2)


def test_refresh_shows_loading_box_in_place(driver):
    _open_list(driver)
    driver.execute_script(
        "window.__boxes = [];"
        "new MutationObserver(function(ms){ms.forEach(function(m){"
        "m.addedNodes.forEach(function(n){window.__boxes.push(n.className);});});})"
        ".observe(document.getElementById('messagestack'), {childList:true});")
    before = len(_rows(driver))
    driver.execute_script(
        "document.querySelector('a.refresh')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,detail:1,view:window}));")
    time.sleep(1.5)
    assert any("loading" in cls for cls in
               driver.execute_script("return window.__boxes;")), \
        "no 'loading' info box was shown during refresh"
    # still the same list page, rows intact, info box cleaned up
    assert "_uid=" not in driver.current_url
    assert len(_rows(driver)) == before
    _wait_until(driver, lambda d: len(d.find_elements(
        By.CSS_SELECTOR, "#messagestack div")) == 0, timeout=15)


def test_import_menu_item_enabled_without_selection(driver):
    _open_list(driver)
    # ensure nothing is selected
    driver.execute_script(
        "[...document.querySelectorAll('#messagelist tbody tr.message.selected')]"
        ".forEach(function(r){r.classList.remove('selected');"
        "var cb=r.querySelector('td.selection input'); if(cb) cb.checked=false;});")
    driver.execute_script(
        "document.querySelector('#messagemenulink')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,detail:1,view:window}));")
    time.sleep(0.4)
    disabled = driver.execute_script(
        "return document.querySelector('#message-menu a.import')"
        ".classList.contains('disabled');")
    assert disabled is False, "Import must not be gated on a selection"


def test_import_dialog_opens_and_validates(driver):
    _open_list(driver)
    driver.execute_script(
        "document.querySelector('#messagemenulink')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,detail:1,view:window}));")
    time.sleep(0.3)
    driver.execute_script(
        "document.querySelector('#message-menu a.import')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,detail:1,view:window}));")
    _wait_until(driver, lambda d: d.find_elements(
        By.CSS_SELECTOR, ".ui-dialog .ui-dialog-title"))
    title = driver.find_element(By.CSS_SELECTOR, ".ui-dialog .ui-dialog-title").text
    assert title == "Import messages"
    assert driver.find_elements(By.CSS_SELECTOR, ".ui-dialog input[type=file]")
    # clicking Import without a file shows the reference error message
    driver.execute_script(
        "var b=document.querySelector('.ui-dialog button.import'); b.click();")
    time.sleep(0.5)
    texts = driver.execute_script(
        "return [...document.querySelectorAll('#messagestack div')]"
        ".map(function(d){return d.textContent;});")
    assert any("select a file" in t for t in texts), \
        "missing 'Please select a file to upload.' feedback: %r" % (texts,)
    driver.execute_script(
        "document.querySelector('.ui-dialog .ui-dialog-titlebar-close').click();")
    time.sleep(0.3)
    assert not driver.find_elements(By.CSS_SELECTOR, ".ui-dialog")


def test_html_spellcheck_rpc(driver):
    driver.get(CC + "/compose")
    time.sleep(1.0)
    if "login" in driver.current_url:
        _login(driver)
        driver.get(CC + "/compose")
    _wait_until(driver, lambda d: d.find_elements(By.ID, "composebody"))
    # switch to HTML mode via the reference editor selector
    driver.execute_script(
        "window.cc_editor.command('toggle-editor',"
        "{id:'composebody', html:true});")
    _wait_until(driver, lambda d: d.execute_script(
        "return !!window.tinymce && !!window.tinymce.activeEditor;"), timeout=15)
    driver.execute_script(
        "window.__xhrs = [];"
        "var oo = XMLHttpRequest.prototype.open;"
        "XMLHttpRequest.prototype.open = function(m, u) {"
        "this.__u = u; return oo.apply(this, arguments); };"
        "var os = XMLHttpRequest.prototype.send;"
        "XMLHttpRequest.prototype.send = function() {"
        "window.__xhrs.push(this.__u); return os.apply(this, arguments); };")
    driver.execute_script(
        "window.tinymce.activeEditor.setContent('teh quick brown fox');"
        "document.getElementById('tb-spell')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,detail:1,view:window}));")
    _wait_until(driver, lambda d: any(
        "spell" in u for u in d.execute_script("return window.__xhrs;")), timeout=10)
    hits = [u for u in driver.execute_script("return window.__xhrs;") if "spell" in u]
    assert any("spell_html" in u for u in hits), \
        "spellcheck did not call the RPC endpoint: %r" % (hits,)


def _open_compose(drv):
    # /compose is a plain server-rendered page; right after a fixture login
    # an occasional driver.get lands back on the inbox, so retry until the
    # textarea is present.
    for _ in range(3):
        drv.get(CC + "/compose")
        try:
            _wait_until(drv, lambda d: d.find_elements(By.ID, "composebody"), timeout=8)
            return
        except AssertionError:
            continue
    raise AssertionError("compose body never appeared")


def test_plain_spellcheck_googie_layer(driver):
    """Plain compose Spell must open the GoogieSpell edit layer with
    clickable errors and server suggestions (googiespell.js parity),
    not merely toggle the native spellcheck attribute."""
    _open_compose(driver)
    _wait_until(driver, lambda d: d.execute_script("return !!window.googie;"), timeout=25)
    body = driver.find_element(By.ID, "composebody")
    driver.execute_script("arguments[0].value = '';", body)
    body.send_keys("Teh quik brown fox sent the moon.")
    driver.execute_script(
        "document.getElementById('tb-spell')"
        ".dispatchEvent(new MouseEvent('click',"
        "{bubbles:true,cancelable:true,detail:1,view:window}));")
    _wait_until(driver, lambda d: d.find_elements(
        By.CSS_SELECTOR, ".googie_edit_layer .googie_link"))
    links = driver.find_elements(By.CSS_SELECTOR, ".googie_edit_layer .googie_link")
    words = [l.text for l in links]
    assert words == ["Teh", "quik"], words
    # the first error opens the Googie suggestion menu
    links[0].click()
    _wait_until(driver, lambda d: d.find_elements(
        By.CSS_SELECTOR, ".googie_window .googie_list li a"))
    items = driver.find_elements(By.CSS_SELECTOR, ".googie_window .googie_list li a")
    sugg = [i.text for i in items]
    assert "The" in sugg, sugg
    items[sugg.index("The")].click()
    _wait_until(driver, lambda d: d.execute_script(
        "return document.getElementById('composebody').value"
        ".split(' ')[0] === 'The';"))
