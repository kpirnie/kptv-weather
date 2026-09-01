#!/usr/bin/env python3
"""
Core Package

The rendering primitives: the layer contract, the frame compositor, the tick
scheduler, and the background data refresher.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from .compositor import Compositor
from .datastore import DataStore
from .layer import Layer
from .scheduler import Scheduler

__all__ = ["Compositor", "DataStore", "Layer", "Scheduler"]
