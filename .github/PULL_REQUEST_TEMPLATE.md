## Summary

<!-- What does this PR change and why? 1-3 bullet points. -->

-
-

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behavior change)
- [ ] Documentation
- [ ] Tests

## Checklist

- [ ] Syntax check passes: `cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"`
- [ ] Node check passes: `node --check scripts/claude-code-bridge/server.js`
- [ ] Tests pass: `cd scripts && backend/venv/bin/python -m pytest tests/ -v`
- [ ] No `.env` files committed
- [ ] `!restart` call chain not broken (if `whatsapp_router.py`, `cloud_api.py`, `guards/__init__.py`, or `restart_cmd.py` were touched)

## Related Issues

Closes #
