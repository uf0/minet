# =============================================================================
# Minet Google Exceptions
# =============================================================================
#
from minet.exceptions import MinetError


class GoogleError(MinetError):
    pass


class GoogleSheetsError(GoogleError):
    pass


class GoogleSheetsInvalidTargetError(GoogleSheetsError):
    pass


class GoogleSheetsInvalidContentTypeError(GoogleSheetsError):
    pass


class GoogleSheetsMissingCookieError(GoogleSheetsError):
    pass
