# Interface translations

Linework follows Krita's interface language at startup, including the language
chosen in **Settings → Switch Application Language**. Restart Krita after a
language change, as for Krita's own translated tools. Regional codes resolve to
their matching catalog or base language; missing messages use the English source.

The catalog set includes all 75 locales listed in the Krita 6.0.4.1 source release's
`po/` directory, plus the English source locale. This is locale support, not a claim
that every message has a reviewed translation in every language.

Brazilian Portuguese has been reviewed during development. Exact matches from
Krita's translation catalogs were reused when available; most additional messages
were automatically translated using the public Google Translate service. Only
public interface strings were submitted. Technical terminology needs community
review. Chhattisgarhi (`hne`), Interlingua (`ia`), Low German (`nds`), Toki Pona
(`tok`) and Walloon (`wa`) currently rely mostly on English fallback. Valencian
uses the Catalan draft, Nynorsk includes automatic Norwegian translations and the
Uzbek Cyrillic draft includes automatic transliteration; these variants also need
native-speaker review. Formatting placeholders are checked by automated tests.

## Coverage

Counts indicate explicit entries for the 268 catalog source messages, including
unchanged technical labels. English has full coverage through the source text.
They do not measure translation quality or reviewed terminology.

| Locale | Explicit entries | Remaining English fallback |
| --- | ---: | ---: |
| `af` | 268 | 0 |
| `ar` | 268 | 0 |
| `be` | 268 | 0 |
| `bg` | 268 | 0 |
| `br` | 268 | 0 |
| `bs` | 268 | 0 |
| `ca` | 268 | 0 |
| `ca@valencia` | 268 | 0 |
| `cs` | 268 | 0 |
| `cy` | 268 | 0 |
| `da` | 268 | 0 |
| `de` | 268 | 0 |
| `el` | 268 | 0 |
| `en_GB` | 0 | 268 |
| `eo` | 268 | 0 |
| `es` | 268 | 0 |
| `et` | 267 | 1 |
| `eu` | 268 | 0 |
| `fa` | 268 | 0 |
| `fi` | 267 | 1 |
| `fr` | 268 | 0 |
| `fy` | 268 | 0 |
| `ga` | 268 | 0 |
| `gl` | 268 | 0 |
| `he` | 268 | 0 |
| `hi` | 268 | 0 |
| `hne` | 3 | 265 |
| `hr` | 268 | 0 |
| `hu` | 267 | 1 |
| `ia` | 3 | 265 |
| `id` | 268 | 0 |
| `is` | 268 | 0 |
| `it` | 268 | 0 |
| `ja` | 268 | 0 |
| `ka` | 268 | 0 |
| `kk` | 268 | 0 |
| `km` | 268 | 0 |
| `ko` | 268 | 0 |
| `lt` | 267 | 1 |
| `lv` | 267 | 1 |
| `mai` | 268 | 0 |
| `mk` | 268 | 0 |
| `mr` | 268 | 0 |
| `ms` | 268 | 0 |
| `nb` | 268 | 0 |
| `nds` | 3 | 265 |
| `ne` | 268 | 0 |
| `nl` | 268 | 0 |
| `nn` | 268 | 0 |
| `oc` | 268 | 0 |
| `pa` | 268 | 0 |
| `pl` | 268 | 0 |
| `pt` | 268 | 0 |
| `pt_BR` | 268 | 0 |
| `ro` | 268 | 0 |
| `ru` | 268 | 0 |
| `se` | 268 | 0 |
| `sk` | 268 | 0 |
| `sl` | 268 | 0 |
| `sq` | 268 | 0 |
| `sv` | 268 | 0 |
| `ta` | 268 | 0 |
| `tg` | 268 | 0 |
| `th` | 268 | 0 |
| `tok` | 1 | 267 |
| `tr` | 268 | 0 |
| `ug` | 266 | 2 |
| `uk` | 268 | 0 |
| `uz` | 268 | 0 |
| `uz@cyrillic` | 258 | 10 |
| `vi` | 268 | 0 |
| `wa` | 3 | 265 |
| `xh` | 268 | 0 |
| `zh_CN` | 268 | 0 |
| `zh_TW` | 267 | 1 |

## Contributing

Edit `linework/translations/<locale>.json`. Keys are the English source messages;
values are their translations. Preserve indexed fields such as `{0}`, `{1}` and
`{2:.2f}`, their format specifiers, and intentional line breaks. Indexed fields may
be reordered when the language requires it. Missing entries are safe and display
English. Add translations using the existing locale code rather than a renamed key.

Run `python3 -m unittest discover -s tests -p test_i18n.py -v` to check locale
resolution, fallback, message keys and formatting. For an isolated application
capture, use `python3 tests/gui/run.py localization --language es`. The Windows
runner accepts the same `--language` option with its normal runtime/prefix options.

Krita source: https://download.kde.org/stable/krita/6.0.3/krita-6.0.3.tar.xz
The JSON catalogs are distributed under the project's GPL-3.0-or-later license.
