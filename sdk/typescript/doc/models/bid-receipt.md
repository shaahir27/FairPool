
# Bid Receipt

*This model accepts additional fields of type unknown.*

## Structure

`BidReceipt`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `hash` | `string` | Required | - |
| `signature` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { BidReceipt } from 'fairpool-merchant-agent-apilib';

const bidReceipt: BidReceipt = {
  hash: 'hash4',
  signature: 'signature6',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

