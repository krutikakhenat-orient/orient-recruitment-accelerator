# HR Accelerator: AWS architecture (Orient_Internal_AI account, ap-south-1)

```mermaid
flowchart TB
  cand([Candidate browser])
  hr([HR user browser])

  subgraph acct["AWS account Orient_Internal_AI, ap-south-1"]
    amp["Amplify Hosting<br/>React SPA<br/>/api/* rewrite"]
    apigw["API Gateway HTTP API<br/>throttling + access logs<br/>only entry to Lambda"]

    subgraph vpc["VPC"]
      nat["fck-nat + EIP"]
      api["Lambda api<br/>FastAPI: app JWT, RBAC,<br/>checks interview link token,<br/>signs wss URL locally"]
      ops["Lambda ops<br/>migrate / seed<br/>IAM invoke only"]
      db[("Aurora Serverless v2<br/>private, encrypted")]
    end

    files[("S3 files<br/>private")]
    role["Lambda IAM role<br/>InvokeAgentRuntime<br/>+ WebSocketStream<br/>this runtime ARN only"]

    subgraph ac["AgentCore interview runtime (IAM / SigV4 inbound auth)"]
      pol["Resource policy:<br/>Allow api Lambda role<br/>Deny all other principals<br/>Deny user-id delegation"]
      agent["Agent: /ws, validates<br/>join_token + session id"]
    end
    ai["Transcribe / Polly / Bedrock"]
    res[("S3 interview results")]
  end

  hr -->|HTTPS| amp
  cand -->|HTTPS + single-use link token| amp
  amp -->|/api/*| apigw --> api
  api --> db
  ops --> db
  api --> files
  api -->|InvokeAgentRuntime: prepare, via NAT| nat --> pol
  api -.-> role
  api -->|returns pre-signed wss, 60 s,<br/>bound to session id| cand
  cand ==>|WebSocket, SigV4 pre-signed URL| pol
  pol --> agent
  agent --> ai
  agent --> res
  agent -.->|HMAC webhook, to wire| apigw
```

## Notes
- **Entry point:** API Gateway is the only way to reach the `api` Lambda. There is no Lambda Function URL.
- **`ops` Lambda:** runs migrations and seeding. No public URL, IAM invoke only.
- **Agent auth:** the interview runtime uses IAM (SigV4) inbound auth. A runtime supports IAM or JWT, not both. Candidates connect with a 60-second SigV4 pre-signed `wss://` URL minted by the `api` Lambda after it checks their single-use link token.
- **Runtime lock:** `scripts/lock-agent-runtime.ps1` attaches a resource policy that allows only the `api` Lambda role and denies every other principal.
- **Cost tags:** every resource carries Project, Application, Environment, Owner, CostCenter and ManagedBy.
- **CI/CD:** one GitHub Actions pipeline (`.github/workflows/deploy-orient-internal-ai.yml`) deploys infrastructure, backend, migrations and frontend.

## Not yet done
- The agent-to-HR-API result webhook is not wired.
- The Terraform still has the VPC and NAT. The Data API and Cognito changes are a later phase.
- Nothing is deployed yet.
