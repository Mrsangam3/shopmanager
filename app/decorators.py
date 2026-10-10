from functools import wraps
from flask import abort, current_app
from flask_login import current_user


def roles_required(*roles):
    """Allow only logged-in users whose role is in `roles`."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()  # redirect to login
            if not current_user.has_role(*roles):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator