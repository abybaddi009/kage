"""macOS launch-at-login support.

Uses SMAppService (macOS 13+) when available, falling back to the legacy
SMLoginItemSetEnabled API. Both require the app to be a proper bundle; when
running via ``uv run`` the call may report success but have no effect until
Kage is packaged as an .app.

The functions degrade gracefully (return False) when the ServiceManagement
framework is unavailable.
"""

from __future__ import annotations


def _import_smappservice():
    try:
        from ServiceManagement import SMAppService  # type: ignore

        return SMAppService
    except ImportError:
        return None


def _import_legacy():
    try:
        from ServiceManagement import SMLoginItemSetEnabled  # type: ignore

        return SMLoginItemSetEnabled
    except ImportError:
        return None


def set_launch_at_login(enabled: bool) -> bool:
    """Enable or disable launching Kage at login. Returns success."""
    SMAppService = _import_smappservice()
    if SMAppService is not None:
        try:
            service = SMAppService.mainAppService()
            if enabled:
                err = service.register()
            else:
                err = service.unregister()
            return err is None or err == 0
        except Exception:
            return False
    legacy = _import_legacy()
    if legacy is not None:
        try:
            # Legacy API: identifier + enabled flag. Best-effort; only works
            # for a packaged helper bundle.
            return bool(legacy("ai.kage.Kage", enabled))
        except Exception:
            return False
    return False


def is_launch_at_login() -> bool:
    """True if launch-at-login is currently enabled."""
    SMAppService = _import_smappservice()
    if SMAppService is not None:
        try:
            return SMAppService.mainAppService().status == 1  # SMAppServiceStatusEnabled
        except Exception:
            return False
    return False
