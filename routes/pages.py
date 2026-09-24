"""HTML page routes for the GhostWork UI."""

from flask import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/", methods=["GET"])
def index():
    """Discovery dashboard (landing page)."""
    return render_template("discovery.html", page_name="discovery")


@pages_bp.route("/workflow/<int:workflow_id>", methods=["GET"])
def workflow_detail(workflow_id: int):
    """Workflow detail page with GhostGraph and GhostScore breakdown."""
    return render_template("workflow_detail.html", workflow_id=workflow_id, page_name="discovery")


@pages_bp.route("/execution", methods=["GET"])
def execution_view():
    """Execution view page for running workflows."""
    from flask import request
    execution_id = request.args.get("id", "")
    return render_template("execution.html", execution_id=execution_id, page_name="executions")


@pages_bp.route("/executions", methods=["GET"])
def executions_list():
    """List of all executions."""
    return render_template("executions.html", page_name="executions")


@pages_bp.route("/integrations", methods=["GET"])
def integrations_view():
    """Integration status page."""
    return render_template("integrations.html", page_name="integrations")
