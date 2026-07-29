# Deployment shapes reference

Lookup tables for the `profile:topology` skill. The signature table covers every value
of the `shape` enum in `topology.schema.json`; the dependency and third-party tables
cover the infrastructure and external services this phase is asked to recognize. These
tables read the same inventory `profile:stack` already produced — under `containers`,
`iac`, and `entrypoints` — so match against paths that are already there before reading
anything new.

## Shape signatures

| `shape` | Signature | Notes |
|---|---|---|
| `multi-service` | A compose file (`docker-compose.yml`/`compose.yaml`) or Kubernetes/Helm manifests naming two or more **application** services — each with its own build context or image — or two or more directories in the repo that each carry their own Dockerfile/manifest/entrypoint (a services monorepo). | The distinguishing question is whether more than one component is independently deployable code the repo owns. A compose file with one app service and a `postgres` image is `service-with-dependencies`, not `multi-service` — postgres is infrastructure, not an application component. |
| `service-with-dependencies` | One Dockerfile (or one manifest/entrypoint) plus one or more infrastructure services declared alongside it — a compose file naming exactly one build-from-source service plus database/cache/queue images, or a single app manifest plus an IaC file provisioning a managed datastore. | If the compose file (or manifest) has only the app and nothing else declared, that's `monolith` instead. |
| `monolith` | A single Dockerfile plus a single manifest (or a single entrypoint) and no other declared component or infrastructure dependency — one process, one deployable, nothing else present in `containers`/`iac`. | An empty `real_dependencies` list is expected and correct here. Do not manufacture a dependency that isn't declared anywhere. |
| `serverless` | `serverless.yml`, a `template.yaml`/`template.yml` classified `sam` by content (see caveat), or an IaC file (`cdk.json`, `Pulumi.yaml`) whose program defines function-level resources (Lambda, Cloud Functions, Azure Functions) rather than a container or VM. | `template.yaml` is content-classified, not name-classified: a SAM `Transform` (`AWS::Serverless-2016-10-31`) marks it `sam`, which is serverless evidence. An `AWSTemplateFormatVersion` with no SAM transform marks it plain `cloudformation` instead — that alone does **not** imply serverless, since CloudFormation just as often provisions EC2 instances, ECS services, or RDS. Read the resource types (`AWS::Lambda::Function` versus `AWS::EC2::Instance`/`AWS::ECS::Service`) before assigning shape. A `template.yaml` matching neither marker is not IaC at all (a GitHub issue form or a Backstage software template can share the filename) and proves nothing. The same ambiguity applies to `cdk.json`/`Pulumi.yaml`: both tools provision containers and VPCs as often as functions, so read what the program actually constructs rather than trusting the filename. |
| `cli` | A manifest declaring an installable command (`[project.scripts]` in `pyproject.toml`, `bin` in `package.json`) or a `cmd/*/main.go` layout, with no container/compose file, no IaC, and no code that binds a port or starts a server loop. | A `main.go`/`main.py` entrypoint alone is not enough — plenty of services also have exactly one. Confirm the absence of a listener (`http.ListenAndServe`, `app.listen`, `uvicorn.run`, and the like) before calling this `cli` rather than `monolith`. |
| `library` | A manifest with no entrypoint at all — no path in `entrypoints`, no `[project.scripts]`/`bin`, no `cmd/*/main.go` — and typically no Dockerfile. The manifest exists only to declare a package for other code to import. | Remember that `index.ts`/`index.js` only count as entrypoints at the repo root — nested `index.*` files are barrel re-exports by convention, not evidence of a runnable unit, so their presence deeper in the tree does not disqualify a shape from `library`. An empty `components` list (or a single library-role component) is legitimate; do not force a `real_dependencies` entry onto a library just because example code loads one — read whether the shipped package itself needs it to import, not what a consumer might do with it. |
| `desktop` | A packaging manifest for a desktop shell — `package.json` with an `electron`/`tauri` dependency and a `main` field pointing at a shell process, a `tauri.conf.json`, a `.csproj` with `<OutputType>WinExe</OutputType>` or a WPF/WinForms reference, or a native GUI toolkit dependency (Qt, GTK, SwiftUI/AppKit) with no server entrypoint. | Distinguish from `cli`: a desktop shape ships a GUI process for an end user's machine; a CLI ships a terminal command. Both can lack a Dockerfile — the packaging manifest, not the absence of a container, is the signal. |
| `hybrid` | Two or more of the signatures above are present and each describes a genuinely different kind of deployable — for example one directory is a `library` published for import, another is a `serverless` function, another is a `cli` tool — and `multi-service` framing doesn't apply because they don't share a deployment substrate. | Do not default to `hybrid` just because a repo has both a library-shaped package and a thin wrapper script; check whether the wrapper is really a second deployable or just the library's own usage example. Reserve `hybrid` for cases `multi-service` doesn't fit. |
| `unknown` | None of the above signatures are present with enough confidence — no containers, no IaC, no entrypoints, and the manifest itself doesn't clarify — or the evidence found is contradictory. | Record what's missing in `assumptions[]` (for example, "no container, IaC, or entrypoint evidence found; repo may be a plugin or config-only package") rather than guessing a shape to fill the field. `unknown` is a legitimate, informative answer. |

