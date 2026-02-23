# Sancrev Server Restart After pip install

Every `pip install /tmp/cave` or `pip install /tmp/sanctuary-revolution` kills the running sancrev uvicorn server because the package gets replaced underneath it.

**After EVERY pip install of cave or sanctuary-revolution, run:**

```bash
uvicorn sanctuary_revolution.harness.server.http_server:app --port 8080 --host 0.0.0.0 > /tmp/sancrev_server.log 2>&1 &
```

**Also restart the organ daemon if cave was reinstalled:**

```bash
kill $(cat /tmp/heaven_data/organ_daemon.pid 2>/dev/null) 2>/dev/null
sleep 1
python -m cave.core.organ_daemon > /tmp/heaven_data/organ_daemon.log 2>&1 &
```

**The sancrev server is NOT `python -m cave.server.http_server`.** That's the bare cave server without domain endpoints. Always use the uvicorn command above.
