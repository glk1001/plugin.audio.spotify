#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
    plugin.audio.spotify
    Spotify Player for Kodi
    Main service entry point
"""

import os
import sys

sys.path.insert(1, os.path.join(os.path.dirname(__file__), "resources", "lib"))

if __name__ == "__main__":
    from main_service import MainService

    MainService()
