from app import auth


def test_hash_password_verifies_correct_password():
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", hashed) is True


def test_hash_password_rejects_wrong_password():
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("wrong password", hashed) is False


def test_verify_password_handles_garbage_hash_gracefully():
    assert auth.verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_session_token_round_trips_to_same_user_id():
    token = auth.create_session_token("user-123")
    assert auth._read_session_token(token) == "user-123"


def test_session_token_rejects_tampered_payload():
    token = auth.create_session_token("user-123")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert auth._read_session_token(tampered) is None
