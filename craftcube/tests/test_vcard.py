"""vCard export byte-parity vs Roundcube 1.7.5 (live-captured oracles).

The expected byte sequences were captured from the reference instance's
/?_task=addressbook&_action=export after seeding the matching contacts."""
from app import util


def _ext(**kw):
    base = {"name": "", "prefix": "", "firstname": "", "middlename": "",
            "surname": "", "suffix": "", "nickname": "", "organization": "",
            "department": "", "jobtitle": "", "gender": "", "birthday": "",
            "notes": "", "emails": [], "phones": [], "addresses": []}
    base.update(kw)
    return base


FULL_ORACLE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\n"
    "N:Lovelace;Ada;King;Right;Hon\r\n"
    "FN:Ada Lovelace King Right Hon\r\n"
    "EMAIL;TYPE=work:ada@example.org\r\n"
    "EMAIL;TYPE=home:ada.lovelace@analytical.example\r\n"
    "NICKNAME:countess\r\n"
    "TITLE:Chief Programmer\r\n"
    "ORG:Analytical Engine Ltd\r\n"
    "X-DEPARTMENT:Engines\r\n"
    "X-GENDER:female\r\n"
    "TEL;TYPE=home:+44 20 7946 0000\r\n"
    "TEL;TYPE=cell:+44 7700 900000\r\n"
    "ADR;TYPE=work:;;12 Byron Row;London;;SW1;United Kingdom\r\n"
    "BDAY;VALUE=date:1815-12-10\r\n"
    "NOTE:first programmer\\; enbows arrows\r\n"
    "CATEGORIES:Mathematicians\r\n"
    "END:VCARD\r\n"
)


def test_export_full_contact():
    ext = _ext(
        name="Ada Lovelace King Right Hon", prefix="Right", firstname="Ada",
        middlename="King", surname="Lovelace", suffix="Hon",
        nickname="countess", organization="Analytical Engine Ltd",
        department="Engines", jobtitle="Chief Programmer", gender="female",
        birthday="1815-12-10", notes="first programmer; enbows arrows",
        emails=[("work", "ada@example.org"),
                ("home", "ada.lovelace@analytical.example")],
        phones=[("home", "+44 20 7946 0000"), ("cell", "+44 7700 900000")],
        addresses=[("work", "12 Byron Row", "London", "SW1", "", "United Kingdom")],
    )
    assert util.vcard_export(ext, categories=["Mathematicians"]) == FULL_ORACLE


NASTY_ORACLE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\n"
    "N:;Grimaldi;;;\r\n"
    "FN:Grimaldi\r\n"
    "EMAIL:grimaldi+test@example.org\r\n"
    "ORG:O\\;rg, Inc\r\n"
    "NOTE:a,b\\;c\\\\d line1\\nline2\r\n"
    "END:VCARD\r\n"
)


def test_export_escaping_v3():
    # v3: semicolons/backslashes escaped, commas NOT, LF -> \n; TYPE=other
    # behaves as untyped on export
    ext = _ext(name="Grimaldi", firstname="Grimaldi",
               notes="a,b;c\\d line1\nline2",
               emails=[("other", "grimaldi+test@example.org")],
               organization="O;rg, Inc")
    assert util.vcard_export(ext) == NASTY_ORACLE


def _fold_note():
    return "".join(f"sentence{i} " for i in range(40))


