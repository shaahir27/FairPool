
# Bid Response

*This model accepts additional fields of type unknown.*

## Structure

`BidResponse`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bidId` | `string` | Required | - |
| `receipt` | [`BidReceipt`](../../doc/models/bid-receipt.md) | Required | - |
| `revision` | `number` | Required | - |
| `status` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { BidResponse } from 'fairpool-merchant-agent-apilib';

const bidResponse: BidResponse = {
  bidId: '00000418-0000-0000-0000-000000000000',
  receipt: {
    hash: 'hash0',
    signature: 'signature2',
    additionalProperties: {
      'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
    },
  },
  revision: 96,
  status: 'status2',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

