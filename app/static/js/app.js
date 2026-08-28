const form = document.getElementById("job-form");
const submitBtn = document.getElementById("submit-btn");
const statusPanel = document.getElementById("status-panel");
const statusText = document.getElementById("status-text");
const resultPanel = document.getElementById("result-panel");
const transcriptText = document.getElementById("transcript-text");
const detectedLanguage = document.getElementById("detected-language");
const downloadTxt = document.getElementById("download-txt");
const downloadSrt = document.getElementById("download-srt");
const historyList = document.getElementById("history-list");

let activeTab = "link";
let pollTimer = null;

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

function showStatus(text, isError = false) {
    statusPanel.classList.remove("hidden");
    statusText.textContent = text;
    statusText.className = isError ? "error-text" : "";
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
            showStatus("Không thể lấy trạng thái job.", true);
            submitBtn.disabled = false;
            return;
        }
        const job = await res.json();
        if (job.status === "done") {
            stopPolling();
            showStatus("Hoàn tất.");
            showResult(job);
            submitBtn.disabled = false;
            loadHistory();
        } else if (job.status === "error") {
            stopPolling();
            showStatus(job.error || "Đã có lỗi xảy ra.", true);
            submitBtn.disabled = false;
            loadHistory();
        } else {
            showStatus(job.stage_message || job.status);
        }
    }, 2000);
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    resultPanel.classList.add("hidden");
    showStatus("Đang gửi...");

    const language = document.getElementById("language-select").value;
    const engine = document.getElementById("engine-select").value;

    let res;
    try {
        if (activeTab === "link") {
            const url = document.getElementById("url-input").value.trim();
            if (!url) {
                showStatus("Vui lòng nhập link video.", true);
                submitBtn.disabled = false;
                return;
            }
            res = await fetch("/api/jobs", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, language, engine }),
            });
        } else {
            const fileInput = document.getElementById("file-input");
            if (!fileInput.files.length) {
                showStatus("Vui lòng chọn file.", true);
                submitBtn.disabled = false;
                return;
            }
            const formData = new FormData();
            formData.append("file", fileInput.files[0]);
            formData.append("language", language);
            formData.append("engine", engine);
            res = await fetch("/api/jobs/upload", { method: "POST", body: formData });
        }
    } catch (err) {
        showStatus("Không thể kết nối tới server.", true);
        submitBtn.disabled = false;
        return;
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showStatus(err.detail || "Yêu cầu không hợp lệ.", true);
        submitBtn.disabled = false;
        return;
    }

    const data = await res.json();
    showStatus("Đã đưa vào hàng đợi...");
    pollJob(data.job_id);
});

async function loadHistory() {
    const res = await fetch("/api/jobs?limit=20");
    if (!res.ok) return;
    const jobList = await res.json();
    historyList.innerHTML = "";
    jobList.forEach((job) => {
        const li = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = `${job.source_ref} — ${job.status}`;
        li.appendChild(label);
        if (job.status === "done") {
            const link = document.createElement("a");
            link.href = "#";
            link.textContent = "Xem";
            link.addEventListener("click", (e) => {
                e.preventDefault();
                showStatus("Hoàn tất.");
                statusPanel.classList.remove("hidden");
                showResult(job);
            });
            li.appendChild(link);
        }
        historyList.appendChild(li);
    });
}

loadHistory();
