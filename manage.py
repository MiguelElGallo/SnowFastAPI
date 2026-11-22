"""Prepare and deploy the DCM project and the serverless FastAPI application."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

import snowflake.connector
import yaml
from filelock import FileLock

from publishing import (
    ACCOUNT_QUERY,
    ROOT,
    SIMPLE_NAME,
    Catalog,
    Deployment,
    account_identifier,
    build_release,
    compile_catalog,
    current_account,
    managed_role,
    metadata,
    read_previous,
)


def snow(*args: str):
    subprocess.run(["snow", *args, "--secondary-roles", "NONE"], check=True)


def verified_account(profile: str, dep: Deployment, expected: str | None = None) -> str:
    with closing(snowflake.connector.connect(connection_name=profile)) as connection:
        account = current_account(connection)
    result = subprocess.run(
        [
            "snow",
            "sql",
            "-c",
            profile,
            "--enable-templating",
            "NONE",
            "-q",
            ACCOUNT_QUERY,
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("ACCOUNT") != account:
        raise ValueError("Snowflake CLI and Python connector resolved different accounts")
    for target in (dep.account_identifier, expected):
        if target and account != account_identifier(target):
            raise ValueError("Snowflake account does not match the configured target or release")
    return account


class Artifact(NamedTuple):
    repository: str
    package: str
    version: str


def package_versions(connection, schema: str, repository: str, package: str) -> set[str]:
    with closing(connection.cursor()) as db:
        db.execute(f"SHOW ARTIFACT REPOSITORIES LIKE '{repository}' IN SCHEMA {schema}")
        if not any(row["name"] == repository for row in metadata(db)):
            return set()
        db.execute(f"SHOW PACKAGES LIKE '{package}' IN ARTIFACT REPOSITORY {schema}.{repository}")
        if not any(row["name"] == package for row in metadata(db)):
            return set()
        db.execute(
            f"SHOW VERSIONS IN ARTIFACT REPOSITORY {schema}.{repository} FOR PACKAGE {package}"
        )
        return {row["version"] for row in metadata(db)}


def wait_for_service(connection, service: str, expected: Artifact):
    deadline = time.monotonic() + 300
    with closing(connection.cursor()) as db:
        while True:
            db.execute(f"DESCRIBE APPLICATION SERVICE {service}")
            (row,) = metadata(db)
            status = row["status"]
            print(f"{service} is {status}", flush=True)
            url = (row.get("url") or "").removeprefix("https://").rstrip("/")
            ready = re.fullmatch(r"[a-z0-9.-]+\.snowflake\.app", url, re.IGNORECASE)
            idle = str(row.get("is_upgrading")).lower() in {"false", "no", "0"}
            source = row.get("source") or {}
            if isinstance(source, str):
                source = json.loads(source)
            active = (
                source.get("artifactRepository"),
                source.get("package"),
                source.get("version"),
            )
            if status == "RUNNING" and ready and idle and active == expected:
                print(f"https://{url} ({expected.package} {expected.version})")
                return
            if (
                status in {"FAILED", "CANCELLED", "INTERNAL_ERROR", "DELETED"}
                or time.monotonic() >= deadline
            ):
                raise SystemExit(
                    f"Service readiness unconfirmed ({status}, observed {active}, expected {expected}). "
                    "Inspect Snowflake App Runtime logs."
                )
            time.sleep(10)


def existing_reader_grants(profile: str, dep: Deployment, account: str, reader: str) -> list[str]:
    if managed_role(reader) in {dep.app_owner, dep.dcm_role}:
        raise ValueError("The outgoing reader must be distinct from both project owners")
    schema = f"{dep.database_name}.API"
    owned = [
        ("SCHEMAS", f"DATABASE {dep.database_name}", "API", "SCHEMA", schema, "USAGE"),
        (
            "TABLES",
            f"SCHEMA {schema}",
            "DEMO_PRODUCTS",
            "TABLE",
            f"{schema}.DEMO_PRODUCTS",
            "SELECT",
        ),
    ]
    grants = []
    with (
        closing(
            snowflake.connector.connect(
                connection_name=profile, role=dep.dcm_role, warehouse=dep.warehouse_name
            )
        ) as conn,
        closing(conn.cursor()) as db,
    ):
        if current_account(conn) != account:
            raise ValueError("DCM inspection connection does not match the verified account")
        db.execute("USE SECONDARY ROLES NONE")
        for objects, parent, name, kind, qualified, privilege in owned:
            db.execute(f"SHOW {objects} LIKE '{name}' IN {parent}")
            row = next((r for r in metadata(db) if r["name"] == name), None)
            if row is None:
                break
            if row["owner"] != dep.dcm_role:
                raise ValueError(f"Verify DCM ownership of {qualified} before rotating the reader")
            db.execute(f"SHOW GRANTS ON {kind} {qualified}")
            rows = metadata(db)
            if len(rows) >= 10000:
                raise ValueError(f"Cannot verify complete reader grants on {qualified}")
            if any(
                r["granted_to"] == "ROLE"
                and r["grantee_name"] == reader
                and r["privilege"] == privilege
                for r in rows
            ):
                grants.append(f"GRANT {privilege} ON {kind} {qualified} TO ROLE {reader};")
    return grants


def apply_infra(
    profile: str,
    dep: Deployment,
    apply: bool,
    expected_account: str | None = None,
    retain_reader: str | None = None,
) -> bool:
    account = verified_account(profile, dep, expected_account)
    retain = (
        existing_reader_grants(profile, dep, account, retain_reader)
        if retain_reader and retain_reader != dep.reader_role
        else []
    )
    with tempfile.TemporaryDirectory() as tmp:
        project = ROOT / "dcm"
        if retain:
            project = Path(tmp) / "dcm"
            shutil.copytree(ROOT / "dcm", project)
            (project / "sources/definitions/reader-transition.sql").write_text(
                "\n".join(retain) + "\n"
            )
        run_infra(profile, dep, account, project, apply)
    return bool(retain)


def run_infra(profile: str, dep: Deployment, account: str, project: Path, apply: bool):
    flags = [
        "--from",
        str(project),
        "-c",
        profile,
        "--account",
        account,
        "--role",
        dep.dcm_role,
        "--database",
        dep.database_name,
        "--schema",
        "DCM",
        "--warehouse",
        dep.warehouse_name,
    ]
    snow("dcm", "plan", *flags)
    if apply:
        snow("dcm", "deploy", *flags)
        snow(
            "sql",
            "-c",
            profile,
            "--account",
            account,
            "--enable-templating",
            "NONE",
            "--role",
            dep.dcm_role,
            "--database",
            dep.database_name,
            "--schema",
            "API",
            "--warehouse",
            dep.warehouse_name,
            "-f",
            str(ROOT / "setup/seed-demo.sql"),
        )


def prepare(
    args, dep: Deployment, output: Path, previous: Path | None, expected_account: str | None = None
):
    old = read_previous(previous, args.previous_reader)
    account = verified_account(args.connection, dep, old.account if old else expected_account)
    options = {"role": args.metadata_role} if args.metadata_role else {}
    with closing(
        snowflake.connector.connect(
            connection_name=args.connection,
            warehouse=args.metadata_warehouse or dep.warehouse_name,
            **options,
        )
    ) as conn:
        if current_account(conn) != account:
            raise ValueError("Metadata connection does not match the verified Snowflake account")
        catalog = compile_catalog(conn, args.config, dep)
    build_release(catalog, dep, output, old)
    print(
        f"Prepared {output.resolve()}. Review catalog.diff and the grant SQL alongside app/.",
        flush=True,
    )


@contextmanager
def scoped_project(app: Path, manifest: dict, schema: str, stage: str):
    # The CLI uploads a whole directory to its stage root. Each publisher gets an
    # isolated stage; legacy projects also gain an explicit build-job location.
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "app"
        shutil.copytree(app, project)
        (project / "app.yml").write_text(
            yaml.safe_dump(
                {**manifest, "code_stage": stage, "build_job_location": schema}, sort_keys=False
            )
        )
        yield project


@contextmanager
def upload_stage(connection, name: str):
    with closing(connection.cursor()) as db:
        db.execute(f"CREATE STAGE {name} ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')")
        try:
            yield
        finally:
            original_error = sys.exception()
            try:
                db.execute(f"DROP STAGE IF EXISTS {name}")
            except snowflake.connector.Error as cleanup_error:
                if original_error is None:
                    raise
                original_error.add_note(
                    f"Also failed to remove upload stage {name}: {cleanup_error}"
                )


def promote_version(connection, service: str, artifact: Artifact, manifest: dict):
    # CREATE OR ALTER applies the whole service specification on both create and upgrade.
    # These are the serverless service fields from the app.yml v2 reference.
    service_keys = {
        "query_warehouse",
        "url_prefix",
        "health_check",
        "label",
        "description",
        "icon",
        "execute_as_role",
        "auto_resume",
        "auto_suspend_secs",
        "min_instances",
        "max_instances",
        "external_access_integrations",
        "secrets",
        "environment_variables",
        "postgres_instances",
    }
    specification = {k: v for k, v in manifest.items() if k in service_keys and v is not None}
    yaml_spec = yaml.safe_dump(specification, sort_keys=False)
    if "$$" in yaml_spec:
        raise ValueError("Snowflake service specification cannot contain $$")
    with closing(connection.cursor()) as db:
        db.execute(
            f"CREATE OR ALTER APPLICATION SERVICE {service}\n"
            f"FROM ARTIFACT REPOSITORY {artifact.repository} PACKAGE {artifact.package}\n"
            f"VERSION {artifact.version} COMPUTE_RESOURCE = SERVERLESS\nSPECIFICATION = $$\n{yaml_spec}$$"
        )


def publication_lock(account: str, service: str):
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    directory = cache / "snowfastapi" / "publish-locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return FileLock(str(directory / f"{account}.{service}.lock"), timeout=0)


def publish(profile: str, dep: Deployment, release: Path):
    account = verified_account(profile, dep)
    with publication_lock(account, dep.service):
        publish_release(profile, dep, release, account)


def publish_release(profile: str, dep: Deployment, release: Path, account: str):
    app = release.resolve() / "app"
    catalog = Catalog.model_validate_json((app / "catalog.json").read_bytes())
    if (catalog.account, catalog.service, catalog.owner, catalog.warehouse) != (
        account,
        dep.service,
        dep.app_owner,
        dep.warehouse_name,
    ):
        raise ValueError("Release does not match this deployment")
    manifest = yaml.safe_load((app / "app.yml").read_text())
    schema, _, service = dep.service.rpartition(".")
    if (
        manifest.get("targets")
        or manifest.get("default_target")
        or manifest.get("code_workspace")
        or (manifest.get("database"), manifest.get("schema"), manifest.get("name"))
        != (dep.database_name, "API", service)
        or manifest.get("query_warehouse") != dep.warehouse_name
        or manifest.get("build_job_location") not in (None, schema)
        or manifest.get("compute_resource") != "SERVERLESS"
    ):
        raise ValueError("Release app.yml does not match the configured service target")
    repository = manifest["artifact_repo"]
    package = manifest.get("package_name", service)
    if not all(isinstance(n, str) and re.fullmatch(SIMPLE_NAME, n) for n in (repository, package)):
        raise ValueError("Use schema-local, simple uppercase repository and package names")
    stage = f"SNOWFASTAPI_UPLOAD_{uuid4().hex.upper()}"
    with (
        scoped_project(app, manifest, schema, stage) as project,
        closing(
            snowflake.connector.connect(
                connection_name=profile,
                role=dep.app_owner,
                warehouse=dep.warehouse_name,
                database=dep.database_name,
                schema="API",
            )
        ) as conn,
    ):
        if current_account(conn) != account:
            raise ValueError("Release was prepared in another Snowflake account")
        with closing(conn.cursor()) as db:
            db.execute("USE SECONDARY ROLES NONE")
        flags = [
            "--project",
            str(project),
            "-c",
            profile,
            "--account",
            account,
            "--role",
            dep.app_owner,
            "--warehouse",
            dep.warehouse_name,
        ]
        snow("app", "validate", *flags)
        with upload_stage(conn, f"{schema}.{stage}"):
            snow("app", "deploy", "--upload-only", *flags)
            before = package_versions(conn, schema, repository, package)
            snow("app", "deploy", "--build-only", *flags)
            built = package_versions(conn, schema, repository, package) - before
        if len(built) != 1 or not re.fullmatch(r"VERSION\$[0-9]+", next(iter(built))):
            raise ValueError(f"Expected one new immutable package version, found {sorted(built)}")
        expected = Artifact(f"{schema}.{repository}", package, built.pop())
        promote_version(conn, dep.service, expected, manifest)
        wait_for_service(conn, dep.service, expected)
        (release / "published-artifact.json").write_text(
            json.dumps(expected._asdict(), indent=2) + "\n"
        )


def deploy(args, dep: Deployment):
    # Standalone and combined publishers share a lock across local worktrees.
    account = verified_account(args.connection, dep)
    state = ROOT / "build/deployments" / account / dep.service
    state.mkdir(parents=True, exist_ok=True)
    with publication_lock(account, dep.service):
        receipt = state / "last-published.json"
        previous = args.previous or (receipt if receipt.is_file() else None)
        old = read_previous(previous, args.previous_reader)
        if old and (old.account, old.service, old.owner) != (account, dep.service, dep.app_owner):
            raise ValueError(
                "Previous catalog does not match the selected account, service and owner"
            )
        cap = subprocess.run(
            [
                "snow",
                "app",
                "setup",
                "--capabilities",
                "-c",
                args.connection,
                "--account",
                account,
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        flags = json.loads(cap.stdout)
        if any(flags.get(key) is not True for key in ("serverless", "python-serverless")):
            raise ValueError("Snowflake must enable both serverless and python-serverless")
        overlap = apply_infra(
            args.connection,
            dep,
            apply=True,
            expected_account=account,
            retain_reader=old.reader_role if old else None,
        )
        release = state / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
        prepare(args, dep, release, previous, expected_account=account)
        print((release / "catalog.diff").read_text(), flush=True)
        for filename in ("publisher-grants.sql", "caller-grants.sql"):
            snow(
                "sql",
                "-c",
                args.connection,
                "--account",
                account,
                "--enable-templating",
                "NONE",
                "--role",
                args.grant_role,
                "-f",
                str(release / filename),
            )
        publish_release(args.connection, dep, release, account)
        snow(
            "sql",
            "-c",
            args.connection,
            "--account",
            account,
            "--enable-templating",
            "NONE",
            "--role",
            dep.app_owner,
            "--warehouse",
            dep.warehouse_name,
            "-f",
            str(release / "share.sql"),
        )
        if overlap:
            apply_infra(args.connection, dep, apply=True, expected_account=account)
        for name in ("retire-caller-grants.sql", "retire-reader-grants.sql"):
            retire = release / name
            if retire.stat().st_size:
                snow(
                    "sql",
                    "-c",
                    args.connection,
                    "--account",
                    account,
                    "--enable-templating",
                    "NONE",
                    "--role",
                    args.grant_role,
                    "--warehouse",
                    dep.warehouse_name,
                    "-f",
                    str(retire),
                )
        pending = state / "published.tmp"
        pending.write_bytes((release / "app/catalog.json").read_bytes())
        pending.replace(receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser(
        "bootstrap-sql", help="print one-time SQL bound to a Snowflake account"
    )
    source = bootstrap.add_mutually_exclusive_group()
    source.add_argument(
        "-c", "--connection", help="resolve and verify the account with both clients"
    )
    source.add_argument("--account", help="render offline for an organization-account identifier")
    for action in ("plan", "apply-infra", "prepare", "publish", "deploy"):
        cmd = sub.add_parser(action)
        cmd.add_argument("-c", "--connection", required=True)
        if action in ("plan", "apply-infra"):
            cmd.add_argument(
                "--retain-reader",
                help="retain the outgoing reader's existing DCM grants during rotation",
            )
        if action in ("prepare", "deploy"):
            cmd.add_argument("--config", type=Path, default=ROOT / "tables.toml")
            cmd.add_argument("--previous", type=Path, help="previously published catalog.json")
            cmd.add_argument(
                "--previous-reader",
                help="previous managed reader for an unaccompanied legacy catalog",
            )
            cmd.add_argument(
                "--metadata-role", help="role able to inspect and read published objects"
            )
            cmd.add_argument("--metadata-warehouse", help="defaults to the deployment warehouse")
        if action == "prepare":
            cmd.add_argument("--output", type=Path, required=True, help="new release directory")
        if action == "deploy":
            cmd.add_argument(
                "--grant-role", required=True, help="administrator role for generated grants"
            )
        if action == "publish":
            cmd.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    dep = Deployment.load()
    if args.command == "bootstrap-sql":
        account = (
            verified_account(args.connection, dep)
            if args.connection
            else args.account or dep.account_identifier
        )
        if not account:
            parser.error(
                "bootstrap-sql needs -c CONNECTION, --account ORG-ACCOUNT or target account_identifier"
            )
        print(dep.bootstrap(account), end="")
    elif args.command in ("plan", "apply-infra"):
        apply_infra(
            args.connection, dep, args.command == "apply-infra", retain_reader=args.retain_reader
        )
    elif args.command == "publish":
        publish(args.connection, dep, args.release)
    elif args.command == "prepare":
        prepare(args, dep, args.output, args.previous)
    else:
        deploy(args, dep)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr)
        raise SystemExit(error.returncode) from None
