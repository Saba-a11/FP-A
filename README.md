# FP-A — Budgeting Workflow Designer

A sister project to [XP-A](../XP-A) (same dark visual system, same
Python/DuckDB/Dash stack), built step by step at the user's direction
rather than from a fixed roadmap. This is **Step 1**: a drag-and-drop
designer for a budgeting approval workflow.

## What's built so far

- **A visual workflow canvas.** A palette of roles (Preparer, Department
  Head, Finance Reviewer, Controller, CFO by default) that you drag onto a
  canvas to build an ordered sequence of steps. Drag an existing step to
  reorder it, drag it onto the trash (or click its **×**) to remove it.
- **Versioned, editable templates.** Every workflow design is a row in
  `workflow_version` (Draft or Active), with its ordered steps in
  `workflow_step`. Saving replaces the whole step list for that version -
  there's no per-step patch history, the version itself is the unit of
  history (create a new version to keep an old design intact).
- **Running instances with a current-step pointer.** A workflow *instance*
  (e.g. "FY2027 Annual Budget") is a real run of a version's template,
  tracking which step it's currently sitting at. Click a step under an
  instance to mark it as current; earlier steps show as done, the current
  one is highlighted.
- **Roles are extensible.** Add a new role from the sidebar; it's assigned
  the next color in the same 5-hue palette XP-A itself uses.

## Why this tech, not something else

Prompted to consider alternatives before building, here's the reasoning:

- **Dash (Python), not a JS framework (React Flow, etc.):** Node.js isn't
  available in this environment (confirmed missing when XP-A hit the same
  question), and a JS build pipeline would break the "look and feel exactly
  like XP-A" requirement, since XP-A is Dash too. Dash was kept.
- **Real drag-and-drop still needed real JS.** Dash has no built-in
  "drag a card from a palette onto a canvas" primitive, and `dash-cytoscape`
  is built for general graphs, not a simple linear step sequence. Rather
  than fake it with click-to-add buttons, `dashboard/assets/dragdrop.js` is
  a small, dependency-free file using the native HTML5 Drag and Drop API -
  no build step, no npm, just a script Dash serves like any other asset.
- **DuckDB, versioned the same way XP-A does Budget/Forecast.** One
  file, no server process, the same "a version is a row, not an overwrite"
  discipline as `xpna.budget_version`.

## A real bug this surfaced (and the fix)

Mixing hand-written DOM mutation with a React-based framework (Dash) on the
*same* DOM node crashed with `Failed to execute 'removeChild': the node to
be removed is not a child of this node` the first time a Save happened
after a drag edit. The fix, and the reason it's structured this way:
**Dash and the drag-and-drop JS never touch the same element.** Dash only
ever writes to a hidden `#fpa-steps-payload` div (`data-steps` as JSON);
`dragdrop.js` is the only thing that ever renders into the visible
`#fpa-canvas`, watching the payload with a `MutationObserver`. See the
docstring on `layout.build_steps_payload` for the full explanation.

A second real bug, also fixed: `app.layout` was first assigned as a plain
value computed once at server startup, so every new page load kept showing
whatever the database looked like at that moment - editing steps and then
opening a second tab (or reloading) showed stale, pre-edit data. `app.layout`
must be a **function** so Dash recomputes it per page load; see the comment
in `dashboard/app.py`.

## Project layout

```
FP-A/
  sql/schema.sql          dim_role, workflow_version, workflow_step, workflow_instance
  data/seed/roles.csv     the 5 default roles
  src/fpna/
    config.py             paths
    db.py                 DuckDB connection helper (ported from xpna.db)
    seed.py                builds the schema, loads default roles
    workflow.py            all CRUD: roles, versions, steps, instances
  dashboard/
    app.py                 Dash entrypoint - app.layout is a function, see above
    layout.py               page layout + render helpers shared with callbacks
    callbacks.py             version switch/create/activate, save, roles, instances
    assets/
      style.css             ported from XP-A almost verbatim, plus canvas-specific rules
      dragdrop.js            the drag-and-drop engine (vanilla JS, no dependencies)
  tests/test_workflow.py   11 tests covering the CRUD layer, including the
                           dangling-current-step-after-edit case
```

## Running it

```powershell
cd "D:\S A B A\Projects\FP-A"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt -e .
.\.venv\Scripts\python dashboard\app.py
```

Then open http://127.0.0.1:8050.

## Testing

```powershell
.\.venv\Scripts\python -m pytest tests\ -v
```

## Known tradeoffs (not bugs — deliberate, for this step's scope)

- **Editing a version resets every instance's current-step progress back to
  the new first step**, even if the edit didn't touch that instance's
  step. `save_steps` deletes and reinserts every step row (simplest correct
  way to persist a drag-and-drop reorder), so old step ids never survive an
  edit. `current_step_id` is deliberately not a hard foreign key for exactly
  this reason - see the comment in `sql/schema.sql`.
- **No git repository yet** - not initialized, since that wasn't asked for.
- **No login/access control, single user** - same scope decision XP-A made.

## What's not built yet

Whatever the next step turns out to be - this was scoped to exactly what
was asked for (the drag-and-drop designer, versioning, and current-step
tracking), not a guess at the rest of the roadmap.
