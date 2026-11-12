"""Preference catalogue data for the settings UI.

Option lists mirror the reference build (Roundcube Elastic) exactly;
static ones were extracted from the running reference instance, the
timezone list is computed at runtime (see build_timezones below).
"""

import calendar
import datetime
import os
import zoneinfo

LANGUAGES = [
    ('sq_AL', 'Albanian (Shqip)'),
    ('ar_SA', 'Arabic (Saudi Arabia)'),
    ('ar', 'Arabic (العربية)'),
    ('hy_AM', 'Armenian (Հայերեն)'),
    ('ast', 'Asturiana (Asturianu)'),
    ('az_AZ', 'Azerbaijani (Azərbaycanca)'),
    ('eu_ES', 'Basque (Euskara)'),
    ('be_BE', 'Belarusian (беларуская мова)'),
    ('bn_BD', 'Bengali (বাংলা)'),
    ('bs_BA', 'Bosnian (Bosanski)'),
    ('br', 'Breton (Brezhoneg)'),
    ('bg_BG', 'Bulgarian (Български)'),
    ('ca_ES', 'Catalan (Català)'),
    ('zh_TW', 'Chinese (正體中文)'),
    ('zh_CN', 'Chinese (简体中文)'),
    ('hr_HR', 'Croatian (Hrvatski)'),
    ('cs_CZ', 'Czech (Česky)'),
    ('da_DK', 'Danish (Dansk)'),
    ('fa_AF', 'Dari (ﻯﺭﺩ)'),
    ('nl_NL', 'Dutch (Nederlands)'),
    ('en_CA', 'English (Canada)'),
    ('en_GB', 'English (GB)'),
    ('en_US', 'English (US)'),
    ('eo', 'Esperanto'),
    ('et_EE', 'Estonian (Eesti)'),
    ('fo_FO', 'Faroese (Føroyskt)'),
    ('fi_FI', 'Finnish (Suomi)'),
    ('nl_BE', 'Flemish (Vlaams)'),
    ('fr_FR', 'French (Français)'),
    ('gl_ES', 'Galician (Galego)'),
    ('ka_GE', 'Georgian (ქართული)'),
    ('de_DE', 'German (Deutsch)'),
    ('de_CH', 'German (Schweiz)'),
    ('el_GR', 'Greek (Ελληνικά)'),
    ('he_IL', 'Hebrew (עברית)'),
    ('hi_IN', 'Hindi (हिनदी)'),
    ('hu_HU', 'Hungarian (Magyar)'),
    ('is_IS', 'Icelandic (Íslenska)'),
    ('id_ID', 'Indonesian (Bahasa Indonesia)'),
    ('ia', 'Interlingua'),
    ('ga_IE', 'Irish (Gaedhilge)'),
    ('it_IT', 'Italian (Italiano)'),
    ('ja_JP', 'Japanese (日本語)'),
    ('kab', 'Kabyle (Taqbaylit)'),
    ('km_KH', 'Khmer (ភាសាខ្មែរ)'),
    ('kn_IN', 'Konkani (कोंकणी)'),
    ('ko_KR', 'Korean (한국어)'),
    ('ku', 'Kurdish (Kurmancî)'),
    ('lv_LV', 'Latvian (Latviešu)'),
    ('lt_LT', 'Lithuanian (Lietuviškai)'),
    ('lb_LU', 'Luxembourgish (Lëtzebuergesch)'),
    ('mk_MK', 'Macedonian (Македонски)'),
    ('ms_MY', 'Malay (Bahasa Melayu)'),
    ('ml_IN', 'Malayalam (മലയാളം)'),
    ('mr_IN', 'Marathi (मराठी)'),
    ('mn_MN', 'Mongolic (Монгол)'),
    ('ne_NP', 'Nepali (नेपाली)'),
    ('nb_NO', 'Norwegian (Bokmål)'),
    ('nn_NO', 'Norwegian (Nynorsk)'),
    ('ps', 'Pashto'),
    ('fa_IR', 'Persian (فارسی)'),
    ('pl_PL', 'Polish (Polski)'),
    ('pt_BR', 'Portuguese (Brasil)'),
    ('pt_PT', 'Portuguese (Português)'),
    ('ro_RO', 'Romanian (Româneşte)'),
    ('ru_RU', 'Russian (Русский)'),
    ('sr_CS', 'Serbian (Српски)'),
    ('si_LK', 'Sinhalese (සිංහල)'),
    ('sk_SK', 'Slovak (Slovenčina)'),
    ('sl_SI', 'Slovenian (Slovenščina)'),
    ('es_AR', 'Spanish (Argentina)'),
    ('es_ES', 'Spanish (Español)'),
    ('es_419', 'Spanish (Latin America)'),
    ('sv_SE', 'Swedish (Svenska)'),
    ('tzl', 'Talossan'),
    ('ta_IN', 'Tamil (தமிழ்)'),
    ('th_TH', 'Thai (ไทย)'),
    ('ti', 'Tigrinya (ትግርኛ)'),
    ('tr_TR', 'Turkish (Türkçe)'),
    ('uk_UA', 'Ukrainian (Українська)'),
    ('ur_PK', 'Urdu (اُردو)'),
    ('ug', 'Uyghur (ئۇيغۇر)'),
    ('uz', 'Uzbek (Oʻzbekcha)'),
    ('vi_VN', 'Vietnamese (Tiếng Việt)'),
    ('cy_GB', 'Welsh (Cymraeg)'),
    ('fy_NL', 'West Frisian (Frysk)'),
]

