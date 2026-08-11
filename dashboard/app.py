"""FP-A Dash app entrypoint.

Usage (from the repo root, with the project venv active):
    python dashboard/app.py
"""

import dash

import callbacks
import layout
from fpna import db, workflow
from fpna.seed import run_seed


def create_app() -> dash.Dash:
    conn = run_seed()
    # So the mirror file (db/fpna.mirror.duckdb) exists right away instead of
    # only after the first 5s callbacks.sync_mirror_tick - see db.sync_mirror.
    # sync_mirror can legitimately skip (e.g. a viewer tool has the mirror
    # file open right now, blocking the atomic swap) - printed here so that
    # shows up at startup instead of only as a silent no-op.
    if not db.sync_mirror(conn):
        print("Mirror copy not refreshed yet - mirror file is open elsewhere; will keep retrying every 5s.")

    app = dash.Dash(__name__, title="FP-A — طراح گردش‌کار بودجه‌ریزی", suppress_callback_exceptions=True)
    # Dash's default index_string leaves <html> without a lang/dir - set
    # both here (once, at the real <html> tag) rather than relying solely on
    # #fpa-app-root's own dir="rtl" (layout.build_shell), so RTL is correct
    # even before/outside that div (browser chrome, view-source, a11y tools).
    app.index_string = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""

    def serve_layout():
        # A *function*, not a resolved value: unlike XP-A's dimension
        # dropdown options (static reference data), the workflow steps
        # rendered here change on every Save, so app.layout must be
        # recomputed fresh on every new page load - assigning a plain value
        # here would freeze every future page load to whatever the DB looked
        # like at server-start time.
        versions = workflow.list_versions(conn)
        if not versions:
            workflow.create_version(conn, "گردش‌کار جدید")
            versions = workflow.list_versions(conn)
        selected_version_id = versions[0]["version_id"]
        selected_version = workflow.get_version(conn, selected_version_id)
        roles = workflow.list_roles(conn)
        instances = workflow.list_instances(conn, selected_version_id)
        return layout.build_shell(roles, versions, selected_version, instances)

    app.layout = serve_layout
    callbacks.register_callbacks(app, conn)
    return app


if __name__ == "__main__":
    dash_app = create_app()
    # Same reasoning as XP-A: one shared DuckDB connection means the server
    # must not be threaded, and the reloader would spawn a second process
    # trying to open the same file.
    dash_app.run(debug=True, use_reloader=False, threaded=False)
