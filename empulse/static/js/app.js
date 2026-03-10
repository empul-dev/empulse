// === Display format helpers (reads from window.EMPULSE_DISPLAY) ===
(function() {
    var D = window.EMPULSE_DISPLAY || {};

    function formatDateShort(isoDate) {
        // isoDate is "YYYY-MM-DD" — extract month/day and reformat
        if (!isoDate || isoDate.length < 10) return isoDate || '';
        var m = isoDate.slice(5, 7);
        var d = isoDate.slice(8, 10);
        var fmt = D.date_format || 'YYYY-MM-DD';
        if (fmt === 'DD/MM/YYYY') return d + '/' + m;
        if (fmt === 'MM/DD/YYYY') return m + '/' + d;
        return m + '-' + d;
    }

    function formatHourLabel(hour) {
        if (D.time_format === '12h') {
            if (hour === 0) return '12AM';
            if (hour < 12) return hour + 'AM';
            if (hour === 12) return '12PM';
            return (hour - 12) + 'PM';
        }
        return (hour < 10 ? '0' : '') + hour + ':00';
    }

    function getDowLabels(short) {
        var monday = (D.week_start || 'monday') === 'monday';
        if (short) {
            return monday
                ? ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
                : ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
        }
        return monday
            ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    }

    function getDowOrder() {
        // SQLite %w: 0=Sun, 1=Mon, ..., 6=Sat
        if ((D.week_start || 'monday') === 'monday') {
            return [1, 2, 3, 4, 5, 6, 0];
        }
        return [0, 1, 2, 3, 4, 5, 6];
    }

    window.empulseFormat = {
        formatDateShort: formatDateShort,
        formatHourLabel: formatHourLabel,
        getDowLabels: getDowLabels,
        getDowOrder: getDowOrder
    };
})();

// Browser WebSocket for push updates
(function() {
    let ws;
    let reconnectTimer;

    function connect() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(proto + "//" + location.host + "/ws");

        ws.onmessage = function(e) {
            const msg = JSON.parse(e.data);
            if (msg.type === "refresh" && msg.target) {
                document.body.dispatchEvent(
                    new Event("refresh-" + msg.target)
                );
            }
        };

        ws.onclose = function() {
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = function() {
            ws.close();
        };
    }

    connect();
})();

