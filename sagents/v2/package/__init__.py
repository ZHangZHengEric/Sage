"""Declarative package loading, composition, plugins and package registry.

Import concrete surfaces from ``package.manifest`` or ``package.composition``.
Keeping this parent package side-effect free prevents composition-root cycles.
"""
