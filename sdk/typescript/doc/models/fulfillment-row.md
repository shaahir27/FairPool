
# Fulfillment Row

*This model accepts additional fields of type unknown.*

## Structure

`FulfillmentRow`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `buyerOrderId` | `string` | Required | - |
| `city` | `string` | Required | - |
| `countryCode` | `string` | Required | - |
| `itemCents` | `number` | Required | - |
| `line1` | `string` | Required | - |
| `line2` | [`FulfillmentRowLine2 \| undefined`](../../doc/models/containers/fulfillment-row-line-2.md) | Optional | This is a container for any-of cases. |
| `name` | `string` | Required | - |
| `paypalCaptureId` | `string` | Required | - |
| `postalCode` | `string` | Required | - |
| `region` | `string` | Required | - |
| `shippingCents` | `number` | Required | - |
| `taxCents` | `number` | Required | - |
| `totalCents` | `number` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { FulfillmentRow } from 'fairpool-merchant-agent-apilib';

const fulfillmentRow: FulfillmentRow = {
  buyerOrderId: '00000ab6-0000-0000-0000-000000000000',
  city: 'city6',
  countryCode: 'country_code6',
  itemCents: 22,
  line1: 'line18',
  name: 'name6',
  paypalCaptureId: 'paypal_capture_id8',
  postalCode: 'postal_code8',
  region: 'region2',
  shippingCents: 162,
  taxCents: 26,
  totalCents: 38,
  line2: 'String1',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

