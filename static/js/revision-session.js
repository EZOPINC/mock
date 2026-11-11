/* Only transports Practice-engine submissions; answer keys remain server-side. */
(() => {
  "use strict";
  const page = document.querySelector("[data-revision-session]");
  if (!page) return;
  let busy = false;
  page.addEventListener("change", event => {
    if (event.target.matches("[data-revision-answer] input[type=radio]") && !busy) {
      const form = event.target.closest("form");
      form.querySelectorAll("input[type=radio]").forEach(input => { input.checked = input.value === event.target.value; });
      form.requestSubmit();
    }
  });
  page.addEventListener("submit", async event => {
    const form = event.target.closest("[data-revision-answer]");
    if (!form) return;
    event.preventDefault();
    if (busy) return;
    busy = true;
    const region = page.querySelector("[data-revision-live]");
    const status = form.querySelector(".practice-selection-status");
    const body = new FormData(form);
    const controls = [...form.querySelectorAll("input, button")];
    controls.forEach(control => { control.disabled = true; });
    form.setAttribute("aria-busy", "true");
    status.textContent = "Checking your answer...";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(form.action, {method: "POST", body, credentials: "same-origin", cache: "no-store",
        headers: {"X-Requested-With": "XMLHttpRequest"}, signal: controller.signal});
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      if (!response.ok && response.status !== 400) throw new Error("Could not submit. Please retry.");
      region.innerHTML = await response.text();
      const question = region.querySelector("#practice-question");
      question?.focus({preventScroll: true});
    } catch (error) {
      status.textContent = "Submission could not be confirmed. Retry the same answer or reload to see its saved state.";
      form.querySelectorAll("input[type=radio]").forEach(input => { input.checked = false; });
    } finally {
      clearTimeout(timeout);
      controls.forEach(control => { control.disabled = false; });
      form.removeAttribute("aria-busy");
      busy = false;
    }
  });
})();
