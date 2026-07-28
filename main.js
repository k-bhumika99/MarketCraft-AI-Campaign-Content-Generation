// main.js — MarketCraft AI client-side interactivity

document.addEventListener("DOMContentLoaded", () => {
  initFlashDismiss();
  initModeToggle();
  initDropzone();
  initTabs();
  initCopyButtons();
  initImageGeneration();
});

function initFlashDismiss() {
  document.querySelectorAll(".flash").forEach((el) => {
    setTimeout(() => { el.style.transition = "opacity .4s"; el.style.opacity = "0"; }, 5000);
  });
}

// Upload page: toggle between "Upload File" and "Manual Entry"
function initModeToggle() {
  const buttons = document.querySelectorAll("[data-mode-btn]");
  if (!buttons.length) return;
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.modeBtn;
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll("[data-mode-panel]").forEach((panel) => {
        panel.style.display = panel.dataset.modePanel === mode ? "block" : "none";
      });
      const modeInput = document.getElementById("mode-input");
      if (modeInput) modeInput.value = mode;
    });
  });
}

// Drag-and-drop file upload
function initDropzone() {
  const dz = document.getElementById("dropzone");
  const input = document.getElementById("report_file");
  if (!dz || !input) return;

  const showName = (name) => {
    let label = dz.querySelector(".dz-filename");
    if (!label) {
      label = document.createElement("div");
      label.className = "dz-filename";
      dz.appendChild(label);
    }
    label.textContent = "📄 " + name;
  };

  dz.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { if (input.files[0]) showName(input.files[0].name); });

  ["dragover", "dragenter"].forEach((evt) =>
    dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
  );
  dz.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      showName(e.dataTransfer.files[0].name);
    }
  });
}

// Marketing kit result tabs
function initTabs() {
  const tabButtons = document.querySelectorAll("[data-tab-btn]");
  if (!tabButtons.length) return;
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tabBtn;
      tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.tabPanel === target);
      });
    });
  });
}

// Copy-to-clipboard for generated copy blocks
function initCopyButtons() {
  document.querySelectorAll("[data-copy-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const el = document.getElementById(btn.dataset.copyTarget);
      if (!el) return;
      navigator.clipboard.writeText(el.innerText.trim()).then(() => {
        const original = btn.textContent;
        btn.textContent = "Copied ✓";
        setTimeout(() => { btn.textContent = original; }, 1500);
      });
    });
  });
}

// Give every real page-navigation form (sign in, sign up, upload, generate kit,
// delete, etc.) instant visual feedback on submit — a loading state on the
// button — instead of a silent pause that can feel like the click "did nothing".
function initFormSubmitFeedback() {
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      // Respect any client-side validation that cancelled the submit
      // (e.g. the platform-selection check on the Review page, or a
      // confirm() dialog on the Delete form that the user declined).
      if (e.defaultPrevented) return;

      const btn = form.querySelector('button[type="submit"]');
      if (!btn || btn.disabled) return;

      const loadingText = btn.dataset.loadingText || "Please wait…";
      btn.dataset.originalHtml = btn.innerHTML;
      btn.innerHTML = `<span class="spinner" style="width:14px;height:14px;border-width:2px;"></span> ${loadingText}`;
      setTimeout(() => btn.disabled = true, 10);

      // Safety net: if the browser doesn't navigate away (e.g. validation
      // error re-renders the same page), restore the button after a beat.
      setTimeout(() => {
        if (btn.dataset.originalHtml) {
          btn.innerHTML = btn.dataset.originalHtml;
          btn.disabled = false;
        }
      }, 4000);
    });
  });
}

// Creative Design Agent: on-demand AI image generation
function initImageGeneration() {
  document.querySelectorAll("[data-generate-image]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const campaignId = btn.dataset.campaignId;
      const prompt = btn.dataset.prompt;
      const targetId = btn.dataset.generateImage;
      const target = document.getElementById(targetId);
      if (!target) return;

      target.innerHTML = '<div class="spinner"></div><span>Generating…</span>';
      target.classList.add("image-placeholder");
      btn.setAttribute("disabled", "disabled");

      try {
        const res = await fetch(`/campaign/${campaignId}/image`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        });
        const data = await res.json();
        if (data.url) {
          target.classList.remove("image-placeholder");
          target.innerHTML = `<img src="${data.url}" alt="Generated creative">`;
          
          const actionsId = btn.dataset.actionsTarget;
          if (actionsId) {
            const actionsDiv = document.getElementById(actionsId);
            if (actionsDiv) {
              actionsDiv.style.display = 'flex';
              const dlBtn = actionsDiv.querySelector('.dl-btn');
              if (dlBtn) dlBtn.href = data.url;
            }
          }

          if (!data.live) {
            const note = document.createElement("p");
            note.textContent = "Offline preview — add a valid GEMINI_API_KEY for live AI images.";
            note.style.cssText = "font-size:11px;color:var(--muted-dim);padding:6px 10px;";
            target.parentElement.appendChild(note);
          }
        }
      } catch (e) {
        target.innerHTML = "Could not generate image.";
      } finally {
        btn.removeAttribute("disabled");
      }
    });
  });
}
