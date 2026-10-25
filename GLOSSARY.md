# Empulse

Activity monitoring for an Emby media server: who watched what, when, and how.

## Time

**Display timezone**:
The single timezone, chosen in settings, in which every date, hour and weekday is shown and grouped.
_Avoid_: server timezone, local time (ambiguous), tz offset

**Local day**:
A calendar date in the display timezone, running from local midnight to local midnight; its length varies across DST changes.
_Avoid_: day bucket, 24 hours

**Period**:
The last N local days, today included, that a statistic or chart covers. "Last 7 days" is today plus the six local days before it.
_Avoid_: time range, window, rolling N×24h, days

**Previous period**:
The period of the same length that ends where a period begins, used for comparison.
_Avoid_: last period, prior window
