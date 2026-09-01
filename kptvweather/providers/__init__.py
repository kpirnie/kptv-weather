#!/usr/bin/env python3
"""
Providers Package

The upstream data sources: Open-Meteo for the forecast and geocoding, the
National Weather Service for active alerts. Neither needs an API key.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from .nws import NWSAlertClient
from .openmeteo import OpenMeteoClient, WeatherError, geocode

__all__ = ["NWSAlertClient", "OpenMeteoClient", "WeatherError", "geocode"]