// Stat card: hover over list items swaps poster + blur background
function initStatCards() {
    function iconSvg(kind) {
        switch (kind) {
            case "Movie":
            case "movie":
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zm0 3h16V6H4v2zm3 0V6H5v2h2zm4 0V6H9v2h2zm4 0V6h-2v2h2zm4 0V6h-2v2h2z"/></svg>';
            case "Episode":
            case "episode":
            case "tv":
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21 17H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h18a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2zM8 21h8v-2H8v2z"/></svg>';
            case "Audio":
            case "audio":
            case "music":
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h6V3h-8z"/></svg>';
            case "browser":
            case "web":
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 4h16a2 2 0 0 1 2 2v3H2V6a2 2 0 0 1 2-2zm-2 7h20v7a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-7zm3 2v5h14v-5H5z"/></svg>';
            case "mobile":
            case "ios":
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm5 18a1.25 1.25 0 1 0 0-2.5A1.25 1.25 0 0 0 12 20z"/></svg>';
            case "desktop":
            case "platform":
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21 3H3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h7l-2 3v1h8v-1l-2-3h7a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z"/></svg>';
            default:
                return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H8V4h12v12z"/></svg>';
        }
    }

    function iconKind(raw) {
        var v = (raw || "").toLowerCase();
        if (v.indexOf("movie") !== -1) return "movie";
        if (v.indexOf("episode") !== -1 || v.indexOf("tv") !== -1 || v.indexOf("show") !== -1) return "tv";
        if (v.indexOf("audio") !== -1 || v.indexOf("music") !== -1) return "music";
        if (v.indexOf("ios") !== -1 || v.indexOf("iphone") !== -1 || v.indexOf("ipad") !== -1 || v.indexOf("android") !== -1) return "mobile";
        if (v.indexOf("web") !== -1 || v.indexOf("chrome") !== -1 || v.indexOf("firefox") !== -1 || v.indexOf("safari") !== -1 || v.indexOf("edge") !== -1) return "browser";
        if (v.indexOf("lg") !== -1 || v.indexOf("samsung") !== -1 || v.indexOf("roku") !== -1 || v.indexOf("apple tv") !== -1 || v.indexOf("macos") !== -1 || v.indexOf("windows") !== -1 || v.indexOf("desktop") !== -1) return "desktop";
        return v || "platform";
    }

    document.querySelectorAll(".stat-card").forEach(function(card) {
        var posterWrap = card.querySelector(".stat-card-poster");
        var poster = posterWrap ? posterWrap.querySelector("img") : null;
        var fallback = posterWrap ? posterWrap.querySelector(".poster-fallback") : null;
        var defaultSrc = poster ? poster.getAttribute("src") : "";
        var defaultTitle = fallback ? fallback.textContent : "";
        var defaultBg = card.dataset.bg || "";
        var defaultIcon = posterWrap && posterWrap.classList.contains("stat-card-icon")
            ? posterWrap.innerHTML
            : "";

        if (defaultBg) {
            card.style.setProperty("--hover-bg", "url(" + defaultBg + ")");
        }

        card.querySelectorAll("li").forEach(function(li) {
            li.addEventListener("mouseenter", function() {
                if (li.dataset.img && poster) {
                    poster.src = li.dataset.img;
                    if (fallback && li.dataset.title) fallback.textContent = li.dataset.title;
                    if (defaultBg) {
                        card.style.setProperty("--hover-bg", "url(" + li.dataset.img + ")");
                        card.classList.add("is-hovered");
                    }
                }
                if (li.dataset.icon && posterWrap && posterWrap.classList.contains("stat-card-icon")) {
                    posterWrap.innerHTML = iconSvg(iconKind(li.dataset.icon));
                }
            });
        });

        card.querySelectorAll("li[data-href]").forEach(function(li) {
            li.style.cursor = "pointer";
            li.addEventListener("click", function() {
                window.location.href = li.dataset.href;
            });
        });

        card.addEventListener("mouseleave", function() {
            if (poster && defaultSrc) poster.src = defaultSrc;
            if (fallback) fallback.textContent = defaultTitle;
            if (defaultBg) {
                card.style.setProperty("--hover-bg", "url(" + defaultBg + ")");
                card.classList.remove("is-hovered");
            }
            if (posterWrap && posterWrap.classList.contains("stat-card-icon")) {
                posterWrap.innerHTML = defaultIcon;
            }
        });
    });

    // Click navigation for cards WITHOUT data-bg (users, libraries, platforms)
    document.querySelectorAll(".stat-card:not([data-bg]) li[data-href]").forEach(function(li) {
        li.style.cursor = "pointer";
        li.addEventListener("click", function() {
            window.location.href = li.dataset.href;
        });
    });

    // Now-playing cards: just set the blur bg
    document.querySelectorAll(".now-playing-card[data-bg]").forEach(function(card) {
        card.style.setProperty("--hover-bg", "url(" + card.dataset.bg + ")");
    });
}

initStatCards();
document.body.addEventListener("htmx:afterSwap", initStatCards);

// Prevent now-playing cards from re-animating on HTMX poll refreshes
(function() {
    var np = document.getElementById("now-playing");
    if (!np) return;
    np.addEventListener("htmx:afterSettle", function() {
        np.classList.add("no-entrance");
    });
})();

// HTMX 401 handling for auth
document.body.addEventListener("htmx:responseError", function(evt) {
    if (evt.detail.xhr && evt.detail.xhr.status === 401) {
        window.location.href = "/login";
    }
});

