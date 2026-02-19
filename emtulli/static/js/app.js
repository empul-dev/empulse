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

// Set --hover-bg CSS var from data-bg attribute for blur hover effect
function initHoverBackgrounds() {
    document.querySelectorAll("[data-bg]").forEach(function(el) {
        el.style.setProperty("--hover-bg", "url(" + el.dataset.bg + ")");
    });
}

// Run on load and after every HTMX swap
initHoverBackgrounds();
document.body.addEventListener("htmx:afterSwap", initHoverBackgrounds);
