/* Questly — small, dependency-free interactions. */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- confirm
     Any button with data-confirm asks before it submits. */
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-confirm]");
    if (btn && !window.confirm(btn.getAttribute("data-confirm"))) {
      e.preventDefault();
      e.stopPropagation();
    }
  });

  /* ------------------------------------------------------- dismiss flashes */
  document.addEventListener("click", function (e) {
    const x = e.target.closest("[data-dismiss]");
    if (x) x.closest(".flash").remove();
  });

  document.querySelectorAll(".flash").forEach(function (flash) {
    setTimeout(function () {
      flash.style.transition = "opacity .4s, transform .4s";
      flash.style.opacity = "0";
      flash.style.transform = "translateY(-8px)";
      setTimeout(() => flash.remove(), 400);
    }, 6000);
  });

  /* ----------------------------------------------------- double-submit guard
     Stops an excited kid tapping "Buy" or "Done!" three times. */
  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (form.matches("[data-step-form]")) return;
    const buttons = form.querySelectorAll('button[type="submit"], button:not([type])');
    setTimeout(function () {
      buttons.forEach(function (b) {
        b.disabled = true;
        b.style.opacity = ".6";
      });
    }, 0);
  });

  /* ----------------------------------------------------- step checklist
     Ticks off steps without full-page reloads and reveals the Done button
     smoothly when all steps are completed. */
  document.addEventListener("submit", async function (e) {
    const form = e.target.closest("[data-step-form]");
    if (!form) return;

    e.preventDefault();
    e.stopPropagation();

    const btn = form.querySelector("[data-step-btn]");
    if (!btn || btn.disabled) return;

    const questId = btn.getAttribute("data-quest-id");
    const card = document.getElementById("quest-" + questId);
    if (!card) return;

    const box = btn.querySelector(".step__box");
    const wasDone = btn.classList.contains("is-done");
    const willBeDone = !wasDone;

    // Optimistic toggle
    btn.classList.toggle("is-done", willBeDone);
    if (box) {
      box.innerHTML = willBeDone ? "&#10003;" : "";
    }

    btn.disabled = true;

    try {
      const body = new FormData(form);
      const res = await fetch(form.action, {
        method: "POST",
        body: body,
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Accept": "application/json"
        }
      });

      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed");

      btn.classList.toggle("is-done", Boolean(data.ticked));
      if (box) {
        box.innerHTML = data.ticked ? "&#10003;" : "";
      }

      const countEl = card.querySelector(".steps__count");
      if (countEl) {
        countEl.textContent = data.steps_done + " of " + data.steps_total;
      }

      const actionEl = document.getElementById("quest-action-" + questId);
      const footEl = document.getElementById("steps-foot-" + questId);
      const csrfInput = form.querySelector('[name="_csrf"]');
      const csrfVal = csrfInput ? csrfInput.value : "";
      const finishUrl = "/me/quests/" + questId + "/done";

      if (data.all_done) {
        if (actionEl) {
          actionEl.innerHTML = '<span class="stamp stamp--done">Steps done&nbsp;&#10003;</span>';
        }
        if (footEl) {
          footEl.innerHTML =
            '<form method="post" action="' + finishUrl + '">' +
            '<input type="hidden" name="_csrf" value="' + csrfVal + '">' +
            '<button class="btn btn--go" id="done-' + questId + '" type="submit">Done!</button>' +
            '</form>';
          footEl.classList.add("is-shown");
          const bottomDone = footEl.querySelector("button");
          if (bottomDone) {
            bottomDone.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
            bottomDone.classList.add("pulse");
            setTimeout(function () { bottomDone.classList.remove("pulse"); }, 1000);
          }
        }
      } else {
        const left = data.steps_left;
        if (actionEl) {
          actionEl.innerHTML =
            '<span class="stamp stamp--steps">' + left + " step" + (left === 1 ? "" : "s") + " left</span>";
        }
        if (footEl) {
          footEl.classList.remove("is-shown");
          footEl.innerHTML = "";
        }
      }
    } catch (err) {
      console.error("Step toggle failed:", err);
      btn.classList.toggle("is-done", wasDone);
      if (box) {
        box.innerHTML = wasDone ? "&#10003;" : "";
      }
    } finally {
      btn.disabled = false;
    }
  });

  /* ----------------------------------------------------------- balance count */
  const counter = document.querySelector("[data-count]");
  if (counter && !reduceMotion) {
    const target = parseInt(counter.getAttribute("data-count"), 10) || 0;
    if (target > 0 && target < 100000) {
      const start = performance.now();
      const duration = Math.min(900, 260 + target * 6);
      counter.textContent = "0";
      requestAnimationFrame(function step(now) {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        counter.textContent = Math.round(target * eased).toString();
        if (t < 1) requestAnimationFrame(step);
      });
    }
  }

  /* -------------------------------------------------------------- PIN pad */
  const pinForm = document.getElementById("pinform");
  if (pinForm) {
    const value = document.getElementById("pin-value");
    const dots = Array.from(document.querySelectorAll("#pin-dots span"));
    let entered = "";

    function render() {
      value.value = entered;
      dots.forEach(function (dot, i) {
        dot.classList.toggle("is-on", i < entered.length);
      });
    }

    function push(digit) {
      if (entered.length >= 6) return;
      entered += digit;
      render();
    }

    document.querySelectorAll(".key[data-key]").forEach(function (key) {
      key.addEventListener("click", function () {
        const k = key.getAttribute("data-key");
        if (k === "clear") { entered = ""; render(); }
        else push(k);
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key >= "0" && e.key <= "9") push(e.key);
      else if (e.key === "Backspace") { entered = entered.slice(0, -1); render(); }
    });

    render();
  }

  /* --------------------------------------------- reward stock mode rows
     Show only the controls belonging to the selected stock mode. Works for
     any number of reward forms on the page. */
  document.querySelectorAll(".stockbox").forEach(function (box) {
    const radios = box.querySelectorAll('input[name="stock_mode"]');
    const rows = box.querySelectorAll(".stockbox__row");

    function sync() {
      const chosen = box.querySelector('input[name="stock_mode"]:checked');
      const mode = chosen ? chosen.value : "unlimited";
      rows.forEach(function (row) {
        row.classList.toggle("is-shown", row.dataset.when === mode);
      });
    }

    radios.forEach(function (r) { r.addEventListener("change", sync); });
    sync();
  });

  /* ------------------------------------------- notification channel fields
     Show only the fields belonging to the chosen channel type. */
  document.querySelectorAll(".addchan").forEach(function (box) {
    const radios = box.querySelectorAll('input[name="type"]');
    const groups = box.querySelectorAll(".chanfields");

    function sync() {
      const chosen = box.querySelector('input[name="type"]:checked');
      const kind = chosen ? chosen.value : null;
      groups.forEach(function (g) {
        const on = g.dataset.when === kind;
        g.classList.toggle("is-shown", on);
        // Don't submit (or validate) fields for the types you didn't pick.
        g.querySelectorAll("input").forEach(function (i) { i.disabled = !on; });
      });
    }

    radios.forEach(function (r) { r.addEventListener("change", sync); });
    sync();
  });

  /* -------------------------------------------------- Signal group picker
     Group ids are long base64 strings; ask the bridge and let people click. */
  document.querySelectorAll(".grouppick").forEach(function (box) {
    const button = box.querySelector("[data-find-groups]");
    const status = box.querySelector("[data-groups-status]");
    const list = box.querySelector("[data-groups-list]");
    const fields = box.closest(".chanfields");

    function field(name) {
      return fields.querySelector('[name="signal__' + name + '"]');
    }

    button.addEventListener("click", async function () {
      status.textContent = "Asking the bridge\u2026";
      list.hidden = true;
      list.innerHTML = "";

      const body = new URLSearchParams({
        api_url: field("api_url").value.trim(),
        number: field("number").value.trim()
      });

      let data;
      try {
        const res = await fetch(box.dataset.groupsUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": document.querySelector('[name="_csrf"]').value
          },
          body: body
        });
        data = await res.json();
      } catch (err) {
        status.textContent = "Couldn't ask the bridge — is the URL right?";
        return;
      }

      if (data.error) { status.textContent = data.error; return; }

      status.textContent = "Tap one to add it:";
      data.groups.forEach(function (g) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "groupchip";
        chip.textContent = g.name;
        chip.addEventListener("click", function () {
          const input = field("recipients");
          const have = input.value.split(",").map(s => s.trim()).filter(Boolean);
          if (!have.includes(g.id)) have.push(g.id);
          input.value = have.join(", ");
          chip.classList.add("is-added");
        });
        list.appendChild(chip);
      });
      list.hidden = false;
    });
  });

  /* ------------------------------------------------------------- celebrate */
  const toast = document.querySelector("[data-celebrate]");
  if (toast) {
    burst();
    setTimeout(function () {
      toast.classList.add("is-going");
      setTimeout(() => toast.remove(), 400);
    }, 3600);
  }

  function burst() {
    const canvas = document.getElementById("confetti");
    if (!canvas || reduceMotion) return;

    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    ctx.scale(dpr, dpr);
    canvas.style.display = "block";

    const colours = ["#7c4dff", "#ff4d94", "#12d6a0", "#28c8f5", "#ffb300", "#ff7043"];
    const pieces = [];
    const count = window.innerWidth < 600 ? 70 : 120;

    for (let i = 0; i < count; i++) {
      pieces.push({
        x: window.innerWidth / 2 + (Math.random() - 0.5) * 220,
        y: -20 - Math.random() * 120,
        w: 7 + Math.random() * 7,
        h: 9 + Math.random() * 9,
        vx: (Math.random() - 0.5) * 5,
        vy: 2.5 + Math.random() * 4,
        spin: (Math.random() - 0.5) * 0.28,
        angle: Math.random() * Math.PI * 2,
        colour: colours[(Math.random() * colours.length) | 0]
      });
    }

    const started = performance.now();
    (function frame(now) {
      const elapsed = now - started;
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);

      pieces.forEach(function (p) {
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.055;
        p.angle += p.spin;

        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.angle);
        ctx.globalAlpha = elapsed > 2600 ? Math.max(0, 1 - (elapsed - 2600) / 800) : 1;
        ctx.fillStyle = p.colour;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      });

      if (elapsed < 3400) {
        requestAnimationFrame(frame);
      } else {
        ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
        canvas.style.display = "none";
      }
    })(started);
  }

  /* ---------------------------------------------------- service worker */
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function (err) {
        console.warn("ServiceWorker registration failed:", err);
      });
    });
  }

  /* ---------------------------------------------------- install prompt */
  window.addEventListener("beforeinstallprompt", function (e) {
    window.deferredInstallPrompt = e;
  });

  /* ---------------------------------------------------- hash anchor scroll */
  if (window.location.hash) {
    const target = document.querySelector(window.location.hash);
    if (target && window.location.hash.startsWith("#done-")) {
      target.classList.add("pulse");
      setTimeout(function () { target.classList.remove("pulse"); }, 1000);
    }
  }
})();