// === Chart.js ===
(function() {
    var chartDaily = null, chartType = null, chartPlatform = null;

    var COLORS = [
        "#52b54b", "#4db6ac", "#7e57c2", "#d4a76a",
        "#26a69a", "#e57373", "#5c6bc0", "#8bc34a"
    ];

    var TYPE_COLORS = {
        Movie:   "#52b54b",
        Episode: "#4db6ac",
        Audio:   "#7e57c2",
        Other:   "#78909c"
    };

    function getCSS(prop) {
        return getComputedStyle(document.documentElement).getPropertyValue(prop).trim();
    }

    function setupDefaults() {
        var textMuted = getCSS("--text-muted") || "#666";
        var border = getCSS("--border") || "#2a2a2a";
        Chart.defaults.color = textMuted;
        Chart.defaults.borderColor = border;
        Chart.defaults.font.family = "'Source Sans 3', system-ui, sans-serif";
        Chart.defaults.font.size = 11;
        Chart.defaults.plugins.legend.display = false;
        // Hide hard axis border lines — grid lines are enough
        Chart.defaults.scale = Chart.defaults.scale || {};
        Chart.defaults.scale.border = { display: false };
    }

    function getDays() {
        var input = document.getElementById("days-input");
        return input ? (parseInt(input.value) || 30) : 30;
    }

    function getMetric() {
        var active = document.querySelector("#metric-toggle .toggle-btn.active");
        return active ? (active.dataset.value || "plays") : "plays";
    }

    function isDuration() { return getMetric() === "duration"; }

    function toHours(seconds) { return Math.round((seconds || 0) / 360) / 10; }

    function pickValue(d) {
        return isDuration() ? toHours(d.total_duration) : d.plays;
    }

    function metricLabel() { return isDuration() ? "Hours" : "Plays"; }

    function destroyChart(chart) {
        if (chart) chart.destroy();
        return null;
    }

    function loadCharts() {
        var dailyEl = document.getElementById("chart-daily");
        var typeEl = document.getElementById("chart-type");
        var platformEl = document.getElementById("chart-platform");
        if (!dailyEl) return; // not on dashboard

        setupDefaults();
        var days = getDays();
        var accent = getCSS("--accent") || "#52b54b";
        var label = metricLabel();

        // Daily plays
        fetch("/api/charts/daily-plays?days=" + days)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                chartDaily = destroyChart(chartDaily);
                var ctx = dailyEl.getContext("2d");
                var grad = ctx.createLinearGradient(0, 0, 0, dailyEl.parentElement.clientHeight || 200);
                grad.addColorStop(0, "rgba(82, 181, 75, 0.7)");
                grad.addColorStop(1, "rgba(82, 181, 75, 0.05)");
                chartDaily = new Chart(dailyEl, {
                    type: "line",
                    data: {
                        labels: data.map(function(d) { return window.empulseFormat.formatDateShort(d.date); }),
                        datasets: [{
                            label: label,
                            data: data.map(pickValue),
                            borderColor: accent,
                            backgroundColor: grad,
                            fill: true,
                            tension: 0.3,
                            pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            y: { beginAtZero: true, ticks: { precision: isDuration() ? 1 : 0 } }
                        }
                    }
                });
            });

        // Plays by type
        fetch("/api/charts/plays-by-type?days=" + days)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                chartType = destroyChart(chartType);
                chartType = new Chart(typeEl, {
                    type: "doughnut",
                    data: {
                        labels: data.map(function(d) { return d.item_type; }),
                        datasets: [{
                            data: data.map(pickValue),
                            backgroundColor: data.map(function(d) {
                                return TYPE_COLORS[d.item_type] || COLORS[0];
                            })
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: true, position: "right", labels: { boxWidth: 12 } } }
                    }
                });
            });

        // Plays by platform
        fetch("/api/charts/plays-by-platform?days=" + days)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                chartPlatform = destroyChart(chartPlatform);
                chartPlatform = new Chart(platformEl, {
                    type: "bar",
                    data: {
                        labels: data.map(function(d) { return d.client; }),
                        datasets: [{
                            label: label,
                            data: data.map(pickValue),
                            backgroundColor: COLORS.slice(0, data.length)
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        indexAxis: "y",
                        scales: {
                            x: { beginAtZero: true, ticks: { precision: isDuration() ? 1 : 0 } }
                        }
                    }
                });
            });
    }

    // Expose for user/library pages
    window.empulseCharts = {
        COLORS: COLORS,
        setupDefaults: setupDefaults,
        destroyChart: destroyChart,
        getCSS: getCSS,
        reload: loadCharts
    };

    // Load charts when stats-cards swaps (initial load, days change, push update).
    // Also load once on DOMContentLoaded for pages without stats-cards (dashboard
    // always has stats-cards which triggers afterSwap on its hx-trigger="load").
    var chartsLoaded = false;
    document.body.addEventListener("htmx:afterSwap", function(e) {
        if (e.detail.target && e.detail.target.id === "stats-cards") {
            chartsLoaded = true;
            loadCharts();
        }
    });

    // Fallback: if no afterSwap fires within 2s (e.g. stats-cards not on page),
    // load charts once. On dashboard this won't double-fire because chartsLoaded guards it.
    setTimeout(function() {
        if (!chartsLoaded) loadCharts();
    }, 100);
})();

