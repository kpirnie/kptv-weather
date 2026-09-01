#!/usr/bin/env python3
"""
Data Package

Location lookups: the bundled city table used for the regional maps, and ZIP
code resolution.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from .cities import nearby_cities, nearest_city
from .zipcodes import resolve_zip

__all__ = ["nearby_cities", "nearest_city", "resolve_zip"]
