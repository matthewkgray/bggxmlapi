# bgg_api/exceptions.py

class BGGException(Exception):
    """Base exception for all bgg-api errors."""
    pass

class BGGAPIError(BGGException):
    """Raised for errors returned by the BGG API (e.g., invalid user, game not found)."""
    pass

class BGGNetworkError(BGGException):
    """Raised for network-related issues (e.g., connection errors, timeouts)."""
    pass

class BGGNotAuthenticatedError(BGGException):
    """Raised if the attempted operation requires authentication and no token is provided."""
    pass
