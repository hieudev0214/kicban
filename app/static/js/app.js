const form = document.getElementById("job-form");
const submitBtn = document.getElementById("submit-btn");
const statusPanel = document.getElementById("status-panel");
const statusText = document.getElementById("status-text");
const statusSpinner = document.getElementById("status-spinner");
const resultPanel = document.getElementById("result-panel");
const transcriptText = document.getElementById("transcript-text");
const detectedLanguage = document.getElementById("detected-language");
const downloadTxt = document.getElementById("download-txt");
const downloadSrt = document.getElementById("download-srt");
const historyList = document.getElementById("history-list");
const navGuest = document.getElementById("nav-guest");
const navUser = document.getElementById("nav-user");
const walletBalanceEl = document.getElementById("wallet-balance");
const adminLink = document.getElementById("admin-link");
const topupPanel = document.getElementById("topup-panel");
const topupBtn = document.getElementById("topup-btn");
const topupSubmit = document.getElementById("topup-submit");
const topupStatus = document.getElementById("topup-status");
const freeTrialBanner = document.getElementById("free-trial-banner");

let activeTab = "link";
let pollTimer = null;
let currentUser = null;

document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        activeTab = btn.dataset.tab;
        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        document.querySelectorAll(".tab-panel").forEach((p) => {
            p.classList.toggle("hidden", p.dataset.panel !== activeTab);
        });
    });
});

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

function formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return null;
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    if (m === 0) return `${s} giây`;
    if (s === 0) return `${m} phút`;
    return `${m} phút ${s} giây`;
}

function showStatus(text, isError = false, inProgress = true) {
    statusPanel.classList.remove("hidden");
    statusText.textContent = text;
    statusText.className = isError ? "error-text" : "";
    statusSpinner.classList.toggle("hidden", !inProgress);
}

function showResult(job) {
    resultPanel.classList.remove("hidden");
    transcriptText.value = job.transcript_text || "(không phát hiện giọng nói)";
    detectedLanguage.textContent = job.language_detected
        ? `Ngôn ngữ nhận diện: ${job.language_detected}`
        : "";
    downloadTxt.href = `/api/jobs/${job.id}/download?fmt=txt`;
    downloadSrt.href = `/api/jobs/${job.id}/download?fmt=srt`;
}

async function pollJob(jobId) {
    pollTimer = setInterval(async () => {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) {
            stopPolling();
            showStatus("Không thể lấy trạng thái job.", true, false);
            submitBtn.disabled = false;
            return;
        }
        const job = await res.json();
        if (job.status === "done") {
            stopPolling();
            showStatus("Hoàn tất.", false, false);
            showResult(job);
            submitBtn.disabled = false;
            loadHistory();
            loadMe();
        } else if (job.status === "error") {
            stopPolling();
            showStatus(job.error || "Đã có lỗi xảy ra.", true, false);
            submitBtn.disabled = false;
            loadHistory();
            loadMe();
        } else {
            showStatus(job.stage_message || job.status);
        }
    }, 2000);
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentUser) {
        window.location.href = "/login";
        return;
    }
    submitBtn.disabled = true;
    resultPanel.classList.add("hidden");
    showStatus("Đang gửi...");

    const language = document.getElementById("language-select").value;

    let res;
    try {
        if (activeTab === "link") {
            const url = document.getElementById("url-input").value.trim();
            if (!url) {
                showStatus("Vui lòng nhập link video.", true, false);
                submitBtn.disabled = false;
                return;
            }
            res = await fetch("/api/jobs", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, language }),
            });
        } else {
            const fileInput = document.getElementById("file-input");
            if (!fileInput.files.length) {
                showStatus("Vui lòng chọn file.", true, false);
                submitBtn.disabled = false;
                return;
            }
            const formData = new FormData();
            formData.append("file", fileInput.files[0]);
            formData.append("language", language);
            res = await fetch("/api/jobs/upload", { method: "POST", body: formData });
        }
    } catch (err) {
        showStatus("Không thể kết nối tới server.", true, false);
        submitBtn.disabled = false;
        return;
    }

    if (res.status === 401) {
        window.location.href = "/login";
        return;
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showStatus(err.detail || "Yêu cầu không hợp lệ.", true, false);
        submitBtn.disabled = false;
        return;
    }

    const data = await res.json();
    const durationMsg = data.duration_seconds != null
        ? `Video dài ${formatDuration(data.duration_seconds)}`
        : "Không xác định được thời lượng video";
    const priceMsg = data.price_vnd === 0
        ? "dùng lượt miễn phí"
        : `đã trừ ${data.price_vnd.toLocaleString("vi-VN")} đ`;
    showStatus(`${durationMsg} — ${priceMsg} — đã đưa vào hàng đợi...`);
    loadMe();
    pollJob(data.job_id);
});

