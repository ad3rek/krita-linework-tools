# SPDX-License-Identifier: GPL-3.0-or-later
"""Locale variants, fallback safety and translated formatting contracts."""
import ast
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog_test', ROOT/'linework/i18n.py')
i18n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i18n)


class TranslationTests(unittest.TestCase):
    def test_locale_variant_and_english_fallback(self):
        available = {'en', 'pt', 'pt_BR', 'ca@valencia', 'uz@cyrillic', 'es'}
        for incoming, expected in [('pt-BR', 'pt_BR'), ('pt-br.UTF-8', 'pt_BR'),
                                   ('es_MX', 'es'), ('ca@valencia', 'ca@valencia'),
                                   ('uz@cyrillic', 'uz@cyrillic'), ('xx_YY', 'en')]:
            self.assertEqual(i18n.resolve_language(incoming, available), expected)

    def test_portuguese_and_english_switch_preserve_formatting(self):
        i18n.set_language('pt_BR')
        self.assertEqual(i18n.tr('Apply brush'), 'Aplicar pincel')
        self.assertIn('3 traços', i18n.tr("{0} strokes · {1} points · {2:.2f} s").format(3, 12, 1.25))
        self.assertEqual(i18n.tr('Unknown future message'), 'Unknown future message')
        i18n.set_language('en')
        self.assertEqual(i18n.tr('Apply brush'), 'Apply brush')

    def test_every_catalog_preserves_format_fields_and_has_no_translation_markers(self):
        fields = re.compile(r'\{[^{}]*\}')
        for path in i18n.CATALOGS.glob('*.json'):
            for source, translated in json.loads(path.read_text()).items():
                with self.subTest(language=path.stem, message=source):
                    self.assertIsInstance(translated, str)
                    self.assertTrue(translated.strip())
                    self.assertEqual(Counter(fields.findall(source)), Counter(fields.findall(translated)))
                    self.assertNotRegex(translated, r'LWPH\d|LWNEWLINE|LW\d{4}:')

    def test_all_visible_translation_calls_use_catalog_source_keys(self):
        sources = set(json.loads((i18n.CATALOGS/'pt_BR.json').read_text()))
        english_labels = {'Linework Brush','Linework Curve','Linework Line','Linework Edit',
                          'Linework Thickness','Linework Erase'}
        for path in (ROOT/'linework').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'tr' and node.args and isinstance(node.args[0], ast.Constant)):
                    self.assertIn(node.args[0].value, sources | english_labels, path.name)


if __name__ == '__main__': unittest.main()