// Close modal via delegated click (dynamically loaded partials)
document.addEventListener('click', function(e) {
    if (e.target.closest('.modal-close') && typeof closeModal === 'function') {
        closeModal();
    }
});

// Close nav user dropdown when clicking outside
document.addEventListener('click', function(e) {
    var navUser = document.querySelector('.nav-user.open');
    if (navUser && !navUser.contains(e.target)) {
        navUser.classList.remove('open');
    }
});

// Theme toggle with sweep animation (View Transitions API)
function toggleTheme() {
    var html = document.documentElement;
    var current = html.getAttribute('data-theme');
    var next = current === 'light' ? 'dark' : 'light';

    // Get button position for sweep origin
    var btn = document.querySelector('.theme-toggle');
    var rect = btn ? btn.getBoundingClientRect() : { left: window.innerWidth - 48, top: 24, width: 24, height: 24 };
    var x = rect.left + rect.width / 2;
    var y = rect.top + rect.height / 2;
    html.style.setProperty('--sweep-x', x + 'px');
    html.style.setProperty('--sweep-y', y + 'px');

    function applyTheme() {
        html.setAttribute('data-theme', next);
        localStorage.setItem('empulse-theme', next);
        // Re-render charts so grid/text colors match new theme
        if (window.empulseCharts && window.empulseCharts.reload) {
            window.empulseCharts.reload();
        }
    }

    if (document.startViewTransition) {
        document.startViewTransition(applyTheme);
    } else {
        applyTheme();
    }
}
// Restore theme preference (localStorage → system preference → dark)
(function() {
    var saved = localStorage.getItem('empulse-theme');
    var theme = saved || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    document.documentElement.setAttribute('data-theme', theme);
})();

// "Added X ago" overlay for recently-added posters
(function() {
    function timeAgo(iso) {
        var diff = (Date.now() - new Date(iso).getTime()) / 1000;
        if (diff < 60) return 'Added just now';
        var m = Math.floor(diff / 60);
        if (m < 60) return 'Added ' + m + (m === 1 ? ' minute' : ' minutes') + ' ago';
        var h = Math.floor(m / 60);
        if (h < 24) return 'Added ' + h + (h === 1 ? ' hour' : ' hours') + ' ago';
        var d = Math.floor(h / 24);
        return 'Added ' + d + (d === 1 ? ' day' : ' days') + ' ago';
    }

    function updateAll() {
        document.querySelectorAll('.recently-added-ago[data-added]').forEach(function(el) {
            el.textContent = timeAgo(el.dataset.added);
        });
    }

    updateAll();
    document.body.addEventListener('htmx:afterSwap', updateAll);
    setInterval(updateAll, 60000);
})();

// --- Session kill (event delegation) ---
document.addEventListener('click', function(e) {
    var btn = e.target.closest('.stop-session-btn');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    var sessionKey = btn.dataset.sessionKey;
    if (!sessionKey) return;
    if (!confirm('Stop this stream?')) return;
    btn.disabled = true;
    btn.style.opacity = '0.4';
    fetch('/api/sessions/' + encodeURIComponent(sessionKey) + '/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
    }).then(function(r) {
        if (r.ok) {
            setTimeout(function() {
                document.body.dispatchEvent(new Event('refresh-now-playing'));
            }, 1500);
        } else {
            btn.disabled = false;
            btn.style.opacity = '';
            r.json().then(function(data) {
                alert(data.error || 'Failed to stop session');
            }).catch(function() {
                alert('Failed to stop session (status ' + r.status + ')');
            });
        }
    }).catch(function(err) {
        btn.disabled = false;
        btn.style.opacity = '';
        alert('Network error — could not stop session');
    });
});
