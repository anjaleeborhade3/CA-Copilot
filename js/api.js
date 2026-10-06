(function () {
    "use strict";

    const baseUrl = "http://localhost:8001/api";

    async function request(path, options) {
        let response;
        try {
            response = await fetch(baseUrl + path, options);
        } catch (error) {
            throw new Error("Cannot reach the local CA-Copilot backend at http://localhost:8001. Start the backend and try again.");
        }

        if (!response.ok) {
            let detail = "Request failed (" + response.status + ").";
            try {
                const body = await response.json();
                if (typeof body.detail === "string") {
                    detail = body.detail;
                } else if (Array.isArray(body.detail)) {
                    detail = body.detail.map(function (item) {
                        return item.msg;
                    }).join("; ");
                }
            } catch (error) {
                // Keep the HTTP status message when the server did not return JSON.
            }
            throw new Error(detail);
        }

        if (response.status === 204) {
            return null;
        }
        return response.json();
    }

    function query(values) {
        const params = new URLSearchParams();
        Object.entries(values).forEach(function (entry) {
            if (entry[1] !== undefined && entry[1] !== null && entry[1] !== "") {
                params.set(entry[0], entry[1]);
            }
        });
        const suffix = params.toString();
        return suffix ? "?" + suffix : "";
    }

    window.CAApi = {
        request: request,
        query: query,
        get: function (path) {
            return request(path);
        },
        send: function (path, method, body) {
            return request(path, {
                method: method,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
        },
        download: async function (path, filename) {
            const response = await fetch(baseUrl + path);
            if (!response.ok) {
                let detail = "Download failed (" + response.status + ").";
                try {
                    const body = await response.json();
                    if (typeof body.detail === "string") {
                        detail = body.detail;
                    }
                } catch (error) {
                    // Keep the HTTP status message when the server did not return JSON.
                }
                throw new Error(detail);
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(function () {
                URL.revokeObjectURL(url);
            }, 1000);
        }
    };
})();
