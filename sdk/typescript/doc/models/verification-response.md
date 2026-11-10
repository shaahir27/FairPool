
# Verification Response

*This model accepts additional fields of type unknown.*

## Structure

`VerificationResponse`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `allMatch` | `boolean` | Required | - |
| `checkedAt` | `string` | Required | - |
| `expectedCapturedTotalCents` | `number` | Required | - |
| `items` | [`VerificationItem[]`](../../doc/models/verification-item.md) | Required | - |
| `lotId` | `string` | Required | - |
| `matched` | `number` | Required | - |
| `paypalCapturedTotalCents` | `number` | Required | - |
| `total` | `number` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { VerificationResponse } from 'fairpool-merchant-agent-apilib';

const verificationResponse: VerificationResponse = {
  allMatch: false,
  checkedAt: '2016-03-13T12:52:32.123Z',
  expectedCapturedTotalCents: 98,
  items: [
    {
      expectedAmountCents: 150,
      match: false,
      paypalAmountCents: 64,
      paypalCaptureId: 'paypal_capture_id0',
      paypalCaptureStatus: 'paypal_capture_status0',
      paypalOrderId: 'paypal_order_id8',
      additionalProperties: {
        'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
      },
    }
  ],
  lotId: '00001a8a-0000-0000-0000-000000000000',
  matched: 180,
  paypalCapturedTotalCents: 212,
  total: 196,
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

