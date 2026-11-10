
# Merchant Bid List

*This model accepts additional fields of type unknown.*

## Structure

`MerchantBidList`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `items` | [`BidView[]`](../../doc/models/bid-view.md) | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { MerchantBidList } from 'fairpool-merchant-agent-apilib';

const merchantBidList: MerchantBidList = {
  items: [
    {
      bidId: '00000e34-0000-0000-0000-000000000000',
      currentRevision: 26,
      lotId: '00001d56-0000-0000-0000-000000000000',
      status: 'status0',
      flags: [
        {
          code: 'code0',
          evidence: 'evidence0',
          field: 'field6',
          severity: 'severity2',
          additionalProperties: {
            'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
          },
        }
      ],
      rejectReason: 'String7',
      structured: { 'key1': 'val1', 'key2': 'val2' },
      additionalProperties: {
        'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
      },
    }
  ],
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

