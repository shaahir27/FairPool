
# Bid Flag View

*This model accepts additional fields of type unknown.*

## Structure

`BidFlagView`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `code` | `string` | Required | - |
| `evidence` | `string` | Required | - |
| `field` | `string` | Required | - |
| `severity` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { BidFlagView } from 'fairpool-merchant-agent-apilib';

const bidFlagView: BidFlagView = {
  code: 'code4',
  evidence: 'evidence6',
  field: 'field0',
  severity: 'severity4',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

