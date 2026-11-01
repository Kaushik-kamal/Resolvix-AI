# Resolvix contracts v1.0.0 (FROZEN)

Every cross-component payload is defined here. Models use `extra="forbid"`, so drift fails loudly.

Change process: propose in team chat → all three agree → edit models → bump CONTRACT_VERSION →
regenerate jsonschema/ and fixtures → `pytest contracts/tests` green in all three environments.

Ownership of config content: departments.yaml = frozen with contracts; urgency_rules.yaml = Member B;
sms_templates.yaml = Member C. Structure of all three is part of the contract.
