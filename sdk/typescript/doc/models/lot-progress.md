
# Lot Progress

*This model accepts additional fields of type unknown.*

## Structure

`LotProgress`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `capturesCompleted` | `number` | Required | - |
| `counts` | `Record<string, number>` | Required | - |
| `fundDeadlineAt` | [`LotProgressFundDeadlineAt \| undefined`](../../doc/models/containers/lot-progress-fund-deadline-at.md) | Optional | This is a container for any-of cases. |
| `holdsPlaced` | `number` | Required | - |
| `labels` | `string[] \| undefined` | Optional | - |
| `lotId` | `string` | Required | - |
| `moq` | `number` | Required | - |
| `refillsOffered` | `number` | Required | - |
| `seats` | `number` | Required | - |
| `status` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { LotProgress } from 'fairpool-merchant-agent-apilib';

const lotProgress: LotProgress = {
  capturesCompleted: 190,
  counts: {
    'key0': 103
  },
  holdsPlaced: 0,
  lotId: '000009d6-0000-0000-0000-000000000000',
  moq: 70,
  refillsOffered: 66,
  seats: 134,
  status: 'status8',
  fundDeadlineAt: '2016-03-13T12:52:32.123Z',
  labels: [
    'labels6'
  ],
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

