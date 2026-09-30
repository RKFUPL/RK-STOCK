def test_category_list_missing_settings_is_empty_without_creating_document(client, headers, app):
    response = client.get('/api/settings/categories', headers=headers)

    assert response.status_code == 200
    assert response.json == {'categories': [], 'usage': {}, 'revision': 0, 'legacy_issues': []}
    assert app.extensions['mongo_db'].settings.count_documents({'_id': 'global'}) == 0


def test_category_list_returns_configured_categories_and_usage(client, headers, app):
    database = app.extensions['mongo_db']
    database.settings.insert_one({'_id': 'global', 'categories': ['Dresses', 'Sarees']})
    database.products.insert_one({'sku': 'D-1', 'category': ' dresses '})

    response = client.get('/api/settings/categories', headers=headers)

    assert response.status_code == 200
    assert response.json == {'categories': ['Dresses', 'Sarees'], 'usage': {'Dresses': 1, 'Sarees': 0}, 'revision': 0, 'legacy_issues': []}


def test_admin_can_save_trimmed_categories_and_preserve_unrelated_settings(client, headers, app):
    database = app.extensions['mongo_db']
    database.settings.insert_one({'_id': 'global', 'sizes': ['XS'], 'production_stages': ['cutting'], 'categories': []})

    response = client.put('/api/settings/categories', headers=headers, json={'categories': [' Dresses ', 'Sarees'], 'revision': 0})

    assert response.status_code == 200
    assert response.json['categories'] == ['Dresses', 'Sarees']
    stored = database.settings.find_one({'_id': 'global'})
    assert stored['categories'] == ['Dresses', 'Sarees']
    assert stored['sizes'] == ['XS']
    assert stored['production_stages'] == ['cutting']


def test_first_category_save_creates_global_settings_safely(client, headers, app):
    database = app.extensions['mongo_db']

    response = client.put('/api/settings/categories', headers=headers, json={'categories': ['Dresses'], 'revision': 0})

    assert response.status_code == 200
    assert database.settings.find_one({'_id': 'global'})['categories'] == ['Dresses']


def test_category_write_requires_settings_permission(client, app):
    database = app.extensions['mongo_db']
    from app.auth import hash_password
    from app.utils import now
    database.users.insert_one({'name': 'Sales', 'email': 'sales@rk.test', 'password_hash': hash_password('strong-sales-password'), 'role': 'sales', 'active': True, 'created_at': now()})
    login = client.post('/api/auth/login', json={'email': 'sales@rk.test', 'password': 'strong-sales-password'})

    response = client.put('/api/settings/categories', headers={'Authorization': f"Bearer {login.json['token']}"}, json={'categories': ['Dresses']})

    assert response.status_code == 403
    assert response.json['error'] == 'Permission denied'


def test_category_payload_is_strict_and_validated(client, headers):
    for payload, expected in (
        ({'categories': 'Dresses'}, 'categories must be an array of strings'),
        ({'categories': ['']}, 'Category names cannot be empty'),
        ({'categories': ['Dresses', ' dresses ']}, 'Category names must be unique, ignoring capitalization'),
        ({'categories': ['x' * 81]}, 'Category names must be 80 characters or fewer'),
        ({'categories': ['Dresses'], 'sizes': ['XS']}, 'Only the categories and revision fields are accepted'),
    ):
        response = client.put('/api/settings/categories', headers=headers, json=payload)
        assert response.status_code == 400
        assert response.json['error'] == expected


def test_category_removal_and_rename_are_blocked_when_products_use_the_name(client, headers, app):
    database = app.extensions['mongo_db']
    database.settings.insert_one({'_id': 'global', 'categories': ['Dresses']})
    database.products.insert_one({'sku': 'D-1', 'category': 'DRESSES'})

    response = client.put('/api/settings/categories', headers=headers, json={'categories': ['Eveningwear'], 'revision': 0})

    assert response.status_code == 409
    assert response.json['in_use'] == ['Dresses']
    assert database.settings.find_one({'_id': 'global'})['categories'] == ['Dresses']


def test_unused_category_can_be_removed_or_renamed(client, headers, app):
    database = app.extensions['mongo_db']
    database.settings.insert_one({'_id': 'global', 'categories': ['Dresses', 'Unused']})

    rename = client.put('/api/settings/categories', headers=headers, json={'categories': ['Dresses', 'Eveningwear'], 'revision': 0})
    remove = client.put('/api/settings/categories', headers=headers, json={'categories': ['Dresses'], 'revision': 1})

    assert rename.status_code == 200
    assert remove.status_code == 200
    assert database.settings.find_one({'_id': 'global'})['categories'] == ['Dresses']


def test_legacy_categories_are_reported_and_writes_fail_closed(client, headers, app):
    database = app.extensions['mongo_db']
    database.settings.insert_one({'_id': 'global', 'categories': ['Dresses', ' dresses ', '', 7]})

    response = client.get('/api/settings/categories', headers=headers)
    assert response.status_code == 200
    assert response.json['categories'] == ['Dresses']
    assert len(response.json['legacy_issues']) == 3

    update = client.put('/api/settings/categories', headers=headers, json={'categories': ['Dresses'], 'revision': 0})
    assert update.status_code == 409
    assert database.settings.find_one({'_id': 'global'})['categories'] == ['Dresses', ' dresses ', '', 7]


def test_stale_category_revision_is_rejected_without_overwriting_newer_values(client, headers, app):
    database = app.extensions['mongo_db']
    database.settings.insert_one({'_id': 'global', 'categories': ['Dresses'], 'categories_revision': 4})

    response = client.put('/api/settings/categories', headers=headers, json={'categories': ['Sarees'], 'revision': 3})

    assert response.status_code == 409
    stored = database.settings.find_one({'_id': 'global'})
    assert stored['categories'] == ['Dresses']
    assert stored['categories_revision'] == 4


def test_user_level_settings_permission_is_effective(client, app):
    database = app.extensions['mongo_db']
    from app.auth import hash_password
    from app.utils import now
    database.users.insert_one({'name': 'Settings editor', 'email': 'settings@rk.test', 'password_hash': hash_password('strong-settings-password'), 'role': 'sales', 'permissions': ['settings:write'], 'active': True, 'created_at': now()})
    login = client.post('/api/auth/login', json={'email': 'settings@rk.test', 'password': 'strong-settings-password'})
    response = client.put('/api/settings/categories', headers={'Authorization': f"Bearer {login.json['token']}"}, json={'categories': ['Dresses'], 'revision': 0})
    assert response.status_code == 200
    me = client.get('/api/auth/me', headers={'Authorization': f"Bearer {login.json['token']}"})
    assert 'settings:write' in me.json['effective_permissions']
