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
        var defaultSrc = card.dataset.bg;

        // Set initial blur bg
        card.style.setProperty("--hover-bg", "url(" + defaultSrc + ")");

        card.querySelectorAll("li[data-img]").forEach(function(li) {
            li.addEventListener("mouseenter", function() {
                var src = li.dataset.img;
                if (poster) poster.src = src;
                card.style.setProperty("--hover-bg", "url(" + src + ")");
                card.classList.add("is-hovered");
            });
        });

        card.addEventListener("mouseleave", function() {
            if (poster) poster.src = defaultSrc;
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
        "#c8a438", "#22c55e", "#eab308", "#ef4444",
        "#a855f7", "#06b6d4", "#f97316", "#ec4899"
    ];

    function getCSS(prop) {
        return getComputedStyle(document.documentElement).getPropertyValue(prop).trim();
    }

    function setupDefaults() {
        var textMuted = getCSS("--text-muted") || "#6b7280";
        var border = getCSS("--border") || "#2a3550";
        Chart.defaults.color = textMuted;
        Chart.defaults.borderColor = border;
        Chart.defaults.font.family = "system-ui, sans-serif";
        Chart.defaults.font.size = 11;
        Chart.defaults.plugins.legend.display = false;
    }

    function getDays() {
        var input = document.getElementById("days-input");
        return input ? (parseInt(input.value) || 30) : 30;
    }

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
        var accent = getCSS("--accent") || "#c8a438";

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
                            label: "Plays",
                            data: data.map(function(d) { return d.plays; }),
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
                            y: { beginAtZero: true, ticks: { precision: 0 } }
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
                            data: data.map(function(d) { return d.plays; }),
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
                            label: "Plays",
                            data: data.map(function(d) { return d.plays; }),
                            backgroundColor: COLORS.slice(0, data.length)
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        indexAxis: "y",
                        scales: {
                            x: { beginAtZero: true, ticks: { precision: 0 } }
                        }
                    }
                });
            });
    }

    // Expose for user/library pages
    window.emtulliCharts = {
        COLORS: COLORS,
        setupDefaults: setupDefaults,
        destroyChart: destroyChart,
        getCSS: getCSS
    };

    // Load on page load
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", loadCharts);
    } else {
        loadCharts();
    }

    // Reload on HTMX swap (stats-cards swap triggers after days-input change or push update)
    document.body.addEventListener("htmx:afterSwap", function(e) {
        if (e.detail.target && e.detail.target.id === "stats-cards") {
            loadCharts();
        }
    });
})();
