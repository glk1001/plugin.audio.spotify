#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
    plugin.audio.spotify
    Unofficial Spotify client for Kodi
"""

import os
import sys

sys.path.insert(1, os.path.join(os.path.dirname(__file__), "resources", "lib"))
from plugin_content import PluginContent

if __name__ == "__main__":
    PluginContent()
