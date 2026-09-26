"""Deploy GhostWork to AWS Lambda with a public HTTPS Function URL.

Usage (after `aws login`):
    python scripts/deploy_lambda.py

What it does, in order:
  1. Builds a Linux (manylinux x86_64, Python 3.12) package of requirements.txt
     plus the app code. No Docker needed.
  2. Creates the IAM role and Lambda function on first run, else updates code.
  3. Sets environment variables from .env (allowlist only; .env itself is never
     uploaded), plus a generated REGISTRATION_CODE (invite code) and a strong
     FLASK_SECRET_KEY (signs session cookies). Both are kept across redeploys.
  4. Creates a public Function URL and sets PUBLIC_BASE_URL to it, so Vobiz
     callbacks reach the app. Sign-in (Supabase Auth) protects everything
     except the login pages, /api/health and the token-checked Vobiz routes.

The app runs under waitress behind the AWS Lambda Web Adapter layer.
"""

import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Build outside the repo: OneDrive sync locks files and slows large folders.
BUILD_ROOT = Path(tempfile.gettempdir()) / "ghostwork-lambda-build"
BUILD = BUILD_ROOT / "package"
ZIP_PATH = BUILD_ROOT / "ghostwork-lambda.zip"

FUNCTION = "ghostwork"
ROLE = "ghostwork-lambda-role"
REGION = "ap-south-1"
RUNTIME = "python3.12"
# AWS Lambda Web Adapter 1.1.0 for ap-south-1 (published by AWS).
ADAPTER_LAYER = "arn:aws:lambda:ap-south-1:753240598075:layer:LambdaAdapterLayerX86:30"

APP_DIRS = ["agents", "api", "data", "orchestrator", "routes", "schemas", "services", "static", "templates"]
APP_FILES = ["app.py", "config.py"]

# Only these .env settings are copied to Lambda.
ENV_ALLOWLIST = [
    "SUPABASE_URL", "SUPABASE_KEY", "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
    "SARVAM_API_KEY", "FRESHDESK_PROVIDER", "MCP_FRESHDESK_URL", "MCP_FRESHDESK_AUTH_TOKEN",
    "FRESHDESK_DOMAIN", "FRESHDESK_API_KEY", "FRESHDESK_ALLOW_REST_FALLBACK",
    "FRESHDESK_DEMO_TICKET_ID", "FRESHDESK_REFUND_AMOUNT_FIELD", "FRESHDESK_AUTO_CLOSE",
    "VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN", "VOBIZ_FROM_NUMBER", "APPROVER_PHONE",
    "VOBIZ_DEFAULT_COUNTRY_CODE", "EXECUTOR_TIMEOUT_SECONDS", "SESSION_HOURS",
]
FIXED_ENV = {
    "DB_BACKEND": "supabase",
    "FLASK_DEBUG": "false",
    "FLASK_TESTING": "false",
    # Lambda Web Adapter wiring
    "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap",
    "PORT": "8080",
    "AWS_LWA_READINESS_CHECK_PATH": "/api/health",
}


def aws_exe() -> str:
    found = shutil.which("aws")
    default = Path(r"C:\Program Files\Amazon\AWSCLIV2\aws.exe")
    if found:
        return found
    if default.exists():
        return str(default)
    sys.exit("AWS CLI not found. Install it and run `aws login` first.")