async function loadHistory() {
    if (!currentUser) return;
    const res = await fetch("/api/jobs?limit=20");
    if (!res.ok) return;
    const jobList = await res.json();
    historyList.innerHTML = "";
    jobList.forEach((job) => {
        const li = document.createElement("li");
        const label = document.createElement("span");
        const durationPart = job.duration_seconds != null ? ` — ${formatDuration(job.duration_seconds)}` : "";
        label.textContent = `${job.source_ref}${durationPart} — ${job.status}`;
        li.appendChild(label);
        if (job.status === "done") {
            const link = document.createElement("a");
            link.href = "#";
            link.textContent = "Xem";
            link.addEventListener("click", (e) => {
                e.preventDefault();
                showStatus("Hoàn tất.", false, false);
                statusPanel.classList.remove("hidden");
                showResult(job);
            });
            li.appendChild(link);
        }
        historyList.appendChild(li);
    });
}

async function loadMe() {
    const res = await fetch("/api/auth/me");
    if (!res.ok) {
        currentUser = null;
        navGuest.classList.remove("hidden");
        navUser.classList.add("hidden");
        freeTrialBanner.classList.add("hidden");
        return;
    }
    currentUser = await res.json();
    navGuest.classList.add("hidden");
    navUser.classList.remove("hidden");
    walletBalanceEl.textContent = `Số dư: ${currentUser.wallet_balance_vnd.toLocaleString("vi-VN")} đ`;
    adminLink.classList.toggle("hidden", currentUser.role !== "admin");
    freeTrialBanner.classList.toggle("hidden", !currentUser.free_trial_available);
    loadHistory();
}

document.getElementById("logout-btn").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.reload();
});

const topupQrPanel = document.getElementById("topup-qr-panel");
const topupHistoryList = document.getElementById("topup-history-list");

topupBtn.addEventListener("click", () => {
    topupPanel.classList.toggle("hidden");
    if (!topupPanel.classList.contains("hidden")) loadTopupHistory();
});

topupSubmit.addEventListener("click", async () => {
    const amount = parseInt(document.getElementById("topup-amount").value, 10);
    if (Number.isNaN(amount) || amount <= 0) {
        topupStatus.textContent = "Số tiền không hợp lệ.";
        return;
    }
    topupStatus.textContent = "Đang tạo yêu cầu...";
    const res = await fetch("/api/wallet/topup-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount_vnd: amount }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        topupStatus.textContent = err.detail || "Không thể tạo yêu cầu nạp tiền.";
        return;
    }
    const data = await res.json();
    topupStatus.textContent = "";
    topupQrPanel.classList.remove("hidden");
    document.getElementById("topup-qr-img").src = data.qr_image_url;
    document.getElementById("topup-qr-amount").textContent = `${data.amount_vnd.toLocaleString("vi-VN")} đ`;
    document.getElementById("topup-qr-note").textContent = data.note;
    document.getElementById("topup-qr-bank").textContent = data.bank_id;
    document.getElementById("topup-qr-account").textContent = data.bank_account_no;
    document.getElementById("topup-qr-name").textContent = data.bank_account_name;
    loadTopupHistory();
});

const TOPUP_STATUS_LABELS = {
    pending: "Chờ duyệt",
    approved: "Đã cộng tiền",
    rejected: "Bị từ chối",
};

async function loadTopupHistory() {
    const res = await fetch("/api/wallet/my-topups");
    if (!res.ok) return;
    const topupList = await res.json();
    topupHistoryList.innerHTML = "";
    topupList.forEach((t) => {
        const li = document.createElement("li");
        li.textContent = `${t.amount_vnd.toLocaleString("vi-VN")} đ — ${t.note} — ${TOPUP_STATUS_LABELS[t.status] || t.status}`;
        topupHistoryList.appendChild(li);
    });
}

loadMe();