# Timezone options are built at runtime from the system tzdata, exactly like
# the reference: rcmail_action_settings_index::user_prefs() iterates
# DateTimeZone::listIdentifiers() through timezone_standard_time_data() -
# "move back a month (up to 12 times) until non-DST" - labels
# "(GMT <offset>) <Zone/Name with spaces>", sorted by
# sprintf('%06d.%s', offset_seconds + 45000, name), ksort.

PHP_TZ_GROUPS = ("Africa", "America", "Antarctica", "Arctic", "Asia",
                 "Atlantic", "Australia", "Europe", "Indian", "Pacific")

# PHP listIdentifiers() skips Etc/* and backward-compat aliases
# (Pacific/Samoa, America/Atka, ...), but keeps these links that tzdata
# defines in its main zone files (they show up in the reference dropdown):
PHP_MAIN_LINKS = frozenset((
    "America/Kralendijk", "America/Lower_Princes", "America/Marigot",
    "America/St_Barthelemy", "Arctic/Longyearbyen", "Europe/Bratislava",
    "Europe/Busingen", "Europe/Mariehamn", "Europe/Podgorica",
    "Europe/San_Marino", "Europe/Vatican",
))


def _prev_month(dt):
    y, m = dt.year, dt.month - 1
    if m == 0:
        y, m = y - 1, 12
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def _standard_offset(zname):
    """rcmail_action_settings_index::timezone_standard_time_data()"""
    now = datetime.datetime.now(zoneinfo.ZoneInfo(zname))
    for _ in range(12):
        if not now.dst():
            break
        now = _prev_month(now).replace(tzinfo=zoneinfo.ZoneInfo(zname))
    return now.utcoffset()


def _php_identifiers():
    """DateTimeZone::listIdentifiers(): continental-group zones; PHP skips
    link aliases (America/Atka, Pacific/Samoa, ...), which distro tzdata
    ships as symlinks. 'UTC' has no group but is in PHP's list."""
    names = set(zoneinfo.available_timezones()) | {"UTC"}
    out = []
    for z in sorted(names):
        if z != "UTC" and z.split("/")[0] not in PHP_TZ_GROUPS:
            continue
        link = False
        for base in zoneinfo.TZPATH:
            p = os.path.join(base, z)
            if os.path.exists(p):
                link = os.path.islink(p)
                break
        if link and z not in PHP_MAIN_LINKS and z != "UTC":
            continue
        out.append(z)
    return out


def build_timezones():
    zones = []
    for name in _php_identifiers():
        try:
            off = _standard_offset(name)
        except Exception:  # noqa: S112 - bad/incomplete zone: PHP ignores it too
            continue
        secs = int(off.total_seconds()) if off is not None else 0
        sign = "-" if secs < 0 else "+"
        a = abs(secs)
        label = (f"(GMT {sign}{a // 3600:02d}:{(a % 3600) // 60:02d}) "
                 f"{name.replace('_', ' ')}")
        zones.append((f"{secs + 45000:06d}.{name}", (name, label)))
    zones.sort(key=lambda z: z[0])
    return [("auto", "Auto")] + [z[1] for z in zones]


TIMEZONES = build_timezones()

