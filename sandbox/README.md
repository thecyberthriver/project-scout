# Build your safe sandbox

A sandbox is a throwaway computer for running code you did not write. It **minimizes** the risk of something
malicious touching your real laptop. It does not remove risk: a passed automated check is not proof code is safe,
and no sandbox is a perfect wall. So treat every sandbox as disposable, and **never put real secrets, passwords,
API keys, `.env` files or personal data inside one. Public or synthetic data only.**

You build one of two, both free. Do it once, reuse it all year.

## Option A — Google Colab (completely free, start here)

Best for Python, data and notebooks. Runs on Google's computers, so nothing touches your laptop.

1. Go to **colab.research.google.com**, sign in with a Google account.
2. `File → Open notebook → GitHub`, paste this repo, open **sandbox/colab_sandbox.ipynb**.
3. `File → Save a copy in Drive` — now it is *your* reusable sandbox.
4. Follow the numbered cells: confirm you're in Colab, fetch a repo, **read it**, then run it.
5. When done: `Runtime → Disconnect and delete runtime`.

There is no way for this to cost money.

## Option B — Dev Container in GitHub Codespaces or local Docker/Podman

Best for full projects (web apps, databases). More powerful than Colab.

**In Codespaces (cloud, off your machine):**
1. Get the free **GitHub Student Developer Pack**: education.github.com/pack (use your Baruch email).
2. Copy the `sandbox/.devcontainer/` folder into the repo you want to try (or into your own template repo).
3. On that repo: green **Code** button → **Codespaces** → **Create codespace on main**.
4. You get an isolated Ubuntu with Python + Node, a non-root user and capped resources. Run the project there.
5. Delete it at **github.com/codespaces** when done, so it stops using your free quota.

Codespaces is free up to a monthly limit and won't surprise-bill you; past the limit it stops. If you want zero
chance of a charge, use Colab.

**Locally (on your machine, but sealed in a container):**
1. Install **Podman Desktop** (fully free) or Docker Desktop, and VS Code with the **Dev Containers** extension.
2. Open the repo (with `sandbox/.devcontainer/` copied in) in VS Code → "Reopen in Container".
3. The code runs in the container, not on your host. A container shares the host kernel, so it is weaker than a
   cloud sandbox — still disposable, still no secrets.

## The devcontainer, in short

`.devcontainer/devcontainer.json` here builds an Ubuntu 24.04 container that runs as the unprivileged `vscode`
user, adds Python 3.12 and Node LTS, caps CPU/memory/processes, and sets `no-new-privileges`. It is reproducible:
everyone on the team gets the same clean environment, and nothing is installed on the host.
