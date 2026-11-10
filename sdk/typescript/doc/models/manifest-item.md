
# Manifest Item

*This model accepts additional fields of type unknown.*

## Structure

`ManifestItem`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `amountCents` | `number` | Required | - |
| `capturedAt` | `string` | Required | - |
| `paypalCaptureId` | `string` | Required | - |
| `paypalOrderId` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { ManifestItem } from 'fairpool-merchant-agent-apilib';

const manifestItem: ManifestItem = {
  amountCents: 60,
  capturedAt: '2016-03-13T12:52:32.123Z',
  paypalCaptureId: 'paypal_capture_id4',
  paypalOrderId: 'paypal_order_id2',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

