"""Sign-in, registration, and sign-out pages."""

import logging

from flask import Blueprint, redirect, render_template, request, session, url_for

from services.auth_service import AuthError, authenticate, register, registration_open

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


def _safe_next(target: str) -> str:
    """Only allow local paths, so ?next= cannot redirect to another site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def _start_session(user: dict) -> None:
    session.clear()  # new session on sign-in
    session.permanent = True
    session["user"] = user


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = _safe_next(request.values.get("next", "/"))
    if session.get("user") and request.method == "GET":
        return redirect(next_url)

    error = None
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "")
        user = authenticate(email, request.form.get("password", ""))
        if user:
            _start_session(user)
            logger.info("User signed in", extra={"user_id": user["id"]})
            return redirect(next_url)
        error = "Incorrect email or password."

    return render_template("login.html", error=error, email=email, next_url=next_url,
                           registration_open=registration_open()), (401 if error else 200)


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    error = None
    form = {"name": "", "email": ""}
    if request.method == "POST":
        form = {"name": request.form.get("name", ""), "email": request.form.get("email", "")}
        password = request.form.get("password", "")
        if password != request.form.get("confirm_password", ""):
            error = "Passwords do not match."
        else:
            try:
                user = register(form["name"], form["email"], password, request.form.get("invite_code", ""))
                _start_session(user)
                return redirect("/")
            except AuthError as e:
                error = str(e)

    return render_template("register.html", error=error, form=form,
                           registration_open=registration_open()), (400 if error else 200)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
