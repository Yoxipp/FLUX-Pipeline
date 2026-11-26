# Security policy

## Supported versions

FLUX is in active development. Only the latest release gets security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub: on the repository page, open **Security > Report a vulnerability**. Include:

* what an attacker can do, and the FLUX version (Settings) where you saw it;
* the steps to reproduce, or a proof of concept;
* whether it needs local access, access to the shared workspace folder, or only the network.

You will get an answer within 7 days. Once a fix is released, the report is made public with credit to you, unless
you prefer to stay anonymous.

## Scope

Useful areas to look at: the local API (FastAPI on `127.0.0.1`, protected by a per-launch token), the plugins and
scripts FLUX copies into the DCC preferences, the YAML actions and Flows that run commands, the update mechanism
(installers read from the shared workspace), and the optional Discord bot.

Out of scope: problems that need an attacker who already controls the user's Windows account, and vulnerabilities in
the DCC software itself (report those to their vendors).
