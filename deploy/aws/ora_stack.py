"""Serverless HR-trial stack for the Orient Recruitment Accelerator.

Request path:  browser -> CloudFront -> (S3: React site)  |  (/api/* -> API Gateway -> Lambda)
Data:          Aurora Serverless v2 PostgreSQL (scales to 0 ACU and pauses when idle)
Files:         one private S3 bucket (resumes, JDs, induction video)

Cost/safety choices for a short-lived trial:
  * Reuses the account's default VPC (the account is at its VPC quota). No NAT gateway: S3 is
    reached through the default VPC's existing gateway endpoint, and the Lambdas have no
    internet access (none is needed). Aurora is not publicly accessible.
  * Secrets are CloudFormation NoEcho parameters passed at deploy time (not in the template).
  * Everything is removable with `cdk destroy` (buckets are emptied, DB is not retained).
  * Synthetic data only: the malware scanner is the development heuristic and there is no WAF.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    CfnParameter,
    Duration,
    Fn,
    RemovalPolicy,
    SecretValue,
    Stack,
)
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

HERE = Path(__file__).resolve().parent
LAMBDA_DIR = HERE / "build" / "lambda"
FRONTEND_DIST = HERE.parent.parent / "frontend" / "dist"

# Rewrites extension-less paths (SPA routes such as /campaigns/123) to index.html. Applied only
# to the site behaviour, so real API 404s under /api/* are never turned into HTML.
_SPA_REWRITE = """
function handler(event) {
  var request = event.request;
  if (request.uri.indexOf('.') === -1) { request.uri = '/index.html'; }
  return request;
}
"""


class OraTrialStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not LAMBDA_DIR.is_dir():
            raise RuntimeError("Lambda package missing - run build_lambda.ps1 first")
        if not (FRONTEND_DIST / "index.html").is_file():
            raise RuntimeError("Frontend build missing - run `npm run build` in frontend/ first")

        # ---- Secrets supplied at deploy time (never stored in the template) -------------
        db_password = CfnParameter(self, "DbPassword", type="String", no_echo=True, min_length=16)
        jwt_secret = CfnParameter(self, "JwtSecret", type="String", no_echo=True, min_length=32)
        seed_password = CfnParameter(self, "SeedPassword", type="String", no_echo=True, min_length=12)
        # Public site URL, known only after the first deploy (breaks a CloudFront<->Lambda cycle).
        app_base_url = self.node.try_get_context("app_base_url") or ""

        # ---- Network: reuse the account's DEFAULT VPC (the account is at its VPC quota) --
        # Nothing in the shared VPC is modified: we only add our own security groups, a DB
        # subnet group and Lambda network interfaces. The default VPC already has an S3
        # gateway endpoint on its route table (verified), which is the only AWS service the
        # Lambdas need. Its subnets are "public" (route to an internet gateway), but nothing
        # here gets a public IP: Aurora is not publicly accessible and Lambda ENIs never get
        # one, so the functions have no internet path and the database has no public path.
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        isolated = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        lambda_sg = ec2.SecurityGroup(self, "LambdaSg", vpc=vpc, allow_all_outbound=True)

        # ---- Database: Aurora Serverless v2 PostgreSQL, scales to zero when idle ---------
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, allow_all_outbound=False)
        cluster = rds.DatabaseCluster(
            self,
            "Db",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                # 16.8 supports scaling to 0 ACU (verified with `describe-db-engine-versions`).
                version=rds.AuroraPostgresEngineVersion.of("16.8", "16")
            ),
            credentials=rds.Credentials.from_password(
                "ora_admin", SecretValue.cfn_parameter(db_password)
            ),
            default_database_name="ora",
            writer=rds.ClusterInstance.serverless_v2("writer", publicly_accessible=False),
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=2,
            serverless_v2_auto_pause_duration=Duration.minutes(5),
            vpc=vpc,
            vpc_subnets=isolated,
            security_groups=[db_sg],
            storage_encrypted=True,
            backup=rds.BackupProps(retention=Duration.days(1)),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY,
        )
        db_sg.add_ingress_rule(lambda_sg, ec2.Port.tcp(5432), "Lambda to Aurora")

        # ---- Private file bucket (resumes, JDs, induction video) -------------------------
        files = s3.Bucket(
            self,
            "Files",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            # The browser plays the induction video straight from a short-lived signed GET
            # link; the signature is the credential, so any origin may issue the GET.
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.HEAD],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )

        # ---- Lambda functions (one package, two entrypoints) -----------------------------
        db_url = Fn.join(
            "",
            [
                "postgresql+psycopg://ora_admin:",
                db_password.value_as_string,
                "@",
                cluster.cluster_endpoint.hostname,
                ":5432/ora",
            ],
        )
        common_env = {
            # `staging` turns on the production-safety checks (strong secret, no localhost
            # CORS, no SQLite), hides /docs and the dev-only router.
            "ORA_ENVIRONMENT": "staging",
            "ORA_DATABASE_URL": db_url,
            "ORA_JWT_SECRET": jwt_secret.value_as_string,
            # Browser traffic is same-origin through CloudFront, so CORS is not exercised;
            # a non-localhost value is still required by the safety check.
            # (A JSON array: pydantic-settings decodes list fields from the environment as JSON.)
            "ORA_CORS_ALLOWED_ORIGINS": '["https://trial.invalid"]',
            "ORA_S3_BUCKET": files.bucket_name,
            "ORA_DB_NULL_POOL": "true",
        }
        if app_base_url:
            common_env["ORA_APP_BASE_URL"] = app_base_url

        def make_function(name: str, handler: str, timeout: Duration, env: dict[str, str]):
            return _lambda.Function(
                self,
                name,
                runtime=_lambda.Runtime.PYTHON_3_12,
                architecture=_lambda.Architecture.X86_64,
                handler=handler,
                code=_lambda.Code.from_asset(str(LAMBDA_DIR)),
                memory_size=1024,
                timeout=timeout,
                vpc=vpc,
                vpc_subnets=isolated,
                # Default-VPC subnets are public; Lambda ENIs get no public IP, so this is
                # only a CDK safeguard we acknowledge (the functions need no internet).
                allow_public_subnet=True,
                security_groups=[lambda_sg],
                environment=env,
                log_group=logs.LogGroup(
                    self,
                    f"{name}Logs",
                    retention=logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            )

        api_fn = make_function(
            "ApiFunction", "app.lambda_handler.handler", Duration.seconds(29), common_env
        )
        ops_fn = make_function(
            "OpsFunction",
            "app.ops_handler.handler",
            Duration.minutes(15),
            {**common_env, "ORA_SEED_PASSWORD": seed_password.value_as_string},
        )
        for fn in (api_fn, ops_fn):
            files.grant_read_write(fn)
            fn.node.add_dependency(cluster)

        # ---- HTTP API in front of the API Lambda -----------------------------------------
        http_api = apigw.HttpApi(
            self,
            "HttpApi",
            create_default_stage=False,
            default_integration=integrations.HttpLambdaIntegration("ApiIntegration", api_fn),
        )
        apigw.HttpStage(
            self,
            "ApiStage",
            http_api=http_api,
            stage_name="$default",
            auto_deploy=True,
            # Basic abuse protection (there is no WAF in this trial).
            throttle=apigw.ThrottleSettings(rate_limit=50, burst_limit=100),
        )
        api_domain = Fn.select(2, Fn.split("/", http_api.api_endpoint))

        # ---- Static site + /api proxy through CloudFront ---------------------------------
        site = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        spa_rewrite = cf.Function(
            self,
            "SpaRewrite",
            code=cf.FunctionCode.from_inline(_SPA_REWRITE),
            runtime=cf.FunctionRuntime.JS_2_0,
        )
        distribution = cf.Distribution(
            self,
            "Cdn",
            default_root_object="index.html",
            price_class=cf.PriceClass.PRICE_CLASS_200,
            minimum_protocol_version=cf.SecurityPolicyProtocol.TLS_V1_2_2021,
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                function_associations=[
                    cf.FunctionAssociation(
                        function=spa_rewrite, event_type=cf.FunctionEventType.VIEWER_REQUEST
                    )
                ],
            ),
            additional_behaviors={
                "/api/*": cf.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        api_domain, protocol_policy=cf.OriginProtocolPolicy.HTTPS_ONLY
                    ),
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                    cache_policy=cf.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY,
                )
            },
        )
        s3deploy.BucketDeployment(
            self,
            "SiteDeployment",
            sources=[s3deploy.Source.asset(str(FRONTEND_DIST))],
            destination_bucket=site,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ---- Outputs used by deploy.ps1 ---------------------------------------------------
        CfnOutput(self, "SiteUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "FilesBucketName", value=files.bucket_name)
        CfnOutput(self, "OpsFunctionName", value=ops_fn.function_name)
        CfnOutput(self, "DbEndpoint", value=cluster.cluster_endpoint.hostname)
