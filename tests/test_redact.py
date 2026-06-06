from omoikane.core.redact import redact, redact_text, REDACTION_PLACEHOLDER


def test_redact_openai_key():
    out = redact_text("Use sk-proj-abc123XYZ456defghijklmnop in headers")
    assert REDACTION_PLACEHOLDER in out
    assert "sk-proj-abc123" not in out


def test_redact_anthropic_key():
    out = redact_text("ANTHROPIC_API_KEY=sk-ant-api03-abcdefg1234567890ABCDEFGH-test_key")
    assert REDACTION_PLACEHOLDER in out


def test_redact_aws_access_key():
    assert REDACTION_PLACEHOLDER in redact_text("AKIAIOSFODNN7EXAMPLE rotated")


def test_redact_github_pat():
    assert REDACTION_PLACEHOLDER in redact_text("token: ghp_abcdefghijklmnopqrstuvwxyz0123456789")


def test_redact_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NSJ9.dGVzdF9zaWdfaGVyZQ"
    assert REDACTION_PLACEHOLDER in redact_text(jwt)


def test_redact_bearer_token():
    out = redact_text("Authorization: Bearer abcd1234efgh5678ijkl9012")
    assert REDACTION_PLACEHOLDER in out


def test_redact_pem_private_key():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIBVQIBADANBgkqhkiG9w0\n-----END PRIVATE KEY-----"
    assert REDACTION_PLACEHOLDER in redact_text(pem)


def test_redact_sensitive_dict_key():
    out = redact({"password": "hunter2", "user": "alice"})
    assert out["password"] == REDACTION_PLACEHOLDER
    assert out["user"] == "alice"


def test_redact_nested():
    out = redact({
        "config": {
            "api_key": "secret-value-here",
            "endpoint": "https://api.example.com",
        },
        "items": [{"token": "tok-1"}, {"name": "ok"}],
    })
    assert out["config"]["api_key"] == REDACTION_PLACEHOLDER
    assert out["config"]["endpoint"] == "https://api.example.com"
    assert out["items"][0]["token"] == REDACTION_PLACEHOLDER
    assert out["items"][1]["name"] == "ok"


def test_redact_inline_kv_in_text():
    out = redact_text("config: api_key=supersecretvalue and rest")
    assert "supersecretvalue" not in out
    assert REDACTION_PLACEHOLDER in out


def test_redact_passthrough_non_sensitive():
    assert redact_text("Normal log line without secrets") == "Normal log line without secrets"
    assert redact({"score": 42, "name": "ok"}) == {"score": 42, "name": "ok"}


def test_redact_handles_none():
    assert redact(None) is None