CHARSETS = [
    ('UTF-8', 'UTF-8 (Unicode)'),
    ('US-ASCII', 'ASCII (English)'),
    ('ISO-8859-1', 'ISO-8859-1 (Western European)'),
    ('ISO-8859-2', 'ISO-8859-2 (Eastern European)'),
    ('ISO-8859-4', 'ISO-8859-4 (Baltic)'),
    ('ISO-8859-5', 'ISO-8859-5 (Cyrillic)'),
    ('ISO-8859-6', 'ISO-8859-6 (Arabic)'),
    ('ISO-8859-7', 'ISO-8859-7 (Greek)'),
    ('ISO-8859-8', 'ISO-8859-8 (Hebrew)'),
    ('ISO-8859-9', 'ISO-8859-9 (Turkish)'),
    ('ISO-8859-10', 'ISO-8859-10 (Nordic)'),
    ('ISO-8859-11', 'ISO-8859-11 (Thai)'),
    ('ISO-8859-13', 'ISO-8859-13 (Baltic)'),
    ('ISO-8859-14', 'ISO-8859-14 (Celtic)'),
    ('ISO-8859-15', 'ISO-8859-15 (Western European)'),
    ('ISO-8859-16', 'ISO-8859-16 (South-Eastern European)'),
    ('WINDOWS-1250', 'Windows-1250 (Eastern European)'),
    ('WINDOWS-1251', 'Windows-1251 (Cyrillic)'),
    ('WINDOWS-1252', 'Windows-1252 (Western European)'),
    ('WINDOWS-1253', 'Windows-1253 (Greek)'),
    ('WINDOWS-1254', 'Windows-1254 (Turkish)'),
    ('WINDOWS-1255', 'Windows-1255 (Hebrew)'),
    ('WINDOWS-1256', 'Windows-1256 (Arabic)'),
    ('WINDOWS-1257', 'Windows-1257 (Baltic)'),
    ('WINDOWS-1258', 'Windows-1258 (Vietnamese)'),
    ('ISO-2022-JP', 'ISO-2022-JP (Japanese)'),
    ('ISO-2022-KR', 'ISO-2022-KR (Korean)'),
    ('ISO-2022-CN', 'ISO-2022-CN (Chinese)'),
    ('EUC-JP', 'EUC-JP (Japanese)'),
    ('EUC-KR', 'EUC-KR (Korean)'),
    ('EUC-CN', 'EUC-CN (Chinese)'),
    ('BIG5', 'BIG5 (Chinese)'),
    ('GB2312', 'GB2312 (Chinese)'),
    ('KOI8-R', 'KOI8-R (Cyrillic)'),
]

MAIL_READ_TIME = [
    ('-1', 'never'),
    ('0', 'immediately'),
    ('5', 'after 5 seconds'),
    ('10', 'after 10 seconds'),
    ('20', 'after 20 seconds'),
    ('30', 'after 30 seconds'),
]

AUTOEXPAND_THREADS = [
    ('0', 'never'),
    ('1', 'all threads'),
    ('2', 'only with unread messages'),
]

SHOW_IMAGES = [
    ('0', 'never'),
    ('1', 'from my contacts'),
    ('3', 'from trusted senders'),
    ('2', 'always'),
]

MDN_REQUESTS = [
    ('0', 'ask me'),
    ('1', 'send receipt'),
    ('3', 'send receipt to my contacts, otherwise ask me'),
    ('4', 'send receipt to my contacts, otherwise ignore'),
    ('5', 'send receipt to trusted senders, otherwise ask me'),
    ('6', 'send receipt to trusted senders, otherwise ignore'),
    ('2', 'ignore request'),
]

HTMLEDITOR = [
    ('0', 'never'),
    ('2', 'on reply to HTML message'),
    ('3', 'on forward or reply to HTML message'),
    ('1', 'always'),
    ('4', 'always, except when replying to plain text'),
]

DRAFT_AUTOSAVE = [
    ('0', 'never'),
    ('60', 'every 1 minute(s)'),
    ('180', 'every 3 minute(s)'),
    ('300', 'every 5 minute(s)'),
    ('600', 'every 10 minute(s)'),
]

REPLY_MODE = [
    ('-1', 'do not quote the original message'),
    ('0', 'start new message below the quote'),
    ('1', 'start new message above the quote'),
    ('2', 'start new message above the quote (no indentation)'),
]

FORWARD_ATTACHMENT = [
    ('0', 'inline'),
    ('1', 'as attachment'),
]

REPLY_ALL_MODE = [
    ('0', 'reply to all'),
    ('1', 'reply to mailing list only (if found)'),
]

SHOW_SIG = [
    ('0', 'never'),
    ('1', 'always'),
    ('2', 'new message only'),
    ('3', 'replies and forwards only'),
]

MIME_PARAM_FOLDING = [
    ('0', 'Full RFC 2231 (Thunderbird)'),
    ('1', 'RFC 2047/2231 (MS Outlook)'),
    ('2', 'Full RFC 2047 (other)'),
]

ADDRESSBOOK_NAME_LISTING = [
    ('0', 'Display Name'),
    ('1', 'First Name Last Name'),
    ('2', 'Last Name First Name'),
    ('3', 'Last Name, First Name'),
]

