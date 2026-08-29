/* Vanilla-JS drag-and-drop for the workflow canvas - no build step, no
 * Node.js, works with plain <script> served from assets/ like any other
 * Dash asset.
 *
 * Ownership split (important - this is what keeps React/Dash from ever
 * crashing over this canvas): Dash/React only ever renders and updates the
 * *hidden* #fpa-steps-payload element (a JSON blob in data-steps). This
 * script is the ONLY thing that ever writes to #fpa-canvas's real DOM -
 * on every drag, reorder, remove, and on every server-side change (version
 * switch, Save), by re-reading the payload. Two different pieces of code
 * mutating the very same DOM node is what caused
 * "Failed to execute 'removeChild': the node to be removed is not a child
 * of this node" during development - splitting who-owns-what fixed it.
 *
 * Source of truth while editing lives in window.__fpaSteps (a plain JS
 * array). dash_clientside.set_props() pushes a serializable copy into the
 * workflow-steps-store any time it changes, so the "Save Changes" button's
 * Python callback can read it as normal Dash State.
 */

(function () {
  "use strict";

  window.__fpaSteps = window.__fpaSteps || [];
  window.__fpaLoadedToken = window.__fpaLoadedToken || null;
  window.__fpaHistory = window.__fpaHistory || [];
  var __fpaKeyCounter = 0;
  var FPA_HISTORY_LIMIT = 20;

  function newKey() {
    __fpaKeyCounter += 1;
    return "new_" + __fpaKeyCounter + "_" + Date.now();
  }

  // Undo support: a snapshot pushed right before each mutation (add,
  // remove, reorder), never after - see the click/drop handlers below.
  // Deep-copied (not a reference) so later mutations to __fpaSteps can
  // never retroactively change an already-pushed snapshot.
  function pushHistory() {
    window.__fpaHistory.push(JSON.parse(JSON.stringify(window.__fpaSteps)));
    if (window.__fpaHistory.length > FPA_HISTORY_LIMIT) window.__fpaHistory.shift();
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  // Re-read the authoritative payload whenever Dash has changed it (version
  // switch, create, activate, or Save all update its data-version-id/
  // data-steps together) and repaint #fpa-canvas from it.
  function syncFromServerIfNeeded() {
    var payload = document.getElementById("fpa-steps-payload");
    if (!payload) return;
    var token = payload.getAttribute("data-version-id");
    if (token === window.__fpaLoadedToken) return;

    window.__fpaLoadedToken = token;
    // A server-driven change (version switch, Save, etc.) invalidates
    // whatever local undo history there was - those snapshots refer to
    // step keys/positions from a canvas that no longer exists once the
    // server has replaced it.
    window.__fpaHistory = [];
    var raw = payload.getAttribute("data-steps") || "[]";
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      parsed = [];
    }
    window.__fpaSteps = parsed.map(function (s) {
      return {
        key: "s" + s.step_id,
        role_id: s.role_id,
        role_name: s.role_name,
        color_hex: s.color_hex,
        label: s.label,
      };
    });
    render();
  }

  function chipHtml(step, index) {
    // Mirrors layout.build_canvas_children's markup exactly (neutral card +
    // --role-color custom property + .fpa-role-badge showing the role's
    // initial) - the two must never drift apart, since this is what
    // repaints the canvas on every client-side drag/reorder between saves.
    var badgeInitial = (step.role_name || step.label || "").slice(0, 1);
    return (
      '<div class="fpa-chip" draggable="true" style="--role-color:' +
      escapeHtml(step.color_hex) +
      '" data-key="' +
      escapeHtml(step.key) +
      '" data-role-id="' +
      escapeHtml(step.role_id) +
      '" data-role-name="' +
      escapeHtml(step.role_name) +
      '" data-color="' +
      escapeHtml(step.color_hex) +
      '" data-label="' +
      escapeHtml(step.label) +
      '">' +
      '<span class="fpa-step-index">' + (index + 1) + "</span>" +
      '<span class="fpa-role-badge">' + escapeHtml(badgeInitial) + "</span>" +
      "<span>" + escapeHtml(step.label) + "</span>" +
      '<button type="button" class="fpa-remove" data-key="' + escapeHtml(step.key) + '" title="حذف مرحله">×</button>' +
      "</div>"
    );
  }

  function render() {
    var canvas = document.getElementById("fpa-canvas");
    if (!canvas) return;
    if (window.__fpaSteps.length === 0) {
      canvas.innerHTML =
        '<div class="fpa-canvas-empty"><div class="fpa-plus">+</div><div>یک نقش را اینجا بکشید تا اولین مرحله اضافه شود</div></div>';
      return;
    }
    var parts = [];
    window.__fpaSteps.forEach(function (step, i) {
      if (i > 0) parts.push('<span class="fpa-arrow">→</span>');
      parts.push(chipHtml(step, i));
    });
    canvas.innerHTML = parts.join("");
  }

  function pushToStore() {
    if (!(window.dash_clientside && window.dash_clientside.set_props)) return;
    // `key` rides along so Python's save_steps can tell "this chip is
    // still the same step it was before" (key "s<id>") from "this is a
    // brand-new chip" (key "new_...") - that's what lets a saved step's
    // owner/duty/template survive a re-save instead of being wiped every
    // time the canvas changes. See workflow.save_steps.
    var payload = window.__fpaSteps.map(function (s) {
      return { role_id: s.role_id, label: s.label, key: s.key };
    });
    window.dash_clientside.set_props("workflow-steps-store", { data: payload });
  }

  function commit() {
    render();
    pushToStore();
  }

  // Index among the CURRENT chips (excluding the one being dragged, if any)
  // that a horizontal mouse position falls into, based on each chip's
  // midpoint - the standard "insert between the two nearest chips" rule.
  function dropIndexForX(clientX, excludeKey) {
    var canvas = document.getElementById("fpa-canvas");
    var chips = canvas ? Array.prototype.slice.call(canvas.querySelectorAll(".fpa-chip")) : [];
    var visibleIndex = 0;
    for (var i = 0; i < chips.length; i++) {
      var chip = chips[i];
      if (excludeKey && chip.getAttribute("data-key") === excludeKey) continue;
      var rect = chip.getBoundingClientRect();
      var midpoint = rect.left + rect.width / 2;
      if (clientX < midpoint) {
        return visibleIndex;
      }
      visibleIndex += 1;
    }
    return visibleIndex;
  }

  function keyIndex(key) {
    for (var i = 0; i < window.__fpaSteps.length; i++) {
      if (window.__fpaSteps[i].key === key) return i;
    }
    return -1;
  }

  document.addEventListener("dragstart", function (e) {
    var paletteChip = e.target.closest ? e.target.closest(".fpa-role-chip") : null;
    var canvasChip = e.target.closest ? e.target.closest(".fpa-chip") : null;
    if (paletteChip) {
      var payload = {
        source: "palette",
        role_id: parseInt(paletteChip.getAttribute("data-role-id"), 10),
        role_name: paletteChip.getAttribute("data-role-name") || "",
        color_hex: paletteChip.getAttribute("data-color") || "#8b5cf6",
      };
      e.dataTransfer.setData("application/json", JSON.stringify(payload));
      e.dataTransfer.effectAllowed = "copy";
    } else if (canvasChip) {
      var key = canvasChip.getAttribute("data-key");
      e.dataTransfer.setData("application/json", JSON.stringify({ source: "canvas", key: key }));
      e.dataTransfer.effectAllowed = "move";
      canvasChip.classList.add("fpa-dragging");
    }
  });

  document.addEventListener("dragend", function () {
    var dragging = document.querySelectorAll(".fpa-chip.fpa-dragging");
    dragging.forEach(function (el) {
      el.classList.remove("fpa-dragging");
    });
  });

  document.addEventListener("dragover", function (e) {
    var dropzone = e.target.closest ? e.target.closest("#fpa-canvas-dropzone") : null;
    var trash = e.target.closest ? e.target.closest("#fpa-trash-zone") : null;
    if (dropzone || trash) {
      e.preventDefault();
      if (dropzone) dropzone.classList.add("fpa-drag-over");
      if (trash) trash.classList.add("fpa-drag-over");
    }
  });

  document.addEventListener("dragleave", function (e) {
    var dropzone = document.getElementById("fpa-canvas-dropzone");
    var trash = document.getElementById("fpa-trash-zone");
    if (dropzone && e.target === dropzone) dropzone.classList.remove("fpa-drag-over");
    if (trash && e.target === trash) trash.classList.remove("fpa-drag-over");
  });

  document.addEventListener("drop", function (e) {
    var dropzone = e.target.closest ? e.target.closest("#fpa-canvas-dropzone") : null;
    var trash = e.target.closest ? e.target.closest("#fpa-trash-zone") : null;
    if (!dropzone && !trash) return;
    e.preventDefault();

    var raw = e.dataTransfer.getData("application/json");
    var data;
    try {
      data = JSON.parse(raw);
    } catch (err) {
      return;
    }

    var dz = document.getElementById("fpa-canvas-dropzone");
    var tz = document.getElementById("fpa-trash-zone");
    if (dz) dz.classList.remove("fpa-drag-over");
    if (tz) tz.classList.remove("fpa-drag-over");

    if (trash) {
      if (data.source === "canvas") {
        var idx = keyIndex(data.key);
        if (idx !== -1) {
          pushHistory();
          window.__fpaSteps.splice(idx, 1);
          commit();
        }
      }
      return;
    }

    if (data.source === "palette") {
      pushHistory();
      var insertAt = dropIndexForX(e.clientX, null);
      window.__fpaSteps.splice(insertAt, 0, {
        key: newKey(),
        role_id: data.role_id,
        role_name: data.role_name,
        color_hex: data.color_hex,
        label: data.role_name,
      });
      commit();
    } else if (data.source === "canvas") {
      var fromIndex = keyIndex(data.key);
      if (fromIndex === -1) return;
      pushHistory();
      var target = dropIndexForX(e.clientX, data.key);
      var moved = window.__fpaSteps.splice(fromIndex, 1)[0];
      if (target > fromIndex) target -= 1;
      window.__fpaSteps.splice(target, 0, moved);
      commit();
    }
  });

  document.addEventListener("click", function (e) {
    var undoBtn = e.target.closest ? e.target.closest("#fpa-undo-btn") : null;
    if (undoBtn) {
      // Pure client-side, like the rest of the canvas - nothing here is
      // persisted until "ذخیره‌ی تغییرات" is clicked, so undo is just
      // "restore the previous in-memory snapshot," no server round-trip.
      if (window.__fpaHistory.length > 0) {
        window.__fpaSteps = window.__fpaHistory.pop();
        commit();
      }
      return;
    }

    var removeBtn = e.target.closest ? e.target.closest(".fpa-remove") : null;
    if (!removeBtn) return;
    var key = removeBtn.getAttribute("data-key");
    var idx = keyIndex(key);
    if (idx !== -1) {
      pushHistory();
      window.__fpaSteps.splice(idx, 1);
      commit();
    }
  });

  function boot() {
    syncFromServerIfNeeded();
    var root = document.getElementById("fpa-app-root");
    if (root) {
      // Observes #fpa-app-root (subtree: true), not #fpa-steps-payload
      // itself, on purpose: switching sidebar modules away from "workflow"
      // and back makes React unmount and recreate the whole page-content
      // subtree, including a brand-new #fpa-steps-payload node - an
      // observer bound to the old node would silently stop firing forever
      // once that node's gone, since detaching it isn't itself a tracked
      // mutation. A subtree observer on the one div that's never replaced
      // catches the new node's attributes too;
      // syncFromServerIfNeeded() already re-queries the element fresh by
      // id on every call, so it doesn't care which node the mutation
      // report came from.
      new MutationObserver(syncFromServerIfNeeded).observe(root, {
        attributes: true,
        attributeFilter: ["data-version-id", "data-steps"],
        subtree: true,
      });
    } else {
      // Root not mounted yet (Dash still hydrating) - retry shortly.
      setTimeout(boot, 150);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
