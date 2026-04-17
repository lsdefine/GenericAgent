# Python Quick Example — Hello World

A minimal example to run GenericAgent's demo loop.

1. Clone & enter:

```bash
git clone https://github.com/lsdefine/GenericAgent.git && cd GenericAgent
```

2. Install minimal deps (recommended in a venv):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt 2>/dev/null || echo "No requirements.txt or optional deps"
```

3. Run the demo loop:

```bash
python launch.pyw
```

If you see the agent prompt or logs, the demo started successfully.
