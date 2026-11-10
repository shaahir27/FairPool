
# Bid View

*This model accepts additional fields of type unknown.*

## Structure

`BidView`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bidId` | `string` | Required | - |
| `currentRevision` | `number` | Required | - |
| `flags` | [`BidFlagView[] \| undefined`](../../doc/models/bid-flag-view.md) | Optional | - |
| `lotId` | `string` | Required | - |
| `rejectReason` | [`BidViewRejectReason \| undefined`](../../doc/models/containers/bid-view-reject-reason.md) | Optional | This is a container for any-of cases. |
| `status` | `string` | Required | - |
| `structured` | [`BidViewStructured \| undefined`](../../doc/models/containers/bid-view-structured.md) | Optional | This is a container for any-of cases. |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { BidView } from 'fairpool-merchant-agent-apilib';

const bidView: BidView = {
  bidId: '0000171a-0000-0000-0000-000000000000',
  currentRevision: 16,
  lotId: '00001470-0000-0000-0000-000000000000',
  status: 'status2',
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
  rejectReason: 'String5',
  structured: { 'key1': 'val1', 'key2': 'val2' },
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

