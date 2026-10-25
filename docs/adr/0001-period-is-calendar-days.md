# A Period is whole local days, not rolling N×24h

"Last N days" means today plus the N−1 local days before it, starting at local midnight in the display timezone. We chose this over a rolling N×24h window, which leaves a partial oldest day on every daily chart, so that stat cards, charts and the period comparison always cover the same whole days. Local dates, hours and weekdays are computed per row with zoneinfo-backed SQLite functions instead of one fixed UTC offset, so grouping stays correct across DST changes.
