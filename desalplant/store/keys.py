"""Key layout of the persisted control state."""

PLANT_STATE = "plant/state"
PLANT_STARTED_AT = "plant/started_at"
PLANT_STOPPED_AT = "plant/stopped_at"
PLANT_MAINTAINED_AT = "plant/maintained_at"

AUDIT_SEQUENCE = "audit/sequence"
AUDIT_EVENT_PREFIX = "audit/event/"
AUDIT_LAST_PREFIX = "audit/last/"

TREND_POINT_PREFIX = "trend/point/"
TREND_STATE_PREFIX = "trend/state/"
TREND_RAW_PREFIX = "trend/raw/"
TREND_PUBLISHED_PREFIX = "trend/published/"
TREND_CORRECTION_PREFIX = "trend/correction/"
TREND_FAILURE_PREFIX = "trend/failure/"


def audit_event_key(sequence: int) -> str:
    """Key holding the event written at ``sequence``."""
    if sequence < 1:
        raise ValueError("audit sequence starts at one")
    return f"{AUDIT_EVENT_PREFIX}{sequence:06d}"


def audit_last_key(kind: str) -> str:
    """Key holding the sequence of the latest event of ``kind``."""
    return f"{AUDIT_LAST_PREFIX}{kind}"


def trend_point_key(point_id: str) -> str:
    """Key holding the configuration of a trend point."""
    return f"{TREND_POINT_PREFIX}{point_id}"


def trend_state_key(point_id: str) -> str:
    """Key holding the ordered-series state of a trend point."""
    return f"{TREND_STATE_PREFIX}{point_id}"


def trend_raw_key(point_id: str, slot: int) -> str:
    """Key holding the immutable raw reading for a slot."""
    return f"{TREND_RAW_PREFIX}{point_id}/{slot:08d}"


def trend_published_key(point_id: str, slot: int) -> str:
    """Key holding the immutable published trend for a slot."""
    return f"{TREND_PUBLISHED_PREFIX}{point_id}/{slot:08d}"


def trend_correction_key(point_id: str, slot: int) -> str:
    """Key holding the append-only correction for a slot."""
    return f"{TREND_CORRECTION_PREFIX}{point_id}/{slot:08d}"


def trend_failure_key(point_id: str, slot: int) -> str:
    """Key holding the partial-failure record for a slot."""
    return f"{TREND_FAILURE_PREFIX}{point_id}/{slot:08d}"
