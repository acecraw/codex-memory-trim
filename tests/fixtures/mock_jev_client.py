"""Offline fixture only. Never sends requests."""
def validate_request(payload):
    assert isinstance(payload['state'], dict)
    assert isinstance(payload['questions'], dict)


def validate_response(response, payload):
    assert set(response['answers']) == set(payload['questions'])
    assert response['model'] == 'jev-mock'


def runtime():
    raise AssertionError('Offline tests must never load credentials')
