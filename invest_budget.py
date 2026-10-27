"""Bound execution to the existing report window; never submit investment content."""
from datetime import datetime


def plan(run, schedule, stamp):
    clock = schedule['deadline'] if run['stage'] == 'research' else '21:00'
    window = datetime.fromisoformat(run['day']+'T'+clock).replace(tzinfo=stamp.tzinfo)
    seconds = min(1200, int((window-stamp).total_seconds())-30)
    if seconds <= 0:
        return None
    research_seconds = max(0, seconds-300)
    return dict(namespace='olive-investment', run_id=run['id'], stage=run['stage'],
                seconds=seconds, research_seconds=research_seconds,
                started_at=stamp.timestamp(), research_until=stamp.timestamp()+research_seconds,
                expires_at=stamp.timestamp()+seconds, window_ends_at=window.isoformat())


def remaining(contract, stamp):
    return max(0, int(contract['expires_at']-stamp.timestamp()))
