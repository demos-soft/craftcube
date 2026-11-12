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
    # argv form, fixed executables; never shell=True
    p = subprocess.run(cmd, input=data.encode("utf-8"),  # noqa: S603
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


def _ignored(word, ignore):
    """rcube_spellchecker::_is_correct() ignore options."""
    if not ignore:
        return False
    if ignore.get("syms") and re.search(r"[@#$%^&_+~*=\-]", word):
        return True
    if ignore.get("nums") and re.search(r"[0-9]", word):
        return True
    return bool(ignore.get("caps") and word == word.upper())


def check(text, lang, ignore=None):
    """rcube_spellchecker::check()/get(): {word: [suggestions]} for words
    that are misspelled; {} when everything is fine.
    ignore: {'syms','nums','caps'} per spellcheck_ignore_* prefs
    (rcube_spellchecker.php:283-293 - such words count as correct)."""
    engine = _available()
    if not engine:
        return None  # engine error -> caller returns internalerror

    def drop(words):
        return {w: s for w, s in words.items() if not _ignored(w, ignore)}
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
                    and s[0] not in "+-?@"]
            words[word] = sugg
        return drop(words)
    # aspell: pipe mode gives suggestions (`& word n c: s1, s2…`);
    # `# word n c:` = misspelled without suggestions; `-` = correct
    d = lang.split("_")[0]
    out = _run(["aspell", "--lang=" + d, "--encoding=utf-8", "pipe"], text)
    words = {}
    for line in out.splitlines():
        if line.startswith("&"):
            parts = line.split()
            if len(parts) > 1:
                sug = line.split(":", 1)[1] if ":" in line else ""
                words[parts[1]] = [s.strip() for s in sug.split(",") if s.strip()]
        elif line.startswith("#"):
            parts = line.split()
            if len(parts) > 1:
                words.setdefault(parts[1], [])
    return drop(words)


def add_word(word):
    # personal dictionaries are not enabled (spellcheck_dictionary=false in
    # the reference default) — accept silently like rcube_spellchecker does
    return True


# rcube_spellchecker_engine::$separator (spellchecker/engine.php:34)
_SEP_RE = re.compile(r"[\s()\[\]{}<>/\"]+|[:;?!,.](?=\W|$)")

# rcube_spellchecker::check(): links are replaced by same-length blanks
_LINK_RE = re.compile(r"(^|\s)(www\.\S+|[a-z]+://\S+)")

MAX_SUGGESTIONS = 10  # engine.php::MAX_SUGGESTIONS


def find_matches(text, lang, ignore=None):
    """rcube_spellchecker::check() + ->matches for the Googie XML protocol:
    ordered [(word, offset, length, suggestions)] of misspellments; offsets
    are character positions into the plain (link-blanked) text.

    Mirrors spellchecker/pspell.php::check(): tokenize on $separator, trim
    the token, skip words pspell considers correct; offsets use the raw
    token start ($pos = $w[1] - $diff, no leading-trim correction).
    Returns None when no engine is available (caller errors).
    """
    blanked = _LINK_RE.sub(lambda m: m.group(1) + " " * len(m.group(2)), text)
    tokens = []
    pos = 0
    for m in _SEP_RE.finditer(blanked):
        tok = blanked[pos:m.start()]
        if tok:
            word = tok.strip()
            if word:
                tokens.append((word, pos))
        pos = m.end()
    tok = blanked[pos:]
    if tok and tok.strip():
        tokens.append((tok.strip(), pos))
    if not tokens:
        return [], len(blanked)
    # one engine pass over the unique candidate words, reusing check()
    unique = "\n".join(dict.fromkeys(w for w, _ in tokens))
    result = check(unique, lang, ignore=ignore)
    if result is None:
        return None, len(blanked)
    matches = []
    for word, offset in tokens:
        # pspell treats words without letters as correct (numbers, symbols)
        if not any(ch.isalpha() for ch in word):
            continue
        if word in result:
            matches.append((word, offset, len(word), result[word][:MAX_SUGGESTIONS]))
    return matches, len(blanked)
