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
