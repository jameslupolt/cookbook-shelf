class ShelfError(Exception):
    """An actionable error safe to display without browser logs or credentials."""

    code = "shelf_error"


class LoginRequired(ShelfError):
    code = "login_required"


class VerificationRequired(ShelfError):
    code = "verification_required"


class LayoutChanged(ShelfError):
    code = "layout_changed"


class ScopeError(ShelfError):
    code = "scope_error"
