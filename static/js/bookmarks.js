/* Separate from answer submission, autosave, timers and grading. */
(() => {
  "use strict";
  const pending = new Set();
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-bookmark-form]");
    if (!form) return;
    event.preventDefault();
    const id = form.dataset.questionId;
    if (pending.has(id)) return;
    pending.add(id);
    const peers = [...document.querySelectorAll("[data-bookmark-form]")].filter(item => item.dataset.questionId === id);
    const buttons = peers.map(item => item.querySelector("[data-bookmark-button]"));
    buttons.forEach(button => { button.setAttribute("aria-disabled", "true"); });
    form.setAttribute("aria-busy", "true");
    const status = form.querySelector("[data-bookmark-status]");
    status.classList.add("visually-hidden");
    status.textContent = "Saving...";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(form.action, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json", "X-CSRFToken": form.elements.csrfmiddlewaretoken.value },
        body: new FormData(form), signal: controller.signal
      });
      if (response.status === 401) {
        form.querySelector("[data-bookmark-login]").hidden = false;
        throw new Error("Sign in again to save questions.");
      }
      if (!response.ok) throw new Error("Could not update this bookmark. Please retry.");
      const state = await response.json();
      peers.forEach(item => {
        item.action = state.saved ? item.dataset.unsaveUrl : item.dataset.saveUrl;
        const button = item.querySelector("[data-bookmark-button]");
        button.setAttribute("aria-pressed", String(state.saved));
        button.querySelector("[data-bookmark-label]").textContent = state.saved ? "Saved for revision" : "Save for revision";
        const actionLabel = state.saved ? "Remove from revision bank" : "Save for revision";
        button.setAttribute("aria-label", actionLabel);
        button.title = actionLabel;
        item.querySelector("[data-bookmark-status]").classList.add("visually-hidden");
        item.querySelector("[data-bookmark-status]").textContent = "";
        // Uncomment below to restore saved/removed confirmation messages.
        // item.querySelector("[data-bookmark-status]").textContent = state.saved ? "Saved for revision." : "Removed from saved questions.";
      });
    } catch (error) {
      status.classList.remove("visually-hidden");
      status.textContent = error.name === "AbortError" ? "Bookmark request timed out. Please retry." : error.message;
    } finally {
      clearTimeout(timeout);
      buttons.forEach(button => { button.removeAttribute("aria-disabled"); });
      form.removeAttribute("aria-busy");
      pending.delete(id);
    }
  });
})();
