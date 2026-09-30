"""Key layout of the persisted control state."""

PLANT_STATE = "plant/state"
PLANT_STARTED_AT = "plant/started_at"
PLANT_STOPPED_AT = "plant/stopped_at"
PLANT_MAINTAINED_AT = "plant/maintained_at"

AUDIT_SEQUENCE = "audit/sequence"
AUDIT_EVENT_PREFIX = "audit/event/"
AUDIT_LAST_PREFIX = "audit/last/"

TREND_CLOCK = "trend/clock"
TREND_LIVE_PREFIX = "trend/live/"
TREND_RAW_PREFIX = "trend/raw/"
TREND_UNTRUSTED_COUNT_PREFIX = "trend/untrusted-count/"
TREND_UNTRUSTED_PREFIX = "trend/untrusted/"
TREND_PUBLISHED_PREFIX = "trend/published/"
TREND_CURRENT_PREFIX = "trend/current/"
TREND_CORRECTION_SEQUENCE = "trend/correction-sequence"
TREND_CORRECTION_PREFIX = "trend/correction/"
TREND_WARNING_PREFIX = "trend/warning/"


def audit_event_key(sequence: int) -> str:
    """Key holding the event written at ``sequence``."""
    if sequence < 1:
        raise ValueError("audit sequence starts at one")
    return f"{AUDIT_EVENT_PREFIX}{sequence:06d}"


def audit_last_key(kind: str) -> str:
    """Key holding the sequence of the latest event of ``kind``."""
    return f"{AUDIT_LAST_PREFIX}{kind}"


def trend_live_key(point: str) -> str:
    """Key holding the newest committed live tick of ``point``."""
    return f"{TREND_LIVE_PREFIX}{point}"


def trend_raw_key(point: str, tick: int) -> str:
    """Key holding the raw sample committed for ``point`` at ``tick``."""
    if tick < 1:
        raise ValueError("trend ticks start at one")
    return f"{TREND_RAW_PREFIX}{point}/{tick:09d}"


def trend_untrusted_count_key(point: str) -> str:
    """Key holding the number of untrusted segments recorded for ``point``."""
    return f"{TREND_UNTRUSTED_COUNT_PREFIX}{point}"


def trend_untrusted_key(point: str, sequence: int) -> str:
    """Key holding the untrusted segment recorded at ``sequence`` for ``point``."""
    if sequence < 1:
        raise ValueError("untrusted sequences start at one")
    return f"{TREND_UNTRUSTED_PREFIX}{point}/{sequence:06d}"


def trend_published_prefix(point: str, tick: int) -> str:
    """Prefix under which every published version of a trend point lives."""
    if tick < 1:
        raise ValueError("trend ticks start at one")
    return f"{TREND_PUBLISHED_PREFIX}{point}/{tick:09d}/"


def trend_published_key(point: str, tick: int, version: int) -> str:
    """Key holding one immutable published version of a trend point."""
    if version < 1:
        raise ValueError("trend versions start at one")
    return f"{trend_published_prefix(point, tick)}{version:03d}"


def trend_current_key(point: str, tick: int) -> str:
    """Key holding the version pointer of the effective trend point."""
    if tick < 1:
        raise ValueError("trend ticks start at one")
    return f"{TREND_CURRENT_PREFIX}{point}/{tick:09d}"


def trend_correction_key(sequence: int) -> str:
    """Key holding the correction recorded at ``sequence``."""
    if sequence < 1:
        raise ValueError("correction sequences start at one")
    return f"{TREND_CORRECTION_PREFIX}{sequence:06d}"


def trend_warning_key(point: str, tick: int) -> str:
    """Key holding the warnings raised by the effective trend point."""
    if tick < 1:
        raise ValueError("trend ticks start at one")
    return f"{TREND_WARNING_PREFIX}{point}/{tick:09d}"
