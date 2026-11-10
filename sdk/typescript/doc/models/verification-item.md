
# Verification Item

*This model accepts additional fields of type unknown.*

## Structure

`VerificationItem`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `expectedAmountCents` | `number` | Required | - |
| `match` | `boolean` | Required | - |
| `paypalAmountCents` | `number` | Required | - |
| `paypalCaptureId` | `string` | Required | - |
| `paypalCaptureStatus` | `string` | Required | - |
| `paypalOrderId` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { VerificationItem } from 'fairpool-merchant-agent-apilib';

const verificationItem: VerificationItem = {
  expectedAmountCents: 64,
  match: false,
  paypalAmountCents: 22,
  paypalCaptureId: 'paypal_capture_id6',
  paypalCaptureStatus: 'paypal_capture_status6',
  paypalOrderId: 'paypal_order_id4',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