## Real dependencies

Infrastructure the system genuinely needs to hold state or move data. A client-library
import is stronger evidence than an image name alone — a compose service can be named
`db` with no clue what it runs, but the image line settles it.

| Dependency | Image name(s) | Client library signal | Kind | How normally started |
|---|---|---|---|---|
| postgres | `postgres`, `postgis` | `psycopg`/`psycopg2` (Python), `pg` (Node), `lib/pq`/`pgx` (Go), the `pg` adapter under ActiveRecord (Ruby) | relational database | container/compose service, or a managed instance (RDS, Cloud SQL) reached by connection string |
| mysql | `mysql`, `mariadb` | `mysql-connector-python`/`PyMySQL` (Python), `mysql2` (Node), `go-sql-driver/mysql` (Go) | relational database | container/compose service, or a managed instance |
| redis | `redis`, `redis-stack` | `redis-py` (Python), `ioredis`/`redis` (Node), `go-redis` (Go) | cache / session store / lightweight queue backend | container/compose service, or a managed instance (ElastiCache) |
| rabbitmq | `rabbitmq` | `pika` (Python), `amqplib`/`amqp-connection-manager` (Node), `bunny` (Ruby), `streadway/amqp` (Go) | message queue (AMQP broker) | container/compose service, often with a management-plugin variant in local setups |
| kafka | `confluentinc/cp-kafka`, `bitnami/kafka`, `apache/kafka` | `kafka-python`/`confluent-kafka` (Python), `kafkajs` (Node), `segmentio/kafka-go` (Go) | event streaming log | container/compose service (often paired with a `zookeeper`/KRaft container), or a managed cluster (MSK, Confluent Cloud) |
| elasticsearch | `elasticsearch`, `opensearchproject/opensearch` | `elasticsearch`/`opensearch-py` (Python), `@elastic/elasticsearch` (Node) | search / document index | container/compose service, or a managed cluster |
| minio / S3 | `minio/minio` | `boto3.client("s3")` (Python), `@aws-sdk/client-s3` (Node) with an endpoint override, `aws-sdk-go` `s3.New` | object storage | a `minio` container standing in for S3 locally, or the real AWS S3 service (no container — a bucket name and credentials) |
| mongodb | `mongo` (`mongo-express` is a UI container, not the dependency itself) | `pymongo`/`motor` (Python), `mongoose`/the `mongodb` driver (Node) | document database | container/compose service, or a managed instance (Atlas) |

When only a client library is present with no matching container or IaC evidence, the
dependency is real but externally hosted — record `how_started` as "not self-hosted;
managed instance assumed" and add the gap to `assumptions[]`.

## Third-party services

Services owned by someone else, which a consumer will likely need to substitute.

| Third party | Signal | Used for |
|---|---|---|
| Stripe | `stripe` package (Python/Node/Ruby/Go), base URL `api.stripe.com`, key prefix `sk_`/`pk_` | payment processing |
| Twilio | `twilio` package, base URL `api.twilio.com` | SMS / voice messaging |
| SendGrid | `@sendgrid/mail`/`sendgrid` package, base URL `api.sendgrid.com` | transactional email delivery |
| Auth0 | `auth0`/`@auth0/*` packages, base URL `*.auth0.com` | identity / authentication |
| OpenAI | `openai` package, base URL `api.openai.com` | LLM inference |
| AWS SDK clients | `boto3.client("<service>")` (Python), `new <Service>Client()` from `@aws-sdk/client-<service>` (Node) | depends on the service named in the call — see below |

