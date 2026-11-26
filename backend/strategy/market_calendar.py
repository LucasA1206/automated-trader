"""
NYSE / NASDAQ Market Calendar — Holidays, Weekends & Early Closes
=================================================================
Provides authoritative US equity regular-session hours in Eastern Time (ET):
  - Weekends (Sat/Sun): closed
  - NYSE Holidays (observed): New Year's Day, MLK Jr. Day, Presidents' Day,
    Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day,
    Thanksgiving (4th Thu Nov), Christmas Day
  - Early Closes (09:30–13:00 ET): Day after Thanksgiving, July 3rd (when
    weekday and July 4 is a trading/observed holiday), Christmas Eve (when weekday)
  - Optional IBKR contract-details trading-hours cross-check (fails safe if they disagree).
"""

from datetime import date, datetime, time, timedelta
from typing import Optional
import logging
import pytz

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


def _observed_date(d: date) -> date:
    """Apply NYSE observed-holiday rule (Sat -> Fri, Sun -> Mon)."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth (1-indexed) occurrence of `weekday` (0=Mon..6=Sun) in month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of `weekday` in month."""
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    last = next_first - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm for Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_nyse_holidays(year: int) -> dict[date, str]:
    """Return {date: holiday_name} for NYSE full-day closures in `year`."""
    holidays: dict[date, str] = {}

    # New Year's Day (if Jan 1 is Sat, observed Dec 31 of prior year; handle both)
    nyd = _observed_date(date(year, 1, 1))
    if nyd.year == year:
        holidays[nyd] = "New Year's Day"
    next_nyd = _observed_date(date(year + 1, 1, 1))
    if next_nyd.year == year:
        holidays[next_nyd] = "New Year's Day (Observed)"

    holidays[_nth_weekday_of_month(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    holidays[_nth_weekday_of_month(year, 2, 0, 3)] = "Washington's Birthday"
    holidays[_easter_sunday(year) - timedelta(days=2)] = "Good Friday"
    holidays[_last_weekday_of_month(year, 5, 0)] = "Memorial Day"

    if year >= 2022:
        holidays[_observed_date(date(year, 6, 19))] = "Juneteenth"

    holidays[_observed_date(date(year, 7, 4))] = "Independence Day"
    holidays[_nth_weekday_of_month(year, 9, 0, 1)] = "Labor Day"
    holidays[_nth_weekday_of_month(year, 11, 3, 4)] = "Thanksgiving Day"
    holidays[_observed_date(date(year, 12, 25))] = "Christmas Day"

    return holidays


def get_nyse_early_closes(year: int) -> dict[date, str]:
    """Return {date: reason} for 13:00 ET early-close sessions in `year`."""
    early: dict[date, str] = {}
    holidays = get_nyse_holidays(year)

    # Day after Thanksgiving (Friday)
    thanksgiving = _nth_weekday_of_month(year, 11, 3, 4)
    day_after = thanksgiving + timedelta(days=1)
    if day_after not in holidays:
        early[day_after] = "Day After Thanksgiving (13:00 ET Early Close)"

    # July 3rd (when July 4 is Tue-Fri)
    july4 = date(year, 7, 4)
    if july4.weekday() in (1, 2, 3, 4):
        july3 = date(year, 7, 3)
        if july3.weekday() < 5 and july3 not in holidays:
            early[july3] = "Independence Day Eve (13:00 ET Early Close)"

    # Christmas Eve (when Dec 24 is Mon-Thu)
    dec24 = date(year, 12, 24)
    if dec24.weekday() < 4 and dec24 not in holidays:
        early[dec24] = "Christmas Eve (13:00 ET Early Close)"

    return early


def get_session_info(d: date) -> dict:
    """
    Return session metadata for date `d` (US Eastern):
      is_trading_day, is_holiday, is_weekend, is_early_close,
      holiday_name, open_time, close_time
    """
    if d.weekday() >= 5:
        return {
            "date": d.isoformat(),
            "is_trading_day": False,
            "is_weekend": True,
            "is_holiday": False,
            "is_early_close": False,
            "reason": "Weekend",
            "open_time": None,
            "close_time": None,
        }

    holidays = get_nyse_holidays(d.year)
    if d in holidays:
        return {
            "date": d.isoformat(),
            "is_trading_day": False,
            "is_weekend": False,
            "is_holiday": True,
            "is_early_close": False,
            "reason": f"Market Holiday: {holidays[d]}",
            "open_time": None,
            "close_time": None,
        }

    early = get_nyse_early_closes(d.year)
    if d in early:
        return {
            "date": d.isoformat(),
            "is_trading_day": True,
            "is_weekend": False,
            "is_holiday": False,
            "is_early_close": True,
            "reason": early[d],
            "open_time": time(9, 30),
            "close_time": time(13, 0),
        }

    return {
        "date": d.isoformat(),
        "is_trading_day": True,
        "is_weekend": False,
        "is_holiday": False,
        "is_early_close": False,
        "reason": "Regular Session",
        "open_time": time(9, 30),
        "close_time": time(16, 0),
    }


def is_nyse_trading_day(d: Optional[date] = None) -> bool:
    target = d or datetime.now(ET).date()
    return bool(get_session_info(target)["is_trading_day"])


def is_nyse_market_open(
    now_et: Optional[datetime] = None,
    ibkr_is_open: Optional[bool] = None,
) -> bool:
    """
    Return True if NYSE regular trading session is currently open.
    Respects weekends, holidays, and 13:00 ET early closes.
    If `ibkr_is_open` (from IBKR contract details) is supplied and disagrees
    with the calendar, fails safe and returns False.
    """
    dt = now_et or datetime.now(ET)
    if dt.tzinfo is None:
        dt = ET.localize(dt)
    else:
        dt = dt.astimezone(ET)

    info = get_session_info(dt.date())
    if not info["is_trading_day"]:
        return False

    open_dt = dt.replace(hour=info["open_time"].hour, minute=info["open_time"].minute, second=0, microsecond=0)
    close_dt = dt.replace(hour=info["close_time"].hour, minute=info["close_time"].minute, second=0, microsecond=0)
    cal_open = open_dt <= dt < close_dt

    if ibkr_is_open is not None and bool(ibkr_is_open) != cal_open:
        logger.warning(
            "[MarketCalendar] Calendar (%s) disagrees with IBKR trading hours (%s) — failing safe (closed).",
            cal_open, ibkr_is_open,
        )
        return False

    return cal_open


def seconds_until_next_open(now_et: Optional[datetime] = None) -> float:
    """Seconds until the next NYSE regular session open."""
    dt = now_et or datetime.now(ET)
    if dt.tzinfo is None:
        dt = ET.localize(dt)
    else:
        dt = dt.astimezone(ET)

    if is_nyse_market_open(dt):
        return 0.0

    candidate_date = dt.date()
    for _ in range(14):
        info = get_session_info(candidate_date)
        if info["is_trading_day"]:
            open_dt = ET.localize(datetime.combine(candidate_date, info["open_time"]))
            if open_dt > dt:
                return max(0.0, (open_dt - dt).total_seconds())
        candidate_date += timedelta(days=1)

    return 0.0