ADDRESSBOOK_SORT_COL = [
    ('name', 'Display Name'),
    ('firstname', 'First Name'),
    ('surname', 'Last Name'),
]

CONTACT_FORM_MODE = [
    ('private', 'Private (Home)'),
    ('business', 'Business (Work)'),
]

COLLECTED_RECIPIENTS = [
    ('', '---'),
    ('1', 'Collected Recipients'),
    ('0', 'Personal Addresses'),
]

COLLECTED_SENDERS = [
    ('2', 'Trusted Senders'),
    ('0', 'Personal Addresses'),
]

LOGOUT_PURGE = [
    ('never', 'never'),
    ('all', 'all messages'),
    ('30', 'older than 30 days'),
    ('60', 'older than 60 days'),
    ('90', 'older than 90 days'),
]

ARCHIVE_TYPE = [
    ('', 'None'),
    ('year', 'Year (e.g. Archive/2012)'),
    ('month', 'Month (e.g. Archive/2012/06)'),
    ('tbmonth', 'Month - Thunderbird compatible (e.g. Archive/2012/2012-06)'),
    ('sender', 'Sender email'),
    ('folder', 'Original folder'),
    ('folderyear', 'Year and the original folder (e.g. Archive/2012/...)'),
    ('foldermonth', 'Year, month and the original folder (e.g. Archive/2012/06/...)'),
]

REFRESH_INTERVAL = [
    ('0', 'never'),
    ('1', 'every 1 minute(s)'),
    ('3', 'every 3 minute(s)'),
    ('5', 'every 5 minute(s)'),
    ('10', 'every 10 minute(s)'),
    ('15', 'every 15 minute(s)'),
    ('30', 'every 30 minute(s)'),
    ('60', 'every 60 minute(s)'),
]

TIME_FORMAT = [
    ('G:i', '7:30'),
    ('H:i', '07:30'),
    ('g:i a', '7:30 am'),
    ('h:i A', '07:30 AM'),
]

DATE_FORMAT = [
    ('Y-m-d', '2026-07-24'),
    ('Y/m/d', '2026/07/24'),
    ('Y.m.d', '2026.07.24'),
    ('d-m-Y', '24-07-2026'),
    ('d/m/Y', '24/07/2026'),
    ('d.m.Y', '24.07.2026'),
    ('j.n.Y', '24.7.2026'),
]

FONTS = [['', ''], ['Andale Mono', 'Andale Mono'], ['Arial', 'Arial'], ['Arial Black', 'Arial Black'], ['Book Antiqua', 'Book Antiqua'], ['Courier New', 'Courier New'], ['Georgia', 'Georgia'], ['Helvetica', 'Helvetica'], ['Impact', 'Impact'], ['Tahoma', 'Tahoma'], ['Terminal', 'Terminal'], ['Times New Roman', 'Times New Roman'], ['Trebuchet MS', 'Trebuchet MS'], ['Verdana', 'Verdana']]

FONT_SIZES = [['', ''], ['8pt', '8pt'], ['9pt', '9pt'], ['10pt', '10pt'], ['11pt', '11pt'], ['12pt', '12pt'], ['14pt', '14pt'], ['18pt', '18pt'], ['24pt', '24pt'], ['36pt', '36pt']]


# rcmail config equivalent: available_fonts / available_font_sizes — the
# default_font preference stores a key of this map; the editor's content
# style uses the mapped CSS family list (compose.php:135 + rcmail_action.php:410)
AVAILABLE_FONTS = {
    'Andale Mono': '"Andale Mono",Times,monospace',
    'Arial': 'Arial,Helvetica,sans-serif',
    'Arial Black': '"Arial Black","Avant Garde",sans-serif',
    'Book Antiqua': '"Book Antiqua",Palatino,serif',
    'Courier New': '"Courier New",Courier,monospace',
    'Georgia': 'Georgia,Palatino,serif',
    'Helvetica': 'Helvetica,Arial,sans-serif',
    'Impact': 'Impact,Chicago,sans-serif',
    'Tahoma': 'Tahoma,Arial,Helvetica,sans-serif',
    'Terminal': 'Terminal,Monaco,monospace',
    'Times New Roman': '"Times New Roman",Times,serif',
    'Trebuchet MS': '"Trebuchet MS",Geneva,sans-serif',
    'Verdana': 'Verdana,Geneva,sans-serif',
}

AVAILABLE_FONT_SIZES = ['8pt', '9pt', '10pt', '11pt', '12pt', '14pt', '18pt', '24pt', '36pt']
