# Security Policy

Report vulnerabilities privately to the repository maintainers before public
disclosure.

CAD-EvoLoop can execute unrestricted AutoCAD commands and AutoLISP through a
local MCP server. Run it only in a trusted workspace, keep credentials out of
prompts and logs, and use isolated Core Console jobs for unattended campaigns.
The MCP audit layer redacts common secret fields but is not a substitute for
credential isolation.

Dataset output files and holdout evaluator assets must never be exposed to the
drawing agent or a candidate system modifier.
