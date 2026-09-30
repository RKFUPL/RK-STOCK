from bson import ObjectId

from app.auth import hash_password
from app.utils import now


def collection_record(database, name='Aakaar'):
    key = ''.join(character for character in name.lower() if character.isalnum())
    record = {'_id': ObjectId(), 'name': name, 'slug': key, 'code': key[:3].upper(), 'position': 1, 'active': True}
    database.collections.insert_one(record)
    return record


def test_legacy_collection_values_block_writes_without_discarding_data(client, headers, app):
    database = app.extensions['mongo_db']
    database.collections.insert_many([
        {'name': '', 'slug': 'blank', 'active': True},
        {'name': 'Legacy Aakaar', 'slug': 'legacy-aakaar', 'active': True},
        {'name': ' legacy aAKAAR ', 'slug': 'legacy-aakaar-2', 'active': True},
        {'name': 42, 'slug': 'number', 'active': True},
    ])
    response = client.get('/api/collections', headers=headers)
    assert response.status_code == 200
    assert {issue['kind'] for issue in response.json['legacy_issues']} == {'malformed', 'duplicate'}
    before = list(database.collections.find({}, {'_id': 0}))
    update = client.post('/api/collections', headers=headers, json={'name': 'New', 'revision': 0})
    assert update.status_code == 409
    assert list(database.collections.find({}, {'_id': 0})) == before


def test_collection_rename_and_remove_are_blocked_for_all_reference_collections(client, headers, app):
    database = app.extensions['mongo_db']
    for target in (database.products, database.product_configurations, database.linesheets, database.orders, database.documents):
        record = collection_record(database, f'Used {target.name}')
        target.insert_one({'collection_id': record['_id'], 'collection': record['name']})
        rename = client.patch(f"/api/collections/{record['_id']}", headers=headers, json={'name': 'Renamed', 'revision': 0})
        remove = client.delete(f"/api/collections/{record['_id']}?revision=0", headers=headers)
        assert rename.status_code == 409
        assert remove.status_code == 409
        target.delete_many({'collection_id': record['_id']})
        database.collections.delete_one({'_id': record['_id']})


def test_stale_collection_revision_does_not_overwrite_newer_data(client, headers, app):
    database = app.extensions['mongo_db']
    record = collection_record(database, 'Revision Collection')
    database.settings.insert_one({'_id': 'global', 'collections_revision': 4, 'sizes': ['S'], 'production_stages': ['Cutting']})
    response = client.patch(f"/api/collections/{record['_id']}", headers=headers, json={'name': 'New Name', 'revision': 3})
    assert response.status_code == 409
    stored = database.collections.find_one({'_id': record['_id']})
    assert stored['name'] == 'Revision Collection'
    assert database.settings.find_one({'_id': 'global'})['collections_revision'] == 4


def test_collection_writes_use_effective_permission_and_preserve_settings(client, app):
    database = app.extensions['mongo_db']
    database.users.insert_one({'name': 'Editor', 'email': 'editor@rk.test', 'password_hash': hash_password('strong-editor-password'), 'role': 'sales', 'permissions': ['settings:write'], 'active': True, 'created_at': now()})
    login = client.post('/api/auth/login', json={'email': 'editor@rk.test', 'password': 'strong-editor-password'})
    editor_headers = {'Authorization': f"Bearer {login.json['token']}"}
    database.settings.insert_one({'_id': 'global', 'collections_revision': 0, 'sizes': ['S'], 'production_stages': ['Cutting'], 'other': 'preserve'})
    response = client.post('/api/collections', headers=editor_headers, json={'name': 'New Collection', 'revision': 0})
    assert response.status_code == 201
    settings = database.settings.find_one({'_id': 'global'})
    assert settings['sizes'] == ['S']
    assert settings['production_stages'] == ['Cutting']
    assert settings['other'] == 'preserve'


def test_user_without_settings_permission_can_read_but_cannot_write(client, app):
    database = app.extensions['mongo_db']
    database.users.insert_one({'name': 'Viewer', 'email': 'viewer@rk.test', 'password_hash': hash_password('strong-viewer-password'), 'role': 'sales', 'active': True, 'created_at': now()})
    login = client.post('/api/auth/login', json={'email': 'viewer@rk.test', 'password': 'strong-viewer-password'})
    viewer_headers = {'Authorization': f"Bearer {login.json['token']}"}
    assert client.get('/api/collections', headers=viewer_headers).status_code == 200
    assert client.post('/api/collections', headers=viewer_headers, json={'name': 'Denied', 'revision': 0}).status_code == 403
