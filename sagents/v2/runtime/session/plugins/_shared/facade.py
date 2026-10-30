"""Attribute forwarding shared by composed SessionStore facades."""

from typing import Any


_ABSENT = object()
_FACADE_STATE = frozenset({"_coordinator", "_originals", "__dict__", "__class__"})


class CoordinatorFacade:
    """Forward attribute reads, writes and deletes to ``self._coordinator``.

    Overrides land on the coordinator because its own methods must observe
    them. They are also recorded in the facade's ``__dict__`` so tools that
    patch and undo through ``vars(obj)`` see ordinary instance semantics:
    deleting an override restores the coordinator value it first replaced.
    Reads of overridden names still resolve on the coordinator.
    """

    _coordinator: Any

    def __getattribute__(self, name: str) -> Any:
        if name not in _FACADE_STATE:
            own = object.__getattribute__(self, "__dict__")
            if name in own:
                return getattr(own["_coordinator"], name)
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        if name == "_coordinator":
            raise AttributeError(name)
        return getattr(self._coordinator, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_coordinator":
            object.__setattr__(self, name, value)
            return
        coordinator = self._coordinator
        originals = self.__dict__.setdefault("_originals", {})
        originals.setdefault(name, vars(coordinator).get(name, _ABSENT))
        setattr(coordinator, name, value)
        self.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        if name == "_coordinator":
            object.__delattr__(self, name)
            return
        coordinator = self._coordinator
        originals = self.__dict__.get("_originals", {})
        if name not in originals:
            delattr(coordinator, name)
            return
        del self.__dict__[name]
        original = originals.pop(name)
        if original is _ABSENT:
            vars(coordinator).pop(name, None)
        else:
            setattr(coordinator, name, original)
