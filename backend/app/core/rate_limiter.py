"""
Rate limiter global avec slowapi.
Protege les endpoints sensibles (auth, API) contre le brute force.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
