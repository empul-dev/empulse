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
