"""Tool plugin implementations selected through ExtensionRegistry.

The initializer stays side-effect free because individual Tool plugins may
depend on the public :mod:`sagents.v2.tool` contracts while that facade is
still importing.
"""
