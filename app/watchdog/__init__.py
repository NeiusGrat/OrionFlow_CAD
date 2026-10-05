"""The watchdog: one place where every verification engine is reachable.

The engines stay standalone packages (``interface_check``, ``drawcheck``,
``robocheck``, ``embodiment``); this package only connects them to the main
API — shared sign-in, per-user isolation, and one status endpoint.
"""
