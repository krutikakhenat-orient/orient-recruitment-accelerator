#!/usr/bin/env python3
"""CDK app entrypoint for the serverless HR trial deployment."""

import os

import aws_cdk as cdk

from ora_stack import OraTrialStack

app = cdk.App()

OraTrialStack(
    app,
    "OraTrial",
    # Account comes from the credentials in use (the AWS profile); region defaults to Mumbai.
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "ap-south-1"),
    ),
    description="Orient Recruitment Accelerator - serverless HR trial (synthetic data only)",
)

# Cost-allocation tags. They are applied to every taggable resource in the stack, but they
# only appear in AWS cost reports after a Billing/payer admin ACTIVATES these keys as
# "user-defined cost allocation tags" (Billing console > Cost allocation tags). Keep the keys
# stable: renaming a key starts a new, separate cost line.
cdk.Tags.of(app).add("project", "orient-recruitment-accelerator")
cdk.Tags.of(app).add("purpose", "hr-trial")
cdk.Tags.of(app).add("environment", "trial")
cdk.Tags.of(app).add("owner", "sumanpramanik")
cdk.Tags.of(app).add("managed-by", "cdk")

app.synth()
