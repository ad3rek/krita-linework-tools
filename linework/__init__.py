# SPDX-License-Identifier: GPL-3.0-or-later
from krita import Krita
from .plugin import LineworkExtension
from .tools import install_tools

install_tools()
Krita.instance().addExtension(LineworkExtension(Krita.instance()))
__version__ = '0.1.2'
