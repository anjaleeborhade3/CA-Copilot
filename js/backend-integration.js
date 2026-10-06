(function () {
    "use strict";

    const api = window.CAApi;
    const todayFormat = new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, function (character) {
            return {
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"
            }[character];
        });
    }

    function displayError(error) {
        let notice = document.getElementById("backendNotice");
        if (!notice) {
            notice = document.createElement("div");
            notice.id = "backendNotice";
            notice.setAttribute("role", "alert");
            notice.style.cssText = "margin:12px 0;padding:12px 16px;border:1px solid #f0b6ae;border-radius:8px;background:#fff4f2;color:#8c2e20;";
            const main = document.querySelector("main");
            (main || document.body).prepend(notice);
        }
        notice.textContent = "Backend: " + error.message;
    }

    function clearError() {
        const notice = document.getElementById("backendNotice");
        if (notice) notice.remove();
    }

    async function run(action) {
        try {
            const result = await action();
            clearError();
            return result;
        } catch (error) {
            displayError(error);
            return null;
        }
    }

    function actionError(error) {
        alert(error.message);
    }

    function formatAmount(value) {
        const absolute = Math.abs(Number(value) || 0);
        return (Number(value) < 0 ? "-₹" : "₹") + new Intl.NumberFormat("en-IN", {
            maximumFractionDigits: 0
        }).format(absolute);
    }

    function setSelectOptions(select, items, selectedValue, placeholder) {
        if (!select) return;
        select.replaceChildren();
        if (placeholder) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent = placeholder;
            select.appendChild(option);
        }
        items.forEach(function (item) {
            const option = document.createElement("option");
            option.value = item.id;
            option.textContent = item.name;
            select.appendChild(option);
        });
        if (selectedValue && items.some(function (item) { return item.id === selectedValue; })) {
            select.value = selectedValue;
        }
    }

    async function getClients(search, risk) {
        return api.get("/clients" + api.query({ search: search || "", risk: risk || "all" }));
    }

    function initClients() {
        const table = document.querySelector(".client-table");
        if (!table) return;
        let activeRisk = "all";

        async function load() {
            const query = document.getElementById("clientSearch")?.value || "";
            const response = await getClients(query, activeRisk);
            if (!response) return;
            const oldRows = table.querySelectorAll(".client-row:not(.client-header)");
            oldRows.forEach(function (row) { row.remove(); });
            response.items.forEach(function (client) {
                const row = document.createElement("div");
                row.className = "client-row";
                const initials = client.name.trim().split(/\s+/).slice(0, 2)
                    .map(function (part) { return part[0]; }).join("").toUpperCase();
                row.innerHTML = `
                    <div class="client-name">
                        <div class="client-avatar">${escapeHtml(initials)}</div>
                        <div><h3>${escapeHtml(client.name)}</h3><p>Client ID: ${escapeHtml(client.id)}</p></div>
                    </div>
                    <span>${escapeHtml(client.industry)}</span>
                    <span>${client.documents}</span>
                    <span class="client-risk ${escapeHtml(client.risk.toLowerCase())}">${escapeHtml(client.risk)}</span>
                    <span>${escapeHtml(client.last_review)}</span>
                    <button type="button" class="client-action" data-client-id="${escapeHtml(client.id)}">View</button>`;
                table.appendChild(row);
            });
            const visibleCount = response.count;
            const empty = document.getElementById("clientEmpty");
            if (empty) empty.style.display = visibleCount ? "none" : "block";
            const highRisk = await getClients("", "High");
            const highCount = document.getElementById("highRiskClientCount");
            if (highRisk && highCount) highCount.textContent = highRisk.count;
            const allClients = await getClients("", "all");
            const totalCount = document.getElementById("totalClients");
            if (allClients && totalCount) totalCount.textContent = allClients.count;
            const documents = await api.get("/documents");
            const anomalies = await api.get("/anomalies?status=Open");
            document.querySelectorAll(".dashboard-stats .dashboard-stat").forEach(function (card) {
                const label = card.querySelector("p")?.textContent.toLowerCase() || "";
                const value = card.querySelector("h2");
                if (!value) return;
                if (label.includes("documents")) value.textContent = documents.count;
                if (label.includes("needs review")) value.textContent = anomalies.count;
            });
        }

        window.applyClientFilter = function () { void run(load); };
        window.filterClients = function (risk) {
            activeRisk = risk === "all" ? "all" : risk[0].toUpperCase() + risk.slice(1).toLowerCase();
            void run(load);
            const menu = document.getElementById("filterMenu");
            if (menu) menu.style.display = "none";
        };

        table.addEventListener("click", async function (event) {
            const button = event.target.closest("[data-client-id]");
            if (!button) return;
            const client = await run(function () {
                return api.get("/clients/" + encodeURIComponent(button.dataset.clientId));
            });
            if (client) {
                window.showClient(client.name, client.id, client.industry, String(client.documents), client.risk, client.last_review);
            }
        });

        const form = document.getElementById("addClientForm");
        form?.addEventListener("submit", async function (event) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const name = document.getElementById("newClientName").value.trim();
            const industry = document.getElementById("newBusinessType").value.trim();
            const risk = document.getElementById("newRiskLevel").value;
            try {
                const client = await api.send("/clients", "POST", { name: name, industry: industry, risk: risk });
                form.reset();
                window.closeAddClient();
                await load();
                alert(client.name + " was saved to the local CA-Copilot database as " + client.id + ".");
            } catch (error) {
                actionError(error);
            }
        }, true);
        void run(load);
    }

    function initDocuments() {
        const table = document.querySelector(".document-table");
        if (!table) return;
        let activeStatus = "all";
        const search = document.getElementById("documentSearch");

        async function load() {
            const response = await api.get("/documents" + api.query({
                status: activeStatus,
                search: search?.value || ""
            }));
            const oldRows = table.querySelectorAll(".document-item");
            oldRows.forEach(function (row) { row.remove(); });
            response.items.forEach(function (documentRecord) {
                const row = document.createElement("div");
                row.className = "document-row document-item";
                row.dataset.status = documentRecord.status.toLowerCase();
                row.dataset.search = [documentRecord.name, documentRecord.client, documentRecord.document_type, documentRecord.status].join(" ").toLowerCase();
                const size = documentRecord.file_size ? (documentRecord.file_size / (1024 * 1024)).toFixed(1) + " MB" : "Sample record";
                row.innerHTML = `
                    <div class="document-name"><div class="document-icon">📄</div><div><h3>${escapeHtml(documentRecord.name)}</h3><p>${escapeHtml(size)}</p></div></div>
                    <span>${escapeHtml(documentRecord.client)}</span>
                    <span>${escapeHtml(documentRecord.document_type)}</span>
                    <span class="document-status ${escapeHtml(documentRecord.status.toLowerCase())}">${escapeHtml(documentRecord.status)}</span>
                    <span>${escapeHtml(documentRecord.upload_date)}</span>
                    <div class="document-actions">
                        <button type="button" class="document-action" data-document-view="${documentRecord.id}">View</button>
                        <button type="button" class="document-action" aria-label="Download ${escapeHtml(documentRecord.name)}" data-document-download="${documentRecord.id}" data-document-name="${escapeHtml(documentRecord.name)}">↓</button>
                    </div>`;
                table.appendChild(row);
            });
            const count = document.getElementById("totalDocuments");
            const allDocuments = await api.get("/documents");
            if (count) count.textContent = allDocuments.count;
            for (const entry of [
                ["pendingDocuments", "Pending"],
                ["flaggedDocuments", "Flagged"],
                ["reviewedDocuments", "Reviewed"]
            ]) {
                const result = await api.get("/documents" + api.query({ status: entry[1] }));
                const element = document.getElementById(entry[0]);
                if (element) element.textContent = result.count;
            }
            const empty = document.getElementById("noDocuments");
            if (empty) empty.style.display = response.count ? "none" : "block";
            const documentStats = await api.get("/documents");
            const cards = document.querySelectorAll(".dashboard-stats .dashboard-stat");
            cards.forEach(function (card) {
                const label = card.querySelector("p")?.textContent.toLowerCase() || "";
                const value = card.querySelector("h2");
                if (!value) return;
                if (label.includes("total documents")) value.textContent = documentStats.count;
                if (label.includes("pending")) value.textContent = documentStats.items.filter(function (item) { return item.status === "Pending"; }).length;
                if (label.includes("flagged")) value.textContent = documentStats.items.filter(function (item) { return item.status === "Flagged"; }).length;
                if (label.includes("reviewed")) value.textContent = documentStats.items.filter(function (item) { return item.status === "Reviewed"; }).length;
            });
        }

        window.filterDocuments = function (status) {
            activeStatus = status.toLowerCase();
            void run(load);
            const menu = document.getElementById("documentFilterMenu");
            if (menu) menu.style.display = "none";
        };
        window.searchDocuments = function () { void run(load); };

        table.addEventListener("click", async function (event) {
            const view = event.target.closest("[data-document-view]");
            const download = event.target.closest("[data-document-download]");
            try {
                if (view) {
                    const record = await api.get("/documents/" + view.dataset.documentView);
                    window.viewDocument(record.name, record.client, record.document_type, record.status, record.upload_date);
                } else if (download) {
                    await api.download("/documents/" + download.dataset.documentDownload + "/download", download.dataset.documentName);
                }
            } catch (error) {
                actionError(error);
            }
        });

        getClients("", "all").then(function (response) {
            if (response) setSelectOptions(document.getElementById("uploadClient"), response.items, "", "Select Client");
        }).catch(displayError);

        const form = document.getElementById("uploadDocumentForm");
        form?.addEventListener("submit", async function (event) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const clientId = document.getElementById("uploadClient").value;
            const file = document.getElementById("documentFile").files[0];
            if (!file) {
                alert("Choose a document file before uploading.");
                return;
            }
            const body = new FormData();
            body.append("client_id", clientId);
            body.append("name", document.getElementById("uploadDocumentName").value.trim());
            body.append("document_type", document.getElementById("uploadDocumentType").value);
            body.append("financial_year", document.getElementById("financialYear").value);
            body.append("file", file);
            try {
                const result = await api.request("/documents", { method: "POST", body: body });
                form.reset();
                window.closeUploadModal();
                await load();
                alert(result.name + " was uploaded to local storage. No document analysis was performed.");
            } catch (error) {
                actionError(error);
            }
        }, true);
        void run(load);

        const params = new URLSearchParams(window.location.search);
        if (params.get("open") === "upload") window.openUploadModal();
    }

    function initReconciliation() {
        const table = document.querySelector(".reconciliation-table");
        if (!table) return;
        let activeStatus = "all";
        const search = document.getElementById("reconciliationSearch");

        async function load() {
            const response = await api.get("/transactions" + api.query({
                status: activeStatus,
                search: search?.value || ""
            }));
            table.querySelectorAll(".transaction-item").forEach(function (row) { row.remove(); });
            response.items.forEach(function (transaction) {
                const row = document.createElement("div");
                const statusClass = transaction.status.toLowerCase();
                row.className = "reconciliation-row transaction-item";
                row.dataset.status = statusClass;
                row.dataset.search = [transaction.id, transaction.client].join(" ").toLowerCase();
                row.innerHTML = `
                    <span class="transaction-id">${escapeHtml(transaction.id)}</span>
                    <span class="transaction-client">${escapeHtml(transaction.client)}</span>
                    <span class="amount">${formatAmount(transaction.bank_amount)}</span>
                    <span class="amount">${formatAmount(transaction.book_amount)}</span>
                    <span class="${Number(transaction.difference) ? "difference" : ""}">${formatAmount(transaction.difference)}</span>
                    <span class="reconciliation-status ${statusClass}">${escapeHtml(transaction.status)}</span>
                    <div class="reconciliation-actions">
                        <button type="button" class="reconciliation-action" data-transaction-view="${escapeHtml(transaction.id)}">View</button>
                        ${transaction.status === "Matched" ? "" : `<button type="button" class="reconciliation-action reconcile-btn" data-transaction-reconcile="${escapeHtml(transaction.id)}">Reconcile</button>`}
                    </div>`;
                table.appendChild(row);
            });
            const allTransactions = await api.get("/transactions");
            for (const entry of [
                ["totalTransactions", "all"],
                ["matchedTransactions", "Matched"],
                ["unmatchedTransactions", "Unmatched"],
                ["exceptionTransactions", "Exception"]
            ]) {
                const result = entry[1] === "all" ? allTransactions : await api.get("/transactions" + api.query({ status: entry[1] }));
                const element = document.getElementById(entry[0]);
                if (element) element.textContent = result.count;
            }
            const empty = document.getElementById("noTransactions");
            if (empty) empty.style.display = response.count ? "none" : "block";
            document.querySelectorAll(".dashboard-stats .dashboard-stat").forEach(function (card) {
                const label = card.querySelector("p")?.textContent.toLowerCase() || "";
                const value = card.querySelector("h2");
                if (!value) return;
                if (label.includes("total transactions")) value.textContent = allTransactions.count;
            });
        }

        window.filterTransactions = function (status) {
            activeStatus = status.toLowerCase();
            void run(load);
            const menu = document.getElementById("reconciliationFilterMenu");
            if (menu) menu.style.display = "none";
        };
        window.searchTransactions = function () { void run(load); };

        table.addEventListener("click", async function (event) {
            const view = event.target.closest("[data-transaction-view]");
            const reconcile = event.target.closest("[data-transaction-reconcile]");
            try {
                if (view) {
                    const transaction = await api.get("/transactions/" + encodeURIComponent(view.dataset.transactionView));
                    window.viewTransaction(
                        transaction.id, transaction.client, formatAmount(transaction.bank_amount),
                        formatAmount(transaction.book_amount), formatAmount(transaction.difference), transaction.status
                    );
                } else if (reconcile) {
                    const result = await api.send("/transactions/" + encodeURIComponent(reconcile.dataset.transactionReconcile), "PATCH", { status: "Matched" });
                    await load();
                    alert(result.id + " was updated to Matched in the local database.");
                }
            } catch (error) {
                actionError(error);
            }
        });

        getClients("", "all").then(function (response) {
            if (response) setSelectOptions(document.getElementById("statementClient"), response.items, "", "Select Client");
        }).catch(displayError);

        const form = document.getElementById("statementForm");
        form?.addEventListener("submit", async function (event) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const file = document.getElementById("statementFile").files[0];
            if (!file) {
                alert("Choose a bank statement file before continuing.");
                return;
            }
            const selectedName = document.getElementById("statementClient").selectedOptions[0]?.textContent || "";
            const clients = await run(function () { return getClients("", "all"); });
            if (!clients) return;
            const client = clients.items.find(function (item) { return item.name === selectedName; });
            const body = new FormData();
            body.append("client_id", client.id);
            body.append("bank", document.getElementById("statementBank").value);
            body.append("financial_year", document.getElementById("statementYear").value);
            body.append("file", file);
            try {
                const result = await api.request("/reconciliation/statements", { method: "POST", body: body });
                form.reset();
                window.closeStatementModal();
                alert(result.name + " was stored locally as a document. Its rows were not parsed into transactions.");
            } catch (error) {
                actionError(error);
            }
        }, true);
        void run(load);

        const params = new URLSearchParams(window.location.search);
        if (params.get("open") === "statement") window.openStatementModal();
        const transactionId = params.get("transaction");
        if (transactionId) {
            void run(async function () {
                const transaction = await api.get("/transactions/" + encodeURIComponent(transactionId));
                window.viewTransaction(
                    transaction.id, transaction.client, formatAmount(transaction.bank_amount),
                    formatAmount(transaction.book_amount), formatAmount(transaction.difference), transaction.status
                );
            });
        }
    }

    function initRisk() {
        const tbody = document.querySelector("#riskTable tbody");
        if (!tbody) return;
        const filter = document.getElementById("riskFilter");
        const search = document.getElementById("riskSearch");
        let modalAnomalyId = "";

        const originalView = window.viewAnomaly;
        window.viewAnomaly = function () {
            modalAnomalyId = arguments[0];
            return originalView.apply(this, arguments);
        };

        function showAnomaly(anomaly) {
            window.viewAnomaly(
                anomaly.id,
                anomaly.client,
                anomaly.category,
                formatAmount(anomaly.amount),
                anomaly.risk,
                anomaly.status,
                anomaly.detected,
                anomaly.reason
            );
        }

        async function load() {
            const selected = (filter?.value || "all").toLowerCase();
            const query = {
                search: search?.value || "",
                risk: ["high", "medium", "low"].includes(selected) ? selected : "all",
                status: ["open", "reviewed", "resolved"].includes(selected) ? selected : "all"
            };
            const response = await api.get("/anomalies" + api.query(query));
            tbody.replaceChildren();
            response.items.forEach(function (anomaly) {
                const row = document.createElement("tr");
                row.dataset.risk = anomaly.risk.toLowerCase();
                row.dataset.status = anomaly.status.toLowerCase();
                row.innerHTML = `
                    <td>${escapeHtml(anomaly.id)}</td>
                    <td>${escapeHtml(anomaly.client)}</td>
                    <td>${escapeHtml(anomaly.category)}</td>
                    <td>${formatAmount(anomaly.amount)}</td>
                    <td><span class="risk-badge ${escapeHtml(anomaly.risk.toLowerCase())}">${escapeHtml(anomaly.risk)}</span></td>
                    <td><span class="status-badge ${escapeHtml(anomaly.status.toLowerCase())}">${escapeHtml(anomaly.status)}</span></td>
                    <td>${escapeHtml(anomaly.detected)}</td>
                    <td>
                        <button type="button" class="action-btn" data-anomaly-view="${escapeHtml(anomaly.id)}">View</button>
                        ${anomaly.status === "Resolved" ? "" : `<button type="button" class="action-btn resolve-btn" data-anomaly-resolve="${escapeHtml(anomaly.id)}">Resolve</button>`}
                    </td>`;
                tbody.appendChild(row);
            });
            const empty = document.getElementById("emptyMessage");
            if (empty) empty.style.display = response.count ? "none" : "block";
            const allAnomalies = selected === "all" && !search?.value
                ? response
                : await api.get("/anomalies");
            const riskCounts = allAnomalies.items.reduce(function (counts, anomaly) {
                const risk = anomaly.risk.toLowerCase();
                counts[risk] = (counts[risk] || 0) + 1;
                return counts;
            }, {});
            document.querySelectorAll(".risk-summary .risk-card").forEach(function (card) {
                const label = card.querySelector(".label")?.textContent.toLowerCase() || "";
                const value = card.querySelector(".number");
                if (!value) return;
                if (label.includes("high")) value.textContent = riskCounts.high || 0;
                if (label.includes("medium")) value.textContent = riskCounts.medium || 0;
                if (label.includes("low")) value.textContent = riskCounts.low || 0;
                if (label.includes("total")) value.textContent = allAnomalies.count;
            });
        }

        window.searchRisks = function () { void run(load); };
        window.filterRisks = function () { void run(load); };
        window.resolveFromModal = async function () {
            if (!modalAnomalyId) return;
            try {
                await api.send("/anomalies/" + encodeURIComponent(modalAnomalyId), "PATCH", { status: "Resolved" });
                window.closeAnomaly();
                await load();
                alert(modalAnomalyId + " was marked Resolved in the local database.");
            } catch (error) {
                actionError(error);
            }
        };
        window.runRiskScan = async function () {
            try {
                const result = await api.send("/anomalies/scan", "POST", {});
                alert(result.notice + "\n\nStored unmatched/exception transactions reviewed: " + result.count + ".");
            } catch (error) {
                actionError(error);
            }
        };
        tbody.addEventListener("click", async function (event) {
            const view = event.target.closest("[data-anomaly-view]");
            const resolve = event.target.closest("[data-anomaly-resolve]");
            try {
                if (view) {
                    const anomaly = await api.get("/anomalies/" + encodeURIComponent(view.dataset.anomalyView));
                    showAnomaly(anomaly);
                } else if (resolve) {
                    await api.send("/anomalies/" + encodeURIComponent(resolve.dataset.anomalyResolve), "PATCH", { status: "Resolved" });
                    await load();
                    alert(resolve.dataset.anomalyResolve + " was marked Resolved in the local database.");
                }
            } catch (error) {
                actionError(error);
            }
        });
        const params = new URLSearchParams(window.location.search);
        if (params.get("filter") === "open" && filter) {
            filter.value = "open";
        }
        void run(load);
        const anomalyId = params.get("anomaly");
        if (anomalyId) {
            void run(async function () {
                showAnomaly(await api.get("/anomalies/" + encodeURIComponent(anomalyId)));
            });
        }
    }

    function initReports() {
        const tbody = document.querySelector("#reportsTable tbody");
        if (!tbody) return;
        const search = document.getElementById("reportSearch");
        const filter = document.getElementById("reportFilter");

        async function load() {
            const response = await api.get("/reports" + api.query({
                status: filter?.value || "all",
                search: search?.value || ""
            }));
            tbody.replaceChildren();
            response.items.forEach(function (report) {
                const row = document.createElement("tr");
                row.dataset.status = report.status.toLowerCase();
                row.innerHTML = `
                    <td>${escapeHtml(report.id)}</td>
                    <td>${escapeHtml(report.client)}</td>
                    <td>${escapeHtml(report.report_type)}</td>
                    <td>${escapeHtml(report.financial_year)}</td>
                    <td><span class="status-badge ${escapeHtml(report.status.toLowerCase())}">${escapeHtml(report.status)}</span></td>
                    <td>${escapeHtml(report.generated)}</td>
                    <td>
                        <button type="button" class="action-btn" data-report-view="${escapeHtml(report.id)}">View</button>
                        <button type="button" class="action-btn download-btn" data-report-download="${escapeHtml(report.id)}">Download</button>
                    </td>`;
                tbody.appendChild(row);
            });
            const all = await api.get("/reports");
            const total = document.getElementById("totalReportCount");
            if (total) total.textContent = all.count;
            const empty = document.getElementById("emptyMessage");
            if (empty) empty.style.display = response.count ? "none" : "block";
            const counts = all.items.reduce(function (values, report) {
                values[report.status.toLowerCase()] = (values[report.status.toLowerCase()] || 0) + 1;
                return values;
            }, {});
            document.querySelectorAll(".report-summary .summary-card").forEach(function (card) {
                const label = card.querySelector(".label")?.textContent.toLowerCase() || "";
                const number = card.querySelector(".number");
                if (!number) return;
                if (label.includes("total")) number.textContent = all.count;
                if (label.includes("completed")) number.textContent = counts.completed || 0;
                if (label.includes("draft")) number.textContent = counts.draft || 0;
                if (label.includes("pending")) number.textContent = counts.pending || 0;
            });
        }

        window.searchReports = function () { void run(load); };
        window.filterReports = function () { void run(load); };
        window.applyReportFilters = function () { void run(load); };

        tbody.addEventListener("click", async function (event) {
            const view = event.target.closest("[data-report-view]");
            const download = event.target.closest("[data-report-download]");
            try {
                if (view) {
                    const report = await api.get("/reports/" + encodeURIComponent(view.dataset.reportView));
                    window.viewReport(report.id, report.client, report.report_type, report.financial_year, report.status, report.generated);
                } else if (download) {
                    await api.download("/reports/" + encodeURIComponent(download.dataset.reportDownload) + "/download", download.dataset.reportDownload + ".txt");
                }
            } catch (error) {
                actionError(error);
            }
        });

        const selects = getClients("", "all").then(function (response) {
            if (response) setSelectOptions(document.getElementById("generateClient"), response.items, "", "Select Client");
        }).catch(displayError);
        const form = document.querySelector(".generate-form");
        form?.addEventListener("submit", async function (event) {
            event.preventDefault();
            event.stopImmediatePropagation();
            const body = {
                client_id: document.getElementById("generateClient").value,
                report_type: document.getElementById("generateType").value,
                financial_year: document.getElementById("generateFY").value
            };
            try {
                await selects;
                const report = await api.send("/reports", "POST", body);
                form.reset();
                window.closeGenerateModal();
                await load();
                alert(report.id + " was generated and saved locally as a Draft report file.");
            } catch (error) {
                actionError(error);
            }
        }, true);
        void run(load);
    }

    function initSettings() {
        if (!document.getElementById("fullName")) return;
        const readForm = function () {
            return {
                fullName: document.getElementById("fullName").value.trim(),
                email: document.getElementById("email").value.trim(),
                role: document.getElementById("role").value,
                firmName: document.getElementById("firmName").value.trim(),
                officeEmail: document.getElementById("officeEmail").value.trim(),
                officeLocation: document.getElementById("officeLocation").value.trim(),
                emailNotifications: document.getElementById("emailNotifications").checked,
                riskAlerts: document.getElementById("riskAlerts").checked,
                reportNotifications: document.getElementById("reportNotifications").checked,
                twoFactor: document.getElementById("twoFactor").checked,
                theme: document.getElementById("theme").value,
                layout: document.getElementById("layout").value
            };
        };
        window.loadSettings = function () {
            return run(async function () {
                const settings = await api.get("/settings");
                window.applySettings(settings);
                localStorage.setItem("caCopilotSettings", JSON.stringify(settings));
            });
        };
        window.saveSettings = async function () {
            try {
                const settings = await api.send("/settings", "PUT", readForm());
                window.applySettings(settings);
                localStorage.setItem("caCopilotSettings", JSON.stringify(settings));
                alert("Settings saved to the local CA-Copilot database.");
            } catch (error) {
                actionError(error);
            }
        };
        window.resetSettings = async function () {
            try {
                const settings = await api.send("/settings/reset", "POST", {});
                window.applySettings(settings);
                localStorage.setItem("caCopilotSettings", JSON.stringify(settings));
                alert("Settings were reset to defaults in the local database.");
            } catch (error) {
                actionError(error);
            }
        };
        void window.loadSettings();
    }

    function initChat() {
        const selector = document.getElementById("clientSelect");
        if (!selector) return;
        let clientList = [];
        let requestVersion = 0;

        async function loadClientContext(clearHistory) {
            const selected = clientList.find(function (client) { return client.id === selector.value; });
            if (!selected) return;
            document.getElementById("selectedClient").textContent = selected.name;
            document.getElementById("clientDocumentCount").textContent = selected.documents;
            const transactions = await api.get("/transactions" + api.query({ search: selected.name }));
            document.getElementById("clientTransactionCount").textContent = transactions.count;
            const body = document.getElementById("chatBody");
            body.replaceChildren();
            const history = clearHistory ? { items: [] } : await api.get("/chat/" + encodeURIComponent(selected.id));
            if (history.items.length) {
                history.items.forEach(function (message) {
                    appendMessage("user", message.question);
                    appendMessage("assistant", message.answer);
                });
            } else {
                appendMessage("assistant", "Client file selected: " + selected.name + ". Responses are based on local stored sample records, not AI analysis.");
            }
        }

        function appendMessage(role, text) {
            const message = document.createElement("div");
            message.className = "message " + role;
            const bubble = document.createElement("div");
            bubble.className = "message-bubble";
            bubble.textContent = text;
            if (role === "assistant") {
                const note = document.createElement("div");
                note.className = "source-tag";
                note.textContent = "Local rule-based response · sample/database records";
                bubble.appendChild(note);
            }
            message.appendChild(bubble);
            const chatBody = document.getElementById("chatBody");
            chatBody.appendChild(message);
            chatBody.scrollTop = chatBody.scrollHeight;
        }

        getClients("", "all").then(async function (response) {
            if (!response) return;
            clientList = response.items;
            setSelectOptions(selector, clientList, "CL-001");
            await loadClientContext(false);
        }).catch(displayError);

        window.changeClient = function () {
            requestVersion++;
            void run(function () { return loadClientContext(false); });
        };
        window.sendQuestion = async function () {
            const question = document.getElementById("chatInput").value.trim();
            if (!question) return;
            const version = requestVersion;
            const clientId = selector.value;
            appendMessage("user", question);
            document.getElementById("chatInput").value = "";
            try {
                const response = await api.send("/chat/ask", "POST", { client_id: clientId, question: question });
                if (version === requestVersion && clientId === selector.value) appendMessage("assistant", response.answer);
            } catch (error) {
                actionError(error);
            }
        };
        window.askSuggestion = function (question) {
            document.getElementById("chatInput").value = question;
            void window.sendQuestion();
        };
        window.handleEnter = function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                void window.sendQuestion();
            }
        };
        window.clearChat = async function () {
            const clientId = selector.value;
            try {
                await api.request("/chat/" + encodeURIComponent(clientId), { method: "DELETE" });
                requestVersion++;
                await loadClientContext(true);
            } catch (error) {
                actionError(error);
            }
        };
    }

    function initDashboard() {
        const panel = document.querySelector(".reviews-panel");
        if (!panel) return;
        void run(async function () {
            const dashboard = await api.get("/dashboard");
            const cards = document.querySelectorAll(".dashboard-stat");
            cards.forEach(function (card) {
                const text = card.textContent.toLowerCase();
                const value = card.querySelector("h2");
                if (!value) return;
                if (text.includes("total clients")) value.textContent = dashboard.clients;
                if (text.includes("documents")) value.textContent = dashboard.documents;
                if (text.includes("reconciliation")) value.textContent = dashboard.matched;
                if (text.includes("mismatches")) value.textContent = dashboard.unmatched + dashboard.exceptions;
                if (text.includes("high risk")) value.textContent = dashboard.high_risk;
            });
            document.querySelectorAll(".dashboard-panel.risk-panel .risk-item").forEach(function (item) {
                const label = item.querySelector(".risk-title span")?.textContent.toLowerCase() || "";
                const value = item.querySelector(".risk-title strong");
                if (!value) return;
                if (label.includes("high")) value.textContent = dashboard.risk_breakdown.high || 0;
                if (label.includes("medium")) value.textContent = dashboard.risk_breakdown.medium || 0;
                if (label.includes("low")) value.textContent = dashboard.risk_breakdown.low || 0;
            });
            const anomalyTotal = document.querySelector(".dashboard-panel.risk-panel .risk-summary strong");
            if (anomalyTotal) anomalyTotal.textContent = dashboard.anomalies_total;
            const links = panel.querySelectorAll(".review-row");
            const records = dashboard.activity;
            for (const [index, record] of records.entries()) {
                const link = links[index];
                if (!link) continue;
                const heading = link.querySelector("h3");
                const description = link.querySelector(".review-info p");
                const amount = link.querySelector(".review-amount strong");
                const note = link.querySelector(".review-amount span");
                const status = link.querySelector(".review-status");
                if (heading) heading.textContent = record.client;
                if (record.kind === "transaction") {
                    const details = await api.get("/transactions/" + encodeURIComponent(record.id));
                    if (description) description.textContent = "Bank Payment Reconciliation";
                    if (amount) amount.textContent = formatAmount(details.bank_amount);
                    if (note) note.textContent = Number(details.difference) ? formatAmount(details.difference) + " mismatch" : "Matched";
                    if (status) status.textContent = details.status;
                    link.href = "reconciliation.html?transaction=" + encodeURIComponent(record.id);
                } else {
                    if (description) description.textContent = record.category;
                    if (amount) amount.textContent = formatAmount(record.amount);
                    if (note) note.textContent = record.reason;
                    if (status) status.textContent = record.status;
                    link.href = "risk.html?anomaly=" + encodeURIComponent(record.id);
                }
            }
        });
    }

    const pathname = window.location.pathname.split("/").pop();
    if (pathname === "dashboard.html") initDashboard();
    if (pathname === "clients.html") initClients();
    if (pathname === "documents.html") initDocuments();
    if (pathname === "reconciliation.html") initReconciliation();
    if (pathname === "risk.html") initRisk();
    if (pathname === "ask-client.html") initChat();
    if (pathname === "reports.html") initReports();
    if (pathname === "settings.html") initSettings();
})();