def aws(*args, check=True):
    """Run an AWS CLI command and return parsed JSON (or None)."""
    cmd = [aws_exe(), *args, "--region", REGION, "--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"AWS CLI failed: {' '.join(args[:2])}\n{result.stderr.strip()}")
    if result.returncode != 0:
        return None
    return json.loads(result.stdout) if result.stdout.strip() else {}


def read_dotenv() -> dict:
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"')
    return values


def build_package() -> None:
    print("1/4 Building Linux package...")
    if BUILD.exists():
        # Clear read-only flags (e.g. from pip-installed files) before deleting.
        shutil.rmtree(BUILD, onexc=lambda func, path, _: (Path(path).chmod(0o700), func(path)))
    BUILD.mkdir(parents=True)
    subprocess.run([
        sys.executable, "-m", "pip", "install", "--quiet",
        "-r", str(ROOT / "requirements.txt"), "--target", str(BUILD),
        "--platform", "manylinux2014_x86_64", "--implementation", "cp",
        "--python-version", "3.12", "--only-binary=:all:", "--upgrade",
    ], check=True)
    for name in APP_DIRS:
        shutil.copytree(ROOT / name, BUILD / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in APP_FILES:
        shutil.copy2(ROOT / name, BUILD / name)

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(BUILD).as_posix())
        # run.sh must use LF line endings and be executable on Linux.
        info = zipfile.ZipInfo("run.sh")
        info.external_attr = 0o100755 << 16
        script = (ROOT / "deploy" / "run.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
        zf.writestr(info, script)
    print(f"    package: {ZIP_PATH.stat().st_size / 1_000_000:.1f} MB")


def ensure_role() -> str:
    role = aws("iam", "get-role", "--role-name", ROLE, check=False)
    if role:
        return role["Role"]["Arn"]
    print("    creating IAM role")
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    role = aws("iam", "create-role", "--role-name", ROLE, "--assume-role-policy-document", json.dumps(trust))
    aws("iam", "attach-role-policy", "--role-name", ROLE,
        "--policy-arn", "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    time.sleep(10)  # new roles take a few seconds before Lambda can assume them
    return role["Role"]["Arn"]


def wait_ready() -> None:
    aws("lambda", "wait", "function-updated-v2", "--function-name", FUNCTION)


def deploy_function(role_arn: str) -> dict:
    print("2/4 Deploying function...")
    existing = aws("lambda", "get-function-configuration", "--function-name", FUNCTION, check=False)
    common = ["--timeout", "120", "--memory-size", "1024", "--layers", ADAPTER_LAYER]
    if existing:
        aws("lambda", "update-function-code", "--function-name", FUNCTION, "--zip-file", f"fileb://{ZIP_PATH}")
        wait_ready()
        aws("lambda", "update-function-configuration", "--function-name", FUNCTION,
            "--handler", "run.sh", "--runtime", RUNTIME, *common)
    else:
        aws("lambda", "create-function", "--function-name", FUNCTION, "--runtime", RUNTIME,
            "--role", role_arn, "--handler", "run.sh", "--architectures", "x86_64",
            "--zip-file", f"fileb://{ZIP_PATH}", *common)
    wait_ready()
    return existing or {}


def ensure_function_url() -> str:
    print("3/4 Ensuring public Function URL...")
    url = aws("lambda", "get-function-url-config", "--function-name", FUNCTION, check=False)
    if not url:
        url = aws("lambda", "create-function-url-config", "--function-name", FUNCTION, "--auth-type", "NONE")
    # Public URL invocation needs both permissions (the app enforces its own login).
    aws("lambda", "add-permission", "--function-name", FUNCTION, "--statement-id", "public-url",
        "--action", "lambda:InvokeFunctionUrl", "--principal", "*",
        "--function-url-auth-type", "NONE", check=False)
    aws("lambda", "add-permission", "--function-name", FUNCTION, "--statement-id", "public-url-invoke",
        "--action", "lambda:InvokeFunction", "--principal", "*", check=False)
    return url["FunctionUrl"].rstrip("/")


def set_environment(existing: dict, public_url: str) -> str:
    print("4/4 Setting environment variables...")
    dotenv = read_dotenv()
    current = ((existing.get("Environment") or {}).get("Variables")) or {}

    env = {key: dotenv[key] for key in ENV_ALLOWLIST if dotenv.get(key)}
    env.update(FIXED_ENV)
    env["PUBLIC_BASE_URL"] = public_url
    # Generated once, then kept: changing them would log everyone out / change the invite.
    secret_key = current.get("FLASK_SECRET_KEY", "")
    env["FLASK_SECRET_KEY"] = secret_key if len(secret_key) >= 32 else secrets.token_urlsafe(32)
    env["REGISTRATION_CODE"] = current.get("REGISTRATION_CODE") or secrets.token_urlsafe(9)

    # Pass via a temp file so no secret appears on the command line.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump({"Variables": env}, handle)
        env_file = handle.name
    try:
        aws("lambda", "update-function-configuration", "--function-name", FUNCTION,
            "--environment", f"file://{env_file}")
    finally:
        Path(env_file).unlink(missing_ok=True)
    wait_ready()
    print(f"    set {len(env)} variables (values not printed)")
    return env["REGISTRATION_CODE"] if not current.get("REGISTRATION_CODE") else ""


def main() -> None:
    identity = aws("sts", "get-caller-identity")
    print(f"Deploying to account {identity['Account']} in {REGION}")
    build_package()
    existing = deploy_function(ensure_role())
    public_url = ensure_function_url()
    new_code = set_environment(existing, public_url)

    print("\nDeployed.")
    print(f"  URL:         {public_url}")
    print(f"  Register:    {public_url}/register")
    print(f"  Webhook:     {public_url}/api/webhooks/vobiz")
    if new_code:
        print(f"  Invite code: {new_code}   (shown once; also in the Lambda console env vars)")
    else:
        print("  Invite code: unchanged from the previous deploy")


if __name__ == "__main__":
    main()
