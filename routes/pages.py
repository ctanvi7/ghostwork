"""HTML page routes for the GhostWork UI."""

from flask import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/", methods=["GET"])
def index():
    """Dashboard page."""
    return render_template("dashboard.html")


@pages_bp.route("/workflow/<int:workflow_id>", methods=["GET"])
def workflow_detail(workflow_id: int):
    """Workflow detail page."""
    return render_template("workflow.html", workflow_id=workflow_id)


@pages_bp.route("/execution/<int:execution_id>", methods=["GET"])
def execution_view(execution_id: int):
    """Execution view page."""
    return render_template("execution.html", execution_id=execution_id)
