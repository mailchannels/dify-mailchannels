"""Create synthetic members with native account/tenant services, without email."""
import json
import sys

sys.path.insert(0, '/app/api')

from app_factory import create_app
from configs import dify_config
from extensions.ext_database import db
from models.account import Account, AccountStatus
from services.account_service import AccountService, TenantService
from sqlalchemy import select

payload = json.load(sys.stdin)
_, app = create_app()
with app.app_context():
    owner = db.session.scalar(select(Account).where(Account.email == payload['owner_email']))
    tenants = TenantService.get_join_tenants(owner, session=db.session)
    assert len(tenants) == 1
    tenant_a = tenants[0]
    TenantService.switch_tenant(owner, tenant_a.id, session=db.session)
    result = {'tenant_a': tenant_a.id, 'accounts': {'owner': owner.id}}
    members = {}
    for role in ['admin', 'editor', 'normal', 'dataset_operator', 'owner_b']:
        account = AccountService.create_account(
            email=payload['emails'][role], name=f'Fixture {role}', interface_language='en-US',
            password=payload['password'], is_setup=True, session=db.session)
        account.status = AccountStatus.ACTIVE
        db.session.commit()
        if role == 'owner_b':
            tenant_b = TenantService.create_owner_tenant(
                account, name='Native role fixture B', is_setup=True, session=db.session)
            result['tenant_b'] = tenant_b.id
        else:
            TenantService.create_tenant_member(tenant_a, account, db.session, role=role)
            TenantService.switch_tenant(account, tenant_a.id, session=db.session)
            db.session.commit()
        members[role] = account
        result['accounts'][role] = account.id
    TenantService.create_tenant_member(tenant_b, members['editor'], db.session, role='normal')
    TenantService.switch_tenant(members['editor'], tenant_a.id, session=db.session)
    TenantService.switch_tenant(members['owner_b'], tenant_b.id, session=db.session)
    result['config'] = {name: getattr(dify_config, name) for name in [
        'RBAC_ENABLED', 'DEPLOYMENT_EDITION', 'MARKETPLACE_ENABLED', 'ALLOW_REGISTER',
        'ALLOW_CREATE_WORKSPACE', 'ENABLE_COLLABORATION_MODE']}
    print('FIXTURE_SEEDED ' + json.dumps(result))
