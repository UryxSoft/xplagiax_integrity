"""Operator commands: ``flask --app integrity.app:create_app integrity <cmd>``."""

from __future__ import annotations

import click
from flask.cli import AppGroup
from flask import Flask, current_app
from sqlalchemy import select

from integrity.domain.enums import ActorType, ClientScope, UserRole
from integrity.infrastructure.db.models import Organization, ServiceClient, User
from integrity.infrastructure.db.session import session_scope
from integrity.security.api_keys import generate_key
from integrity.security.audit import record_audit_event


def register_cli(app: Flask) -> None:
    group = AppGroup("integrity", help="XplagiaX Integrity operator commands.")

    @group.command("create-org")
    @click.option("--external-ref", required=True, help="Organisation id in xplagiax_appcli2.")
    @click.option("--name", required=True)
    def create_org(external_ref: str, name: str) -> None:
        with session_scope(current_app) as s:
            if s.scalar(select(Organization).where(Organization.external_ref == external_ref)):
                raise click.ClickException("organization already exists")
            org = Organization(external_ref=external_ref, name=name)
            s.add(org)
            s.flush()
            record_audit_event(s, action="organization.created", actor_type=ActorType.SYSTEM,
                               actor_id="cli", organization_id=org.id, target_type="organization", target_id=org.id)
            click.echo(org.id)

    @group.command("create-user")
    @click.option("--org-ref", required=True)
    @click.option("--external-ref", required=True)
    @click.option("--role", type=click.Choice([r.value for r in UserRole]), default=UserRole.MEMBER.value)
    def create_user(org_ref: str, external_ref: str, role: str) -> None:
        with session_scope(current_app) as s:
            org = s.scalar(select(Organization).where(Organization.external_ref == org_ref))
            if org is None:
                raise click.ClickException("organization not found")
            user = User(organization_id=org.id, external_ref=external_ref, role=UserRole(role))
            s.add(user)
            s.flush()
            record_audit_event(s, action="user.created", actor_type=ActorType.SYSTEM, actor_id="cli",
                               organization_id=org.id, target_type="user", target_id=user.id)
            click.echo(user.id)

    @group.command("create-client")
    @click.option("--name", required=True)
    @click.option("--scope", type=click.Choice([s.value for s in ClientScope]), required=True)
    @click.option("--org-ref", default=None, help="Required for --scope organization.")
    def create_client(name: str, scope: str, org_ref: str | None) -> None:
        """Create a service client. The key is printed ONCE and never stored."""
        scope_enum = ClientScope(scope)
        if (scope_enum == ClientScope.ORGANIZATION) != (org_ref is not None):
            raise click.ClickException("--org-ref is required for organization scope and forbidden otherwise")
        pepper = current_app.config["XI_SETTINGS"].effective_pepper
        with session_scope(current_app) as s:
            org_id = None
            if org_ref:
                org = s.scalar(select(Organization).where(Organization.external_ref == org_ref))
                if org is None:
                    raise click.ClickException("organization not found")
                org_id = org.id
            key = generate_key(pepper)
            client = ServiceClient(name=name, key_prefix=key.prefix, key_hash=key.digest,
                                   scope=scope_enum, organization_id=org_id)
            s.add(client)
            s.flush()
            record_audit_event(s, action="service_client.created", actor_type=ActorType.SYSTEM, actor_id="cli",
                               organization_id=org_id, target_type="service_client", target_id=client.id,
                               details={"scope": scope, "key_prefix": key.prefix})
            click.echo(f"client_id={client.id}")
            click.echo(f"api_key={key.plaintext}")
            click.echo("Store this key in a secret manager now. It cannot be recovered.", err=True)

    @group.command("revoke-client")
    @click.argument("client_id")
    def revoke_client(client_id: str) -> None:
        from integrity.core.ids import utcnow

        with session_scope(current_app) as s:
            client = s.get(ServiceClient, client_id)
            if client is None:
                raise click.ClickException("client not found")
            client.is_active = False
            client.revoked_at = utcnow()
            record_audit_event(s, action="service_client.revoked", actor_type=ActorType.SYSTEM, actor_id="cli",
                               organization_id=client.organization_id, target_type="service_client", target_id=client.id)
            click.echo("revoked")

    app.cli.add_command(group)
