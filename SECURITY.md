# Security Policy

Report vulnerabilities through the repository host's private vulnerability
reporting channel before public disclosure. Do not include exploit details,
credentials, or private dataset assets in a public issue.

CAD-EvoLoop can execute unrestricted AutoCAD commands and AutoLISP through a
local MCP server. Run it only in a trusted workspace, keep credentials out of
prompts and logs, and use isolated Core Console jobs for unattended campaigns.
The MCP audit layer redacts common secret fields but is not a substitute for
credential isolation.

Dataset output files and holdout evaluator assets must never be exposed to the
drawing agent or a candidate system modifier.
