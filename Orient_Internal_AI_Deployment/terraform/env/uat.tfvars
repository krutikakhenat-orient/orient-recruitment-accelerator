# UAT. Separate copy of everything (database, API, Lambdas, buckets, Cognito, Amplify app),
# built from branch `develop`. SYNTHETIC data only: never copy production candidate data here.
environment            = "uat"
create_codecommit_repo = false # the repository belongs to production
amplify_branch         = "develop"
amplify_stage          = "BETA"
amplify_extra_env      = { ORA_ENVIRONMENT = "uat" }                    # Cognito cost tags
app_base_url           = "https://develop.dtenlsz7vp8yv.amplifyapp.com" # UAT Amplify URL (CORS, links in exports)
agentcore_runtime_arn  = ""                                             # AI interview off in UAT until a UAT agent runtime exists
hr_chatbot_enabled     = true                                           # HR policy chatbot on Bedrock KB (ADR-0017); prod stays off until UAT sign-off
