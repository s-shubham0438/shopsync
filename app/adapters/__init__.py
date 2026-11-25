"""Store adapters: one class per store behind a common interface (see base.py).

Import concrete pieces from their modules (`app.adapters.registry`, `app.adapters.runner`, …);
this package init stays import-light so `app.core` can depend on `app.core.stores` freely.
"""
