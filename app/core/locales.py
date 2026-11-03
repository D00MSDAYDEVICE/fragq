import gettext
from os import listdir, path

locales = dict()

# Compiled at docker build time by compile_locales.sh; skipped if missing (english only).
if path.isdir("locales/compiled"):
	for locale_name in sorted(listdir("locales/compiled")):
		t = gettext.translation("all", localedir="locales/compiled", languages=[locale_name])
		t.install()
		locales[t.gettext("_lang")] = t.gettext

# Add default translation
t = gettext.NullTranslations()
t.install()
locales["en"] = t.gettext
