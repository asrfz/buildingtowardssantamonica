from datetime import datetime


def hour_of_day(dt: datetime) -> int:
    return dt.hour


def day_type(dt: datetime) -> str:
    return "weekend" if dt.weekday() >= 5 else "weekday"
