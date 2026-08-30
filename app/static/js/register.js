document.getElementById("auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("email-input").value.trim();
    const password = document.getElementById("password-input").value;
    const errorEl = document.getElementById("auth-error");
    errorEl.textContent = "";
    const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent = err.detail || "Đăng ký thất bại.";
        return;
    }
    window.location.href = "/";
});
