"""HTML page routes for the GhostWork UI."""

from flask import Blueprint, redirect, render_template, request, url_for

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/", methods=["GET"])
def index():
    """Operations overview using live discovery and execution data."""
    return render_template("dashboard.html", page_name="dashboard")


@pages_bp.route("/workflows", methods=["GET"])
def workflows_view():
    """Discovered workflows and their Freshdesk tickets."""
    return render_template("discovery.html", page_name="workflows")


@pages_bp.route("/approvals", methods=["GET"])
def approvals_view():
    """Approval queue derived from execution state."""
    return render_template("approvals.html", page_name="approvals")


@pages_bp.route("/workflow/<int:workflow_id>", methods=["GET"])
def workflow_detail(workflow_id: int):
    """Workflow detail page."""
    return render_template("workflow_detail.html", workflow_id=workflow_id, page_name="workflows")


@pages_bp.route("/privacy", methods=["GET"])
def privacy_view():
    return render_template("legal.html", page_name="", legal_title="Privacy Policy", legal_kind="privacy")


@pages_bp.route("/terms", methods=["GET"])
def terms_view():
    return render_template("legal.html", page_name="", legal_title="Terms of Service", legal_kind="terms")


@pages_bp.route("/execution", methods=["GET"])
def execution_view():
    """Execution view page for running workflows."""
    execution_id = request.args.get("id", type=int)
    if not execution_id or execution_id < 1:
        return redirect(url_for("pages.executions_list"))
    return render_template("execution.html", execution_id=execution_id, page_name="executions")


@pages_bp.route("/execution/<int:execution_id>", methods=["GET"])
def execution_detail(execution_id: int):
    """Execution detail URL used by the original workflow page."""
    if execution_id < 1:
        return redirect(url_for("pages.executions_list"))
    return render_template("execution.html", execution_id=execution_id, page_name="executions")


@pages_bp.route("/executions", methods=["GET"])
def executions_list():
    """List of all executions."""
    return render_template("executions.html", page_name="executions")


@pages_bp.route("/integrations", methods=["GET"])
def integrations_view():
    """Integration status page."""
    return render_template("integrations.html", page_name="integrations")