def test_export_folding():
    # oracle: hard fold at 76 columns, continuation lines start with a space
    ext = _ext(
        name="Fold Test", firstname="Fold", surname="Test", notes=_fold_note(),
        emails=[("work", "a@b.c"), ("work", "a2@b.c")],
        phones=[("", "123")],
        addresses=[("", "Long Street 1234567890 with quite a lot of text to "
                        "force folding of this line here", "Townsville",
                        "", "", "")],
    )
    body = util.vcard_export(ext)
    expected = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\n"
        "N:Test;Fold;;;\r\n"
        "FN:Fold Test\r\n"
        "EMAIL;TYPE=work:a@b.c\r\n"
        "EMAIL;TYPE=work:a2@b.c\r\n"
        "TEL:123\r\n"
        "ADR:;;Long Street 1234567890 with quite a lot of text to force folding of th\r\n"
        " is line here;Townsville;;;\r\n"
        "NOTE:sentence0 sentence1 sentence2 sentence3 sentence4 sentence5 sentence6 s\r\n"
        " entence7 sentence8 sentence9 sentence10 sentence11 sentence12 sentence13 sen\r\n"
        " tence14 sentence15 sentence16 sentence17 sentence18 sentence19 sentence20 se\r\n"
        " ntence21 sentence22 sentence23 sentence24 sentence25 sentence26 sentence27 s\r\n"
        " entence28 sentence29 sentence30 sentence31 sentence32 sentence33 sentence34 \r\n"
        " sentence35 sentence36 sentence37 sentence38 sentence39\r\n"
        "END:VCARD\r\n"
    )
    assert body == expected


def test_parse_roundtrip_of_export_bytes():
    # what the reference export produces, our parser must read back and the
    # exporter must re-emit byte-identically (CATEGORIES is membership data,
    # stripped here the way group membership lives outside the record)
    ext = util.vcard_parse(FULL_ORACLE.replace("CATEGORIES:Mathematicians\r\n", ""))
    assert util.vcard_export(ext) == FULL_ORACLE.replace("CATEGORIES:Mathematicians\r\n", "")
    ext2 = util.vcard_parse(NASTY_ORACLE)
    assert util.vcard_export(ext2) == NASTY_ORACLE
    ext3 = util.vcard_parse(_fold_oracle())
    assert util.vcard_export(ext3) == _fold_oracle()
    assert ext3["emails"] == [("work", "a@b.c"), ("work", "a2@b.c")]
    assert ext3["phones"] == [("", "123")]


def _fold_oracle():
    ext = _ext(name="Fold Test", firstname="Fold", surname="Test",
               notes=_fold_note(),
               emails=[("work", "a@b.c"), ("work", "a2@b.c")],
               phones=[("", "123")],
               addresses=[("", "Long Street 1234567890 with quite a lot of "
                               "text to force folding of this line here",
                           "Townsville", "", "", "")])
    return util.vcard_export(ext)


def test_phone_types_match_elastic_form():
    assert util.CONTACT_EMAIL_TYPES == ["home", "work", "other"]
    assert util.CONTACT_PHONE_TYPES == [
        "home", "home2", "work", "work2", "mobile", "main", "homefax",
        "workfax", "car", "pager", "video", "assistant", "other"]


# rcube_utils::normalize_string() oracles captured from live PHP 1.7.5
NORMALIZE_STORED = [
    ("+44 20 7946 0000", "442079460000"),
    ("O;rg, Inc", "rg inc"),
    ("first programmer; enbows arrows", "first programmer enbows arrows"),
    ("Ada Lovelace King Right Hon", "ada lovelace king right hon"),
    ("ada.lovelace@analytical.example", "ada.lovelace@analytical.example"),
    ("grimaldi+test@example.org", "grimaldi test@example.org"),
    ("Ünïcode Tëst", "unicode test"),
    ("12 Byron Row", "12 byron row"),
]
NORMALIZE_QUERY = [
    ("O;rg", ["o", "rg"]),
    ("lace ad", ["lace", "ad"]),
]


def test_normalize_string_php_oracles():
    for src, want in NORMALIZE_STORED:
        assert util.normalize_string(src) == want, src
    for src, want in NORMALIZE_QUERY:
        assert util.normalize_string(src, as_array=True, minlen=1) == want, src


def test_contact_words_tokens():
    ext = _ext(name="Fold Test", firstname="Fold", surname="Test",
               notes="sentence0 sentence1 ",
               emails=[("work", "a@b.c")], phones=[("", "123")],
               addresses=[("", "Long Street", "Townsville", "", "", "")])
    w = util.contact_words(ext)
    assert "fold" in w and "test" in w
    assert "123" in w and "townsville" in w and "sentence0" in w
