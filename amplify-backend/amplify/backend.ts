import { defineBackend } from "@aws-amplify/backend";
import { Stack, Tags } from "aws-cdk-lib";
import { auth } from "./auth/resource";

// Amplify Gen 2 backend for the HR Accelerator SPA: Cognito only.
// The API (API Gateway + Lambda + Aurora) is Terraform-managed, see Orient_Internal_AI_Deployment/.
// Cognito is provisioned now so it is ready for phase 2 (login via OIDC + a gateway JWT authorizer);
// the application does not use it yet and costs $0 until users exist.
const backend = defineBackend({ auth });

const stack = Stack.of(backend.auth.resources.userPool);

// Cost-allocation tags (same convention as the Terraform and AgentCore stacks).
Tags.of(stack).add("Project", "orient-recruitment-accelerator");
Tags.of(stack).add("Application", "HR Accelerator");
Tags.of(stack).add("Environment", process.env.ORA_ENVIRONMENT ?? "production");
Tags.of(stack).add("Owner", "sumanpramanik@orientindia.net");
Tags.of(stack).add("CostCenter", "Orient_Internal_AI");
Tags.of(stack).add("ManagedBy", "amplify-gen2");

// Security hardening via the CDK escape hatch.
const { cfnUserPool } = backend.auth.resources.cfnResources;
// Staff accounts are created by an administrator only: no public self-registration.
cfnUserPool.adminCreateUserConfig = { allowAdminCreateUserOnly: true };
// Guard against accidental deletion of the user directory.
cfnUserPool.deletionProtection = "ACTIVE";

backend.addOutput({
  custom: {
    region: stack.region,
  },
});