AWS SDK clients are not a single third party: the service name inside the call decides
where the entry belongs. A client constructed for `s3`, `dynamodb`, `rds`,
`elasticache`, or `sqs`/`sns` used as the system's own queue is infrastructure the
system depends on — record it in `real_dependencies` using the matching row above (or
`kind: "queue"` for SQS/SNS with no self-hosted equivalent in this table). A client
constructed for `ses` (email), `sns` used purely to notify a third party, `rekognition`,
`bedrock`/`comprehend` (managed AI), `cognito` (managed identity), or a similar managed
capability the system doesn't host any part of belongs in `external_third_parties`,
named `AWS <service>` (for example "AWS SES").

## Config mechanisms

A component's actual configuration source is whichever of these its code reads — not
whichever file happens to sit in the repo:

- **Environment variables** — read via `os.environ`/`os.getenv` (Python),
  `process.env` (Node), `os.Getenv` (Go), `ENV[...]` (Ruby). The read call site is the
  evidence, not a `.env.example` file: an example file documents expected keys but
  doesn't prove the running process reads them from the environment rather than, say,
  a secret manager that happens to populate the same names.
- **`.env` files** — loaded via `dotenv`/`python-dotenv`/`godotenv` or an equivalent.
  Confirm the load call exists (`load_dotenv()`, `require("dotenv").config()`) — the
  mere presence of a `.env`/`.env.example` file next to a manifest proves nothing on
  its own.
- **Config files** — YAML/JSON/TOML/INI under a `config/` directory or named
  `config.*`/`settings.*`, parsed by application code (`yaml.safe_load`,
  `configparser`, `viper.ReadInConfig`). Read the parse call to confirm the file is
  loaded, and note whether its values can be overridden by environment variables (a
  common layered pattern) versus being the sole source.
- **Flags** — command-line arguments defined with `argparse`/`click` (Python),
  `cobra`/`flag` (Go), `commander`/`yargs` (Node). Common for `cli`-shaped components;
  rare for long-running services except to set one-off startup behavior (a port, a
  config path).
- **Secret managers** — AWS Secrets Manager / SSM Parameter Store, HashiCorp Vault,
  Doppler, GCP Secret Manager. The evidence is an SDK call at startup
  (`boto3.client("secretsmanager").get_secret_value(...)`, `hvac.Client(...)`), not the
  mere presence of a secrets-manager resource declared in IaC for something else.

When more than one mechanism is present (for example a config file with
environment-variable overrides), name the source that actually supplies each specific
value in `config_source`/`config_needed`, not just the primary file. When you cannot
find the read call at all — only a file that plausibly holds config — say so in
`assumptions[]` rather than asserting the mechanism.

## Standup difficulty

`standup_difficulty` on each `standup_notes` entry takes four values:

- **`trivial`** — a single process with no external state: `python app.py` or
  `go run .` starts it, nothing else needs to be running first, and it needs no
  credentials to reach a functional state. Typical for `library`/`cli` shapes and small
  `monolith`s with no `real_dependencies`.
- **`moderate`** — needs one or more containers or a database, but everything required
  is declared in the repo (a compose file, an IaC file with local defaults) and needs
  no external account or credential beyond what the repo already documents, such as a
  default local password committed for that purpose.
- **`hard`** — needs real credentials, a cloud account, or a manual provisioning step
  not captured in a single command: an IaC apply that provisions non-local cloud
  resources, a service that requires an API key issued out-of-band, or a step
  documented only in prose (a README's "first, create an account…") rather than in
  code.
- **`impractical`** — needs production data, a third-party account that cannot be
  stubbed (no sandbox or non-production credential tier exists or is documented), or
  access this discovery process has no way to obtain — a live payment processor
  account in production mode, a proprietary dataset, a partner's private API.

Base the level on what the component's own configuration demands, not on how
convenient the demand is to satisfy elsewhere — a `hard` dependency doesn't become
`moderate` because a teammate happens to already hold credentials.

---

You are reading, not running. Every claim carries `file:line` evidence. Anything you
believe but did not read goes in `assumptions[]` with why it is unconfirmed.
