# SPDX-License-Identifier: GPL-3.0-or-later
"""Local catalogs follow the language Krita selected for its interface."""
import json
from pathlib import Path

CATALOGS = Path(__file__).with_name('translations')
_language = None
_messages = {}


def resolve_language(language, available):
    language = language.split('.', 1)[0].replace('-', '_')
    normalized = {code.casefold(): code for code in available}
    if language.casefold() in normalized:
        return normalized[language.casefold()]
    base = language.split('_', 1)[0].split('@', 1)[0]
    return normalized.get(base.casefold(), 'en')


def set_language(language=None):
    """Called once on startup; Krita's language switch also requires a restart."""
    global _language, _messages
    if language is None:
        from .qt import QLocale, QSettings, QStandardPaths, QCoreApplication
        config = QStandardPaths.locate(QStandardPaths.StandardLocation.GenericConfigLocation,
                                       'klanguageoverridesrc')
        override = QSettings(config, QSettings.Format.IniFormat).value(
            'Language/'+QCoreApplication.applicationName(), '') if config else ''
        # Preserve KDE variants (ca@valencia, uz@cyrillic, tok) that QLocale
        # cannot represent. The override takes precedence over the OS locale.
        language = str(override).split(':', 1)[0] if override else QLocale().name()
    available = {p.stem for p in CATALOGS.glob('*.json')}
    _language = resolve_language(language, available)
    path = CATALOGS/(_language+'.json')
    _messages = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return _language


def tr(source):
    if _language is None:
        set_language()
    return _messages.get(source, source)


def language():
    if _language is None:
        set_language()
    return _language
