const errorEl = document.getElementById("admin-error");
const table = document.getElementById("users-table");
const tbody = document.getElementById("users-tbody");
const jobsPanel = document.getElementById("jobs-panel");
const jobsUserEmail = document.getElementById("jobs-user-email");
const jobsList = document.getElementById("jobs-list");
const topupsTable = document.getElementById("topups-table");
const topupsTbody = document.getElementById("topups-tbody");
const topupsEmpty = document.getElementById("topups-empty");

function fmtVnd(n) {
    return n.toLocaleString("vi-VN") + " đ";
}

async function loadTopups() {
    const res = await fetch("/api/admin/topups?status=pending");
    if (res.status === 401) {
        window.location.href = "/login";
        return;
    }
    if (!res.ok) return;
    const topups = await res.json();
    topupsTbody.innerHTML = "";
    if (topups.length === 0) {
        topupsTable.classList.add("hidden");
        topupsEmpty.classList.remove("hidden");
        return;
    }
    topupsEmpty.classList.add("hidden");
    topupsTable.classList.remove("hidden");
    topups.forEach((t) => {
        const tr = document.createElement("tr");
        [t.user_email, fmtVnd(t.amount_vnd), t.note, new Date(t.created_at).toLocaleString("vi-VN")].forEach(
            (text) => {
                const td = document.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            }
        );

        const actionsTd = document.createElement("td");
        actionsTd.className = "admin-actions";

        const approveBtn = document.createElement("button");
        approveBtn.textContent = "Duyệt (đã nhận tiền)";
        approveBtn.addEventListener("click", async () => {
            if (!confirm(`Xác nhận đã nhận ${fmtVnd(t.amount_vnd)} với nội dung "${t.note}"?`)) return;
            const r = await fetch(`/api/admin/topups/${t.id}/approve`, { method: "POST" });
            if (r.ok) {
                loadTopups();
                loadUsers();
            } else errorEl.textContent = "Duyệt thất bại.";
        });
        actionsTd.appendChild(approveBtn);

        const rejectBtn = document.createElement("button");
        rejectBtn.textContent = "Từ chối";
        rejectBtn.addEventListener("click", async () => {
            if (!confirm("Từ chối yêu cầu này?")) return;
            const r = await fetch(`/api/admin/topups/${t.id}/reject`, { method: "POST" });
            if (r.ok) loadTopups();
            else errorEl.textContent = "Từ chối thất bại.";
        });
        actionsTd.appendChild(rejectBtn);

        tr.appendChild(actionsTd);
        topupsTbody.appendChild(tr);
    });
}

async function loadUsers() {
    const res = await fetch("/api/admin/users");
    if (res.status === 401) {
        window.location.href = "/login";
        return;
    }
    if (res.status === 403) {
        errorEl.textContent = "Bạn không có quyền truy cập trang này.";
        return;
    }
    if (!res.ok) {
        errorEl.textContent = "Không thể tải danh sách user.";
        return;
    }
    const users = await res.json();
    table.classList.remove("hidden");
    tbody.innerHTML = "";
    users.forEach((u) => {
        const tr = document.createElement("tr");

        const cells = [
            u.email,
            u.role,
            fmtVnd(u.wallet_balance_vnd),
            u.is_locked ? "Đã khoá" : "Hoạt động",
            new Date(u.created_at).toLocaleString("vi-VN"),
        ];
        cells.forEach((text) => {
            const td = document.createElement("td");
            td.textContent = text;
            tr.appendChild(td);
        });

        const actionsTd = document.createElement("td");
        actionsTd.className = "admin-actions";

        const viewBtn = document.createElement("button");
        viewBtn.textContent = "Xem job";
        viewBtn.addEventListener("click", () => loadJobs(u.id, u.email));
        actionsTd.appendChild(viewBtn);

        const creditBtn = document.createElement("button");
        creditBtn.textContent = "Cộng/trừ tiền";
        creditBtn.addEventListener("click", async () => {
            const amountStr = prompt("Số tiền cộng (âm để trừ), VND:", "50000");
            if (amountStr === null) return;
            const amount = parseInt(amountStr, 10);
            if (Number.isNaN(amount)) return;
            const r = await fetch(`/api/admin/users/${u.id}/credit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ amount_vnd: amount }),
            });
            if (r.ok) loadUsers();
            else errorEl.textContent = "Cộng/trừ tiền thất bại.";
        });
        actionsTd.appendChild(creditBtn);

        const lockBtn = document.createElement("button");
        lockBtn.textContent = u.is_locked ? "Mở khoá" : "Khoá";
        lockBtn.addEventListener("click", async () => {
            const r = await fetch(`/api/admin/users/${u.id}/lock`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ locked: !u.is_locked }),
            });
            if (r.ok) loadUsers();
            else errorEl.textContent = "Cập nhật trạng thái thất bại.";
        });
        actionsTd.appendChild(lockBtn);

        const deleteBtn = document.createElement("button");
        deleteBtn.textContent = "Xoá";
        deleteBtn.addEventListener("click", async () => {
            if (!confirm(`Xoá tài khoản ${u.email}?`)) return;
            const r = await fetch(`/api/admin/users/${u.id}`, { method: "DELETE" });
            if (r.ok) loadUsers();
            else errorEl.textContent = "Xoá thất bại.";
        });
        actionsTd.appendChild(deleteBtn);

        tr.appendChild(actionsTd);
        tbody.appendChild(tr);
    });
}

async function loadJobs(userId, email) {
    const res = await fetch(`/api/admin/users/${userId}/jobs`);
    if (!res.ok) return;
    const userJobs = await res.json();
    jobsPanel.classList.remove("hidden");
    jobsUserEmail.textContent = email;
    jobsList.innerHTML = "";
    userJobs.forEach((job) => {
        const li = document.createElement("li");
        li.textContent = `${job.source_ref} — ${job.status} — ${job.price_vnd} đ`;
        jobsList.appendChild(li);
    });
}

loadTopups();
loadUsers();
