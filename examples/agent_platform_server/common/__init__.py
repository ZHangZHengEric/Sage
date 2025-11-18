from .exceptions import register_exception_handlers as reh
from .middleware import register_middlewares as rmw


def register_exception_handlers(app):
    reh(app)


def register_middlewares(app):
    rmw(app)
