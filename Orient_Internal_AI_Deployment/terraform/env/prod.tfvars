# Production. Resource prefix "ora-staging" is historical: this IS the live environment.
# Renaming would recreate the database and every resource, so the prefix is kept.
environment            = "staging"
create_codecommit_repo = true
amplify_branch         = "main"
amplify_stage          = "PRODUCTION"
# app_base_url and agentcore_runtime_arn use the variable defaults (production values).
