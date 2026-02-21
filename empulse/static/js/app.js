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
    document.querySelectorAll(".stat-card[data-bg]").forEach(function(card) {
        var poster = card.querySelector(".stat-card-poster img");
        var fallback = card.querySelector(".poster-fallback");
        var defaultSrc = card.dataset.bg;
        var defaultTitle = fallback ? fallback.textContent : "";

        // Set initial blur bg
        card.style.setProperty("--hover-bg", "url(" + defaultSrc + ")");

        card.querySelectorAll("li[data-img]").forEach(function(li) {
            li.addEventListener("mouseenter", function() {
                var src = li.dataset.img;
                if (poster) poster.src = src;
                if (fallback && li.dataset.title) fallback.textContent = li.dataset.title;
                card.style.setProperty("--hover-bg", "url(" + src + ")");
                card.classList.add("is-hovered");
            });
        });

        card.addEventListener("mouseleave", function() {
            if (poster) poster.src = defaultSrc;
            if (fallback) fallback.textContent = defaultTitle;
            card.style.setProperty("--hover-bg", "url(" + defaultSrc + ")");
            card.classList.remove("is-hovered");
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
        "#52b54b", "#06b6d4", "#a855f7", "#ef4444",
        "#eab308", "#f97316", "#ec4899", "#22d3ee"
    ];

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
                chartDaily = new Chart(dailyEl, {
                    type: "line",
                    data: {
                        labels: data.map(function(d) { return d.date.slice(5); }),
                        datasets: [{
                            label: label,
                            data: data.map(pickValue),
                            borderColor: accent,
                            backgroundColor: accent + "33",
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
                            backgroundColor: COLORS.slice(0, data.length)
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
        getCSS: getCSS
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
