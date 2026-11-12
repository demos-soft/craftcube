"""Server-side spellchecker for the TinyMCE editor — mirrors
rcube_spellchecker (pspell engine) + rcmail_action_utils_spell_html.

TinyMCE's spellchecker plugin POSTs:
    method=spelling&lang=<code>&text=<html>          -> {"words": {w: [..]}}
    method=addToDictionary&lang=<code>&word=<w>      -> {"result": true}
"""

import re
import subprocess
from html import unescape

_ENGINES = ("hunspell", "aspell")


def _run(cmd, data):
    p = subprocess.run(cmd, input=data.encode("utf-8"),
                       capture_output=True, timeout=30)
    return p.stdout.decode("utf-8", errors="replace")


def _available():
    import shutil
    for e in _ENGINES:
        if shutil.which(e):
            return e
    return None


def _dict_for(lang):
    # en_US -> en_US for hunspell dicts that ship it, else base 'en'
    return (lang or "en").replace("-", "_")


def check(text, lang):
    """rcube_spellchecker::check()/get(): {word: [suggestions]} for words
    that are misspelled; {} when everything is fine."""
    engine = _available()
    if not engine:
        return None  # engine error -> caller returns internalerror
    # strip html tags/entities like rcube_spellchecker does
    text = re.sub(r"<[^>]+>", " ", unescape(text))
    if engine == "hunspell":
        d = _dict_for(lang)
        out = _run(["hunspell", "-d", d, "-a"], text)
        if ":" not in out.split("\n", 1)[0]:  # 'file line: word ...' header
            d = lang.split("_")[0]
            out = _run(["hunspell", "-d", d, "-a"], text)
        words = {}
        for line in out.splitlines():
            if ":" not in line or not line[0].isdigit():
                continue
            try:
                _, rest = line.split(":", 1)
            except ValueError:
                continue
            parts = rest.split()
            if not parts:
                continue
            word = parts[0].strip("&")
            sugg = [s for s in parts[1:] if not s.startswith("*")
                    and not s[0] in "+-?@"]
            words[word] = sugg
        return words
    # aspell
    d = lang.split("_")[0]
    out = _run(["aspell", "--lang=" + d, "list"], text)
    words = {w: [] for w in out.split() if w.strip()}
    return words


def add_word(word):
    # personal dictionaries are not enabled (spellcheck_dictionary=false in
    # the reference default) — accept silently like rcube_spellchecker does
    return True
