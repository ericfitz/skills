# Arazzo 1.0 authoring reference

One page: the document shapes the `arazzo` skill emits, and the doctrine for
mapping journeys onto them. Normative source: https://spec.openapis.org/arazzo/v1.0.1.html

## Document skeleton

```yaml
arazzo: 1.0.1
info:
  title: <project> workflows
  version: 1.0.0
sourceDescriptions:
  - name: api                    # referenced by operation bindings
    url: api/openapi.yaml        # relative path to the OpenAPI spec
    type: openapi
workflows:
  - workflowId: place-order
    summary: Place an order
    description: <journey narrative>
    dependsOn: [register-account]     # workflow-level prerequisites
    inputs:                           # JSON Schema for runtime inputs
      type: object
      properties:
        apiKey: { type: string }
    steps: [...]
    outputs:
      orderId: $steps.create-order.outputs.orderId
```

## Step shape

```yaml
- stepId: create-order
  description: Create the order from the cart
  operationId: createOrder          # must exist in the source description
  # or, when the spec has no operationIds:
  # operationPath: '{$sourceDescriptions.api.url}#/paths/~1orders/post'
  parameters:
    - name: X-Api-Key
      in: header
      value: $inputs.apiKey
  requestBody:
    contentType: application/json
    payload:
      cartId: $steps.build-cart.outputs.cartId
  successCriteria:
    - condition: $statusCode == 201
  outputs:
    orderId: $response.body#/id
```

## Runtime expressions

| Expression | Meaning |
|---|---|
| `$statusCode` | HTTP status of the current step's response |
| `$response.body#/ptr` | JSON Pointer into the response body |
| `$steps.<stepId>.outputs.<name>` | a prior step's declared output |
| `$inputs.<name>` | a workflow input |
| `$sourceDescriptions.<name>.url` | a source description's URL (for operationPath) |

## Mapping doctrine (journeys → workflows)

- One workflow per confirmed journey. `workflowId` = journey `id` sanitized
  to `[A-Za-z0-9_\-]+`; `dependsOn` = the journey's `depends_on` edges.
- Decompose the narrative into calls; bind every step to a real operation.
  `operationId` preferred; `operationPath` only when the spec declares no ids.
- Chain state explicitly: anything a later step needs (created id, token,
  cursor) becomes an `outputs` entry on the producing step and a runtime
  expression on the consumer. Do not restate literals the API returns.
- `successCriteria` defaults to the 2xx the spec declares for the operation
  (`$statusCode == 201` for a create, etc.); add body conditions only when
  the journey's observable outcome demands them.
- Journeys with no bindable operation (CLI/UI actors) are flagged and
  skipped at the gate — never force-mapped, never fabricated.

### Worked example

Journey (from the journeys doc contract):

```json
{ "id": "checkout", "name": "Check out the cart", "actor": "shopper",
  "narrative": "A shopper with a full cart pays and receives an order id.",
  "entry_point": "POST /orders", "depends_on": ["build-cart"], "rank": 1 }
```

Becomes:

```yaml
- workflowId: checkout
  summary: Check out the cart
  description: A shopper with a full cart pays and receives an order id.
  dependsOn: [build-cart]
  steps:
    - stepId: create-order
      operationId: createOrder
      requestBody:
        contentType: application/json
        payload:
          cartId: $steps.build-cart.outputs.cartId
      successCriteria:
        - condition: $statusCode == 201
      outputs:
        orderId: $response.body#/id
  outputs:
    orderId: $steps.create-order.outputs.orderId
```
