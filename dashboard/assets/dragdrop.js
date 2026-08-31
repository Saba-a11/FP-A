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
 *
 * STAGES (parallel branches). Each step carries a `stage` number, and every
 * step sharing a stage is one column on the canvas - they all run at once,
 * and the next column can't start until every chip in this one is approved
 * (see sql/schema.sql and workflow.instance_progress). The canvas therefore
 * renders columns, not a single row, and offers two kinds of drop target:
 *
 *   .fpa-stage  - drop here to add a parallel branch to THIS column
 *   .fpa-gap    - drop here to open a NEW column at this position
 *
 * A plain linear workflow is just the case where every column holds one
 * chip, so nothing about the old behaviour had to change for the user.
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

  // Groups the flat step array into one array per stage. Relies on the array
  // already being stage-sorted, which normalize() below guarantees after
  // every mutation.
  function stageGroups() {
    var groups = [];
    var currentStage = null;
    window.__fpaSteps.forEach(function (step) {
      if (step.stage !== currentStage) {
        groups.push([]);
        currentStage = step.stage;
      }
      groups[groups.length - 1].push(step);
    });
    return groups;
  }

  // Re-sorts by stage and rewrites stage/lane to a dense 0..n-1 so the array
  // is always in canonical form - callers only have to place a chip roughly
  // ("stage 2.5" to mean between 2 and 3 is not allowed, they shift instead)
  // and never have to think about gaps left by a removed column.
  // Array.prototype.sort is stable (ES2019), so chips inside one stage keep
  // the relative order they were given.
  function normalize() {
    window.__fpaSteps.sort(function (a, b) {
      return a.stage - b.stage;
    });
    var flat = [];
    stageGroups().forEach(function (group, stageIndex) {
      group.forEach(function (step, lane) {
        step.stage = stageIndex;
        step.lane = lane;
        flat.push(step);
      });
    });
    window.__fpaSteps = flat;
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
    window.__fpaSteps = parsed.map(function (s, index) {
      return {
        key: "s" + s.step_id,
        role_id: s.role_id,
        role_name: s.role_name,
        color_hex: s.color_hex,
        label: s.label,
        // A payload from before stages existed carries no `stage` - falling
        // back to the chip's index reproduces the old one-per-column linear
        // layout exactly, so nothing breaks on an old design.
        stage: s.stage == null ? index : s.stage,
        lane: s.lane == null ? 0 : s.lane,
      };
    });
    normalize();
    render();
  }

  function chipHtml(step) {
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
      '<span class="fpa-role-badge">' + escapeHtml(badgeInitial) + "</span>" +
      "<span>" + escapeHtml(step.label) + "</span>" +
      '<button type="button" class="fpa-remove" data-key="' + escapeHtml(step.key) + '" title="حذف مرحله">×</button>' +
      "</div>"
    );
  }

  // The "open a NEW stage here" target between two columns. Rendered as a
  // permanently visible dashed lane rather than a bare hairline: the first
  // version of this was an 18px gap showing only an arrow, and the boundary
  // between one stage and the next was invisible - there was no way to tell
  // where to drop for "runs after" versus "runs alongside".
  function gapHtml(gapIndex) {
    return (
      '<div class="fpa-gap" data-gap="' + gapIndex + '" title="نقش را اینجا رها کنید تا یک مرحله‌ی جدید ساخته شود">' +
      '<div class="fpa-gap-line"></div>' +
      '<div class="fpa-gap-badge">+</div>' +
      '<div class="fpa-gap-label">مرحله‌ی جدید</div>' +
      '<div class="fpa-gap-line"></div>' +
      "</div>"
    );
  }

  function stageHtml(group, stageIndex) {
    var isParallel = group.length > 1;
    var parts = [
      '<div class="fpa-stage' + (isParallel ? " fpa-stage-parallel" : "") + '" data-stage="' + stageIndex + '">',
      '<div class="fpa-stage-head">',
      '<span class="fpa-stage-num">مرحله ' + (stageIndex + 1) + "</span>",
      isParallel ? '<span class="fpa-stage-tag">همزمان · ' + group.length + " نفر</span>" : "",
      "</div>",
      '<div class="fpa-stage-body">',
    ];
    group.forEach(function (step) {
      parts.push(chipHtml(step));
    });
    // The explicit "add to THIS stage" target. Always present, so joining an
    // existing stage is a visible affordance rather than something you have
    // to guess by aiming at a column.
    parts.push(
      '<div class="fpa-stage-drop">+ افزودن نقش به این مرحله<span class="fpa-stage-drop-sub">همزمان با بقیه</span></div>'
    );
    parts.push("</div>");
    if (isParallel) {
      parts.push('<div class="fpa-stage-note">هر ' + group.length + ' نفر باید تایید کنند</div>');
    }
    parts.push("</div>");
    return parts.join("");
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
    var groups = stageGroups();
    parts.push(gapHtml(0));
    groups.forEach(function (group, stageIndex) {
      parts.push(stageHtml(group, stageIndex));
      parts.push(gapHtml(stageIndex + 1));
    });
    canvas.innerHTML = parts.join("");
    fitCanvas();
  }

  // Below this the flow would be unreadable, so rather than shrink further
  // the viewport gives up and scrolls - a deliberate last resort for an
  // extreme design (roughly 14+ stages on a normal screen), not the normal
  // path. Everything realistic fits above it: a 7-stage workflow lands
  // around 0.55.
  var FPA_MIN_SCALE = 0.35;

  // Scale the whole flow down until it fits the available width, so every
  // stage stays visible on one line instead of running off behind a
  // scrollbar. Measures at scale 1 first, because scrollWidth of an already
  // transformed element still reports layout (untransformed) size in some
  // engines and reading it mid-transform makes the result drift on repeated
  // calls.
  function fitCanvas() {
    var viewport = document.getElementById("fpa-canvas-viewport");
    var scaler = document.getElementById("fpa-canvas-scaler");
    if (!viewport || !scaler) return;

    scaler.style.transform = "none";
    scaler.style.width = "max-content";
    var naturalWidth = scaler.scrollWidth;
    var naturalHeight = scaler.scrollHeight;
    var available = viewport.clientWidth;
    if (!naturalWidth || !available) return;

    var scale = available / naturalWidth;
    if (scale >= 1) {
      scale = 1;
    } else if (scale < FPA_MIN_SCALE) {
      scale = FPA_MIN_SCALE;
    }

    scaler.style.transform = scale === 1 ? "none" : "scale(" + scale + ")";
    // The transform is purely visual - it does not change layout size - so
    // the viewport would otherwise keep reserving the full untransformed
    // height and leave a gap under the flow.
    viewport.style.height = Math.ceil(naturalHeight * scale) + "px";
    viewport.style.overflowX = naturalWidth * scale > available + 1 ? "auto" : "hidden";
  }

  window.addEventListener("resize", function () {
    // Coalesce the burst of resize events a window drag produces into one
    // measure-and-scale pass per frame.
    if (window.__fpaFitPending) return;
    window.__fpaFitPending = true;
    window.requestAnimationFrame(function () {
      window.__fpaFitPending = false;
      fitCanvas();
    });
  });

  function pushToStore() {
    if (!(window.dash_clientside && window.dash_clientside.set_props)) return;
    // `key` rides along so Python's save_steps can tell "this chip is
    // still the same step it was before" (key "s<id>") from "this is a
    // brand-new chip" (key "new_...") - that's what lets a saved step's
    // owner/duty/template survive a re-save instead of being wiped every
    // time the canvas changes. See workflow.save_steps.
    var payload = window.__fpaSteps.map(function (s) {
      return { role_id: s.role_id, label: s.label, key: s.key, stage: s.stage, lane: s.lane };
    });
    window.dash_clientside.set_props("workflow-steps-store", { data: payload });
  }

  function commit() {
    normalize();
    render();
    pushToStore();
  }

  function keyIndex(key) {
    for (var i = 0; i < window.__fpaSteps.length; i++) {
      if (window.__fpaSteps[i].key === key) return i;
    }
    return -1;
  }

  // Makes room for a brand-new column at `gapIndex` by pushing every stage
  // from there on one to the right. The caller then places its chip at
  // exactly `gapIndex`, and normalize() closes any numbering gap.
  function shiftStagesFrom(gapIndex) {
    window.__fpaSteps.forEach(function (step) {
      if (step.stage >= gapIndex) step.stage += 1;
    });
  }

  // Where did this drop land? Returns {type: "stage", index} for a drop onto
  // an existing column (add a parallel branch), or {type: "gap", index} for
  // a drop between columns (open a new one), or null if neither.
  function dropTargetFrom(event) {
    if (!event.target.closest) return null;
    var gap = event.target.closest(".fpa-gap");
    if (gap) return { type: "gap", index: parseInt(gap.getAttribute("data-gap"), 10) };
    var stage = event.target.closest(".fpa-stage");
    if (stage) return { type: "stage", index: parseInt(stage.getAttribute("data-stage"), 10) };
    // Dropped on the dropzone but not on any specific target (e.g. the empty
    // canvas, or the padding around the columns) - append as a new last
    // stage, which is what "just drop it on the canvas" should obviously do.
    if (event.target.closest("#fpa-canvas-dropzone")) {
      return { type: "gap", index: stageGroups().length };
    }
    return null;
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
    document.querySelectorAll(".fpa-chip.fpa-dragging").forEach(function (el) {
      el.classList.remove("fpa-dragging");
    });
    clearDropHighlights();
  });

  function clearDropHighlights() {
    document.querySelectorAll(".fpa-drag-over").forEach(function (el) {
      el.classList.remove("fpa-drag-over");
    });
  }

  document.addEventListener("dragover", function (e) {
    var dropzone = e.target.closest ? e.target.closest("#fpa-canvas-dropzone") : null;
    var trash = e.target.closest ? e.target.closest("#fpa-trash-zone") : null;
    if (!dropzone && !trash) return;
    e.preventDefault();
    clearDropHighlights();
    if (trash) {
      trash.classList.add("fpa-drag-over");
      return;
    }
    // Highlight the specific column or gap under the cursor, not the whole
    // canvas - with parallel stages the user needs to see *which* column a
    // chip is about to join, since that is the difference between "runs
    // alongside these people" and "runs after them".
    var target = dropTargetFrom(e);
    if (!target) return;
    var selector = target.type === "gap" ? ".fpa-gap[data-gap='" : ".fpa-stage[data-stage='";
    var el = document.querySelector(selector + target.index + "']");
    if (el) el.classList.add("fpa-drag-over");
    else dropzone.classList.add("fpa-drag-over");
  });

  document.addEventListener("dragleave", function (e) {
    if (e.target.classList && e.target.classList.contains("fpa-drag-over")) {
      e.target.classList.remove("fpa-drag-over");
    }
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
    clearDropHighlights();

    if (trash) {
      if (data.source === "canvas") {
        var trashIndex = keyIndex(data.key);
        if (trashIndex !== -1) {
          pushHistory();
          window.__fpaSteps.splice(trashIndex, 1);
          commit();
        }
      }
      return;
    }

    var target = dropTargetFrom(e);
    if (!target) return;

    if (data.source === "palette") {
      pushHistory();
      if (target.type === "gap") shiftStagesFrom(target.index);
      window.__fpaSteps.push({
        key: newKey(),
        role_id: data.role_id,
        role_name: data.role_name,
        color_hex: data.color_hex,
        label: data.role_name,
        stage: target.index,
        lane: 999, // sorted into place by normalize() - appends to the column
      });
      commit();
    } else if (data.source === "canvas") {
      var fromIndex = keyIndex(data.key);
      if (fromIndex === -1) return;
      pushHistory();
      var moved = window.__fpaSteps.splice(fromIndex, 1)[0];
      if (target.type === "gap") shiftStagesFrom(target.index);
      moved.stage = target.index;
      moved.lane = 999;
      window.__fpaSteps.push(moved);
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
    // The very first paint comes from Dash (layout.build_canvas_children),
    // not from render(), so nothing has called fitCanvas() for it yet.
    fitCanvas();
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
